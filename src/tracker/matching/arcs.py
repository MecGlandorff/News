import json

from src.llm import (
    create_cached_chat_completion,
    mark_schema_failure,
    parse_json_object,
    save_cached_chat_completion,
)
from src.tracker.matching.candidates import chunked, compact_current_article
from src.tracker.matching.constants import (
    ARC_ACCEPT_RELATIONSHIPS,
    ARC_ASSIGNMENT_CASES_PER_CALL,
    ARC_ASSIGNMENT_PROMPT,
    ARC_ASSIGNMENT_PROMPT_VERSION,
    ARC_CANDIDATES_PER_LABEL,
    ARC_RELATIONSHIPS,
    DELTA_CHAR_LIMIT,
    LABEL_STOPWORDS,
    SUMMARY_CHAR_LIMIT,
    TITLE_CHAR_LIMIT,
    VERIFY_ARTICLES_PER_CASE,
    VERIFY_CONFIDENCE_VALUES,
)
from src.tracker.matching.labels import (
    clean_list,
    clean_string,
    days_since,
    distinctive_label_tokens,
    label_tokens,
    truncate_text,
)


def recent_arc_text(arc):
    if not isinstance(arc, dict):
        return ""
    parts = [
        arc.get("canonical_label", ""),
        arc.get("theme", ""),
    ]
    for story in arc.get("recent_stories", []):
        parts.extend([
            story.get("canonical_label", ""),
            story.get("summary", ""),
            story.get("delta_summary", ""),
            story.get("parent_label", ""),
        ])
    return " ".join(str(part or "") for part in parts)


def arc_candidate_score(today_label, arc, today=None, default_days=14):
    today_tokens = distinctive_label_tokens(today_label)
    arc_tokens = distinctive_label_tokens(recent_arc_text(arc))
    shared_tokens = today_tokens & arc_tokens
    score = len(shared_tokens) * 10

    today_all_tokens = label_tokens(today_label)
    arc_all_tokens = label_tokens(recent_arc_text(arc))
    score += len((today_all_tokens & arc_all_tokens) - LABEL_STOPWORDS) * 2

    if not score:
        return 0

    if isinstance(arc, dict) and today is not None:
        age_days = days_since(arc.get("last_seen"), today, default_days)
        score += max(0, 8 - age_days)

    return score


def compact_arc_option(arc):
    recent_stories = []
    for story in arc.get("recent_stories", [])[:5]:
        item = {
            "story_id": story.get("story_id"),
            "canonical_label": truncate_text(story.get("canonical_label", ""), TITLE_CHAR_LIMIT),
            "last_seen": story.get("last_seen", ""),
        }
        if story.get("parent_story_id"):
            item["parent_story_id"] = story.get("parent_story_id")
        if story.get("parent_label"):
            item["parent_label"] = truncate_text(story.get("parent_label", ""), TITLE_CHAR_LIMIT)
        if story.get("delta_summary"):
            item["last_delta"] = truncate_text(story["delta_summary"], DELTA_CHAR_LIMIT)
        if story.get("summary"):
            item["summary"] = truncate_text(story["summary"], SUMMARY_CHAR_LIMIT)
        recent_stories.append(item)

    return {
        "arc_id": arc.get("arc_id"),
        "canonical_label": truncate_text(arc.get("canonical_label", ""), TITLE_CHAR_LIMIT),
        "theme": arc.get("theme", ""),
        "last_seen": arc.get("last_seen", ""),
        "active_days": arc.get("active_days", 0),
        "recent_stories": recent_stories,
    }


def arc_assignment_cases_for_prompt(
    today_labels,
    recent_arcs,
    story_groups,
    today=None,
    limit=ARC_CANDIDATES_PER_LABEL,
    default_days=14,
):
    cases = []
    # Audit copies of the supplied candidates, kept out of the prompt cases so
    # prompt bytes (and the response cache) stay unchanged.
    candidate_audit = {}
    arcs = list(recent_arcs.values()) if isinstance(recent_arcs, dict) else list(recent_arcs or [])
    for today_label in sorted(today_labels):
        scored = []
        for arc in arcs:
            score = arc_candidate_score(today_label, arc, today=today, default_days=default_days)
            if score <= 0:
                continue
            scored.append((score, arc))
        scored.sort(key=lambda item: (-item[0], str(item[1].get("canonical_label", ""))))
        supplied = scored[:limit]
        candidate_arcs = [compact_arc_option(arc) for _, arc in supplied]
        if not candidate_arcs:
            continue
        current_articles = [
            compact_current_article(article)
            for article in story_groups.get(today_label, [])[:VERIFY_ARTICLES_PER_CASE]
        ]
        if not current_articles:
            continue
        candidate_audit[today_label] = [
            {
                "arc_id": arc.get("arc_id"),
                "arc_label": arc.get("canonical_label", ""),
                "score": score,
            }
            for score, arc in supplied
        ]
        cases.append({
            "today_label": today_label,
            "run_date": today or "",
            "current_articles": current_articles,
            "candidate_arcs": candidate_arcs,
        })
    return cases, candidate_audit


def arc_case_key(case):
    return case["today_label"]


def _valid_parent_story_ids(case, arc_id):
    ids = set()
    for arc in case.get("candidate_arcs", []):
        if arc.get("arc_id") != arc_id:
            continue
        for story in arc.get("recent_stories", []):
            if story.get("story_id") is not None:
                ids.add(story["story_id"])
            if story.get("parent_story_id") is not None:
                ids.add(story["parent_story_id"])
    return ids


