import json

from src.llm import (
    create_cached_chat_completion,
    mark_schema_failure,
    parse_json_object,
    save_cached_chat_completion,
)
from src.tracker.matching.candidates import (
    candidate_cases_for_prompt,
    case_key,
    chunked,
    verifier_cases_for_prompt,
)
from src.tracker.matching.constants import (
    MATCH_CASES_PER_CALL,
    MATCH_PROMPT,
    MATCH_PROMPT_VERSION,
    VERIFY_ACCEPT_RELATIONSHIPS,
    VERIFY_CASES_PER_CALL,
    VERIFY_CONFIDENCE_VALUES,
    VERIFY_PROMPT,
    VERIFY_PROMPT_VERSION,
    VERIFY_RELATIONSHIPS,
)
from src.tracker.matching.labels import clean_list, clean_string, labels_can_refer_to_same_story


def decision_from_model(raw, expected_case, model):
    today_label, canonical_label = case_key(expected_case)
    article_dates = [
        article.get("article_date", "") or article.get("reported_at", "")
        for article in expected_case.get("current_articles", [])
        if article.get("article_date") or article.get("reported_at")
    ]
    candidate_last_seen = expected_case["candidate_story"].get("last_seen", "")
    if not isinstance(raw, dict):
        raw = {}

    relationship = clean_string(raw.get("relationship")) or "uncertain"
    if relationship not in VERIFY_RELATIONSHIPS:
        relationship = "uncertain"
    confidence = clean_string(raw.get("confidence")).casefold() or "low"
    if confidence not in VERIFY_CONFIDENCE_VALUES:
        confidence = "low"
    evidence = clean_list(raw.get("continuity_evidence"))
    same_event = raw.get("same_event") is True
    canonical_returned = clean_string(raw.get("canonical_label"))
    today_returned = clean_string(raw.get("today_label"))
    schema_matches_case = (
        today_returned == today_label
        and canonical_returned == canonical_label
    )
    accepted = (
        schema_matches_case
        and same_event
        and relationship in VERIFY_ACCEPT_RELATIONSHIPS
        and confidence in {"high", "medium"}
        and bool(evidence)
    )
    reject_reason = clean_string(raw.get("reject_reason"))
    if not accepted and not reject_reason:
        if not schema_matches_case:
            reject_reason = "Verifier response did not match the supplied case."
        elif relationship == "uncertain":
            reject_reason = "Verifier did not provide enough concrete continuity evidence."
        else:
            reject_reason = "Verifier did not accept this as the same tracked event."

    return {
        "today_label": today_label,
        "candidate_label": canonical_label,
        "candidate_story_id": (
            expected_case.get("candidate_story", {}).get("story_id")
            if isinstance(expected_case.get("candidate_story"), dict)
            else None
        ),
        "accepted": accepted,
        "same_event": same_event,
        "relationship": relationship,
        "confidence": confidence,
        "article_dates": article_dates,
        "candidate_last_seen": candidate_last_seen,
        "continuity_evidence": evidence,
        "reject_reason": reject_reason,
        "verifier_model": model,
        "prompt_version": VERIFY_PROMPT_VERSION,
    }


def missing_decision(expected_case, model):
    return decision_from_model({
        "today_label": expected_case["today_label"],
        "canonical_label": expected_case["candidate_story"]["canonical_label"],
        "same_event": False,
        "relationship": "uncertain",
        "confidence": "low",
        "continuity_evidence": [],
        "reject_reason": "Verifier returned no decision for this candidate match.",
    }, expected_case, model)


def rejected_candidate_story_ids(decisions: list[dict]) -> dict[str, set[int]]:
    """Map each today label to the story ids the verifier rejected for it."""
    rejected: dict[str, set[int]] = {}
    for decision in decisions:
        if decision.get("accepted") or not decision.get("candidate_story_id"):
            continue
        rejected.setdefault(decision["today_label"], set()).add(
            decision["candidate_story_id"]
        )
    return rejected