def arc_assignment_from_model(raw, expected_case, model):
    today_label = arc_case_key(expected_case)
    if not isinstance(raw, dict):
        raw = {}

    today_returned = clean_string(raw.get("today_label"))
    relationship = clean_string(raw.get("relationship")).casefold() or "uncertain"
    if relationship not in ARC_RELATIONSHIPS:
        relationship = "uncertain"
    confidence = clean_string(raw.get("confidence")).casefold() or "low"
    if confidence not in VERIFY_CONFIDENCE_VALUES:
        confidence = "low"
    evidence = clean_list(raw.get("continuity_evidence"))
    reject_reason = clean_string(raw.get("reject_reason"))

    valid_arc_ids = {
        arc.get("arc_id")
        for arc in expected_case.get("candidate_arcs", [])
        if arc.get("arc_id") is not None
    }
    raw_arc_id = raw.get("arc_id")
    arc_id = None
    if isinstance(raw_arc_id, int):
        arc_id = raw_arc_id
    elif isinstance(raw_arc_id, str) and raw_arc_id.isdigit():
        arc_id = int(raw_arc_id)

    raw_parent_id = raw.get("parent_story_id")
    parent_story_id = None
    if isinstance(raw_parent_id, int):
        parent_story_id = raw_parent_id
    elif isinstance(raw_parent_id, str) and raw_parent_id.isdigit():
        parent_story_id = int(raw_parent_id)

    schema_matches_case = today_returned == today_label
    assigned = (
        schema_matches_case
        and arc_id in valid_arc_ids
        and relationship in ARC_ACCEPT_RELATIONSHIPS
        and confidence in {"high", "medium"}
        and bool(evidence)
    )
    if assigned and parent_story_id is not None:
        valid_parent_ids = _valid_parent_story_ids(expected_case, arc_id)
        if parent_story_id not in valid_parent_ids:
            assigned = False

    if not assigned and not reject_reason:
        if not schema_matches_case:
            reject_reason = "Arc assignment response did not match the supplied case."
        elif raw_arc_id == "NEW_ARC":
            reject_reason = "Arc assignment selected a new arc."
        elif arc_id not in valid_arc_ids:
            reject_reason = "Arc assignment did not select a supplied arc."
        elif relationship == "uncertain":
            reject_reason = "Arc assignment did not provide enough concrete arc evidence."
        else:
            reject_reason = "Arc assignment did not accept an existing arc."

    return {
        "today_label": today_label,
        "arc_id": arc_id if assigned else None,
        "parent_story_id": parent_story_id if assigned else None,
        # The model's parsed picks before the accept gate, kept for the audit
        # trail even when the decision is rejected.
        "proposed_arc_id": arc_id,
        "proposed_parent_story_id": parent_story_id,
        "accepted": assigned,
        "relationship": relationship,
        "confidence": confidence,
        "continuity_evidence": evidence,
        "reject_reason": reject_reason,
        "verifier_model": model,
        "prompt_version": ARC_ASSIGNMENT_PROMPT_VERSION,
    }


def missing_arc_assignment(expected_case, model):
    return arc_assignment_from_model({
        "today_label": expected_case["today_label"],
        "arc_id": "NEW_ARC",
        "parent_story_id": None,
        "relationship": "uncertain",
        "confidence": "low",
        "continuity_evidence": [],
        "reject_reason": "Arc assignment returned no decision for this case.",
    }, expected_case, model)


def assign_story_arcs(today_labels, recent_arcs, story_groups, get_client, model, today=None, default_days=14):
    cases, candidate_audit = arc_assignment_cases_for_prompt(
        today_labels,
        recent_arcs,
        story_groups,
        today=today,
        default_days=default_days,
    )
    if not cases:
        return {}

    assignments = {}
    for batch in chunked(cases, ARC_ASSIGNMENT_CASES_PER_CALL):
        expected_by_key = {arc_case_key(case): case for case in batch}
        messages = [
            {"role": "system", "content": ARC_ASSIGNMENT_PROMPT},
            {"role": "user", "content": json.dumps({"cases": batch}, ensure_ascii=False)},
        ]
        response, cache_metadata, cache_hit = create_cached_chat_completion(
            get_client,
            model=model,
            messages=messages,
            purpose="match-arc",
            prompt_version=ARC_ASSIGNMENT_PROMPT_VERSION,
            response_format={"type": "json_object"},
        )
        payload = parse_json_object(response)
        raw_assignments = payload.get("assignments")
        if not isinstance(raw_assignments, list):
            mark_schema_failure('Model response must contain an "assignments" list', response=response)
            raise ValueError('Model response must contain an "assignments" list')
        if not cache_hit:
            save_cached_chat_completion(cache_metadata, response)

        seen_keys = set()
        for raw in raw_assignments:
            if not isinstance(raw, dict):
                continue
            key = clean_string(raw.get("today_label"))
            expected_case = expected_by_key.get(key)
            if expected_case is None:
                continue
            assignment = arc_assignment_from_model(raw, expected_case, model)
            seen_keys.add(key)
            assignments[key] = assignment

        for key, expected_case in expected_by_key.items():
            if key not in seen_keys:
                assignments[key] = missing_arc_assignment(expected_case, model)

    for key, assignment in assignments.items():
        assignment["candidates"] = candidate_audit.get(key, [])

    return assignments