def verify_story_matches(label_map, recent_stories, story_groups, get_client, model, today=None):
    """Verify candidate cross-day matches with richer article context.

    The base label matcher proposes at most one candidate per today label.
    This verifier decides whether that candidate is the same tracked event.
    Weak, missing, adjacent, or uncertain decisions are not accepted.
    """
    cases = verifier_cases_for_prompt(label_map, recent_stories, story_groups, today=today)
    if not cases:
        return dict(label_map), []

    verified = dict(label_map)
    decisions = []
    for batch in chunked(cases, VERIFY_CASES_PER_CALL):
        expected_by_key = {case_key(case): case for case in batch}
        messages = [
            {"role": "system", "content": VERIFY_PROMPT},
            {"role": "user", "content": json.dumps({"cases": batch}, ensure_ascii=False)},
        ]
        response, cache_metadata, cache_hit = create_cached_chat_completion(
            get_client,
            model=model,
            messages=messages,
            purpose="match-verify",
            prompt_version=VERIFY_PROMPT_VERSION,
            response_format={"type": "json_object"},
        )
        payload = parse_json_object(response)
        raw_decisions = payload.get("decisions")
        if not isinstance(raw_decisions, list):
            mark_schema_failure('Model response must contain a "decisions" list', response=response)
            raise ValueError('Model response must contain a "decisions" list')
        if not cache_hit:
            save_cached_chat_completion(cache_metadata, response)

        seen_keys = set()
        for raw in raw_decisions:
            if not isinstance(raw, dict):
                continue
            key = (
                clean_string(raw.get("today_label")),
                clean_string(raw.get("canonical_label")),
            )
            expected_case = expected_by_key.get(key)
            if expected_case is None:
                continue
            decision = decision_from_model(raw, expected_case, model)
            seen_keys.add(key)
            decisions.append(decision)
            if not decision["accepted"]:
                verified[decision["today_label"]] = "NEW"

        for key, expected_case in expected_by_key.items():
            if key in seen_keys:
                continue
            decision = missing_decision(expected_case, model)
            decisions.append(decision)
            verified[decision["today_label"]] = "NEW"

    return verified, decisions


def match_labels(today_labels, recent_stories, get_client, model, today=None, default_days=14):
    if not recent_stories:
        return {label: "NEW" for label in today_labels}

    match_cases = candidate_cases_for_prompt(
        today_labels,
        recent_stories,
        today=today,
        default_days=default_days,
    )
    valid_candidates_by_label = {
        case["today_label"]: {candidate["canonical_label"] for candidate in case["candidates"]}
        for case in match_cases
    }
    if not any(valid_candidates_by_label.values()):
        return {label: "NEW" for label in today_labels}

    matched = {}
    cases_with_candidates = [case for case in match_cases if case["candidates"]]
    for batch in chunked(cases_with_candidates, MATCH_CASES_PER_CALL):
        batch_labels = {case["today_label"] for case in batch}
        messages = [
            {"role": "system", "content": MATCH_PROMPT},
            {"role": "user", "content": json.dumps({
                "match_cases": batch,
            }, ensure_ascii=False)},
        ]
        response, cache_metadata, cache_hit = create_cached_chat_completion(
            get_client,
            model=model,
            messages=messages,
            purpose="match-crossday",
            prompt_version=MATCH_PROMPT_VERSION,
            response_format={"type": "json_object"},
        )
        payload = parse_json_object(response)
        matches = payload.get("matches")
        if not isinstance(matches, list):
            mark_schema_failure('Model response must contain a "matches" list', response=response)
            raise ValueError('Model response must contain a "matches" list')
        if not cache_hit:
            save_cached_chat_completion(cache_metadata, response)
        for match in matches:
            if not isinstance(match, dict) or match.get("today_label") not in batch_labels:
                continue
            today_label = match["today_label"]
            canonical = match.get("canonical_label")
            valid_candidates = valid_candidates_by_label.get(today_label, set())
            if canonical in valid_candidates and labels_can_refer_to_same_story(today_label, canonical):
                matched[today_label] = canonical
            else:
                matched[today_label] = "NEW"
    for label in today_labels:
        matched.setdefault(label, "NEW")
    return matched
