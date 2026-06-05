import json
import re
from datetime import date
from email.utils import parsedate_to_datetime

from src.llm import (
    create_cached_chat_completion,
    mark_schema_failure,
    parse_json_object,
    save_cached_chat_completion,
)


CONSOLIDATE_PROMPT = """You are grouping today's news story labels that refer to the same ongoing story.

Given a list of story labels from today, identify groups that are clearly about the same event.
For each group, pick the best canonical label (clear, concise, in English).

Return a JSON object with key "groups": array of {canonical_label, labels} where labels is the list of today's labels that belong to this group.
Labels that stand alone still appear as a group of one."""

CONSOLIDATE_PROMPT_VERSION = "2026-05-11-v1"

MATCH_PROMPT = """You are matching today's news story labels to recent canonical story memory.

For each match case, return either:
- The matching canonical label from recent history (if it is the same ongoing story)
- "NEW" (if it's a genuinely new story)

Be conservative: slight wording differences for the same real-world story should match, but broad topic similarity is not enough.
Different stories, incidents, crashes, attacks, lawsuits, or accidents must not match merely because they share a category word.
Use the recent story summaries and recent article titles to check whether today's label continues the same event, not merely the same topic.
Only match a today_label to one of its supplied candidates. If no candidate is a strong match, return "NEW".

Return a JSON object with key "matches": array of {today_label, canonical_label}.
canonical_label is either the exact string from the recent-history list or "NEW"."""

MATCH_PROMPT_VERSION = "2026-05-11-v1"

VERIFY_PROMPT_VERSION = "2026-05-08-v1"
VERIFY_PROMPT = """You are verifying whether today's article group continues an existing tracked news story.

For each case, decide whether the current article group is the same real-world event or continuing story arc as the candidate story.

Accept only direct continuity:
- same_event: the same named incident, raid, attack, lawsuit, negotiation, vote, court case, investigation, disaster, policy decision, or operation
- same_story_arc: a direct continuation of the same named ongoing arc, with shared concrete actors and event identity
- direct_follow_up: a later legal, diplomatic, operational, or factual follow-up to the same concrete event

Reject broad or adjacent relationships:
- adjacent_topic: same broad topic, place, actor, allegation type, or conflict context, but not the same tracked event
- broader_context: useful background or big-picture context, but not a continuation of the candidate story
- unrelated: no meaningful relationship
- uncertain: not enough concrete continuity evidence

Big-picture context can be useful, but it must not be merged into the same story unless the article directly continues the candidate event.

Return a JSON object with key "decisions": array of:
{
  "today_label": string,
  "canonical_label": string,
  "same_event": boolean,
  "relationship": one of: same_event | same_story_arc | direct_follow_up | adjacent_topic | broader_context | unrelated | uncertain,
  "confidence": one of: high | medium | low,
  "article_dates": array of date strings from the current articles,
  "candidate_last_seen": date string,
  "continuity_evidence": array of short strings naming the shared concrete event evidence,
  "reject_reason": string
}

If evidence is weak or the relationship is adjacent, set same_event=false."""

ARC_ASSIGNMENT_PROMPT_VERSION = "2026-05-20-v1"
ARC_ASSIGNMENT_PROMPT = """You are assigning unmatched current news stories to broader existing story arcs.

This is not a same-event merge. The same-event verifier has already failed or found no direct continuation.
Your task is only to decide whether today's concrete story belongs under one supplied broader arc or parent story.

Accept an existing arc only when the current story shares concrete actors, geography, conflict, policy thread, legal matter, market, disaster, or continuing public-interest context with that arc.
Reject broad category overlap, generic topic similarity, and weak vibes.
Choose only from the supplied candidate arc_id values and optional parent_story_id values.
Use "NEW_ARC" when none of the supplied arcs is a good broader home.

Return a JSON object with key "assignments": array of:
{
  "today_label": string,
  "arc_id": integer or "NEW_ARC",
  "parent_story_id": integer or null,
  "relationship": one of: same_arc | parent_context | adjacent_topic | broader_context | unrelated | uncertain,
  "confidence": one of: high | medium | low,
  "continuity_evidence": array of short strings naming the concrete arc evidence,
  "reject_reason": string
}"""

LABEL_STOPWORDS = {
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "into",
    "of", "on", "or", "over", "the", "to", "with",
}
GENERIC_EVENT_TOKENS = {
    "accident", "arrest", "attack", "blast", "case", "charges", "charged",
    "collapse", "collision", "crash", "crowd", "danger", "dangerous",
    "death", "fire", "homicide", "incident", "injured", "injuries",
    "injury", "killing", "lawsuit", "manslaughter", "murder", "poisoning",
    "protest", "rescue", "riot", "safety", "shooting", "shooter",
    "stabbing", "strike", "trial", "unrest", "violence", "wounded",
}
CANDIDATES_PER_LABEL = 10
MATCH_CASES_PER_CALL = 50
SUMMARY_CHAR_LIMIT = 400
DELTA_CHAR_LIMIT = 240
TITLE_CHAR_LIMIT = 160
VERIFY_ARTICLE_TEXT_CHAR_LIMIT = 16000
VERIFY_DESCRIPTION_CHAR_LIMIT = 1200
VERIFY_ARTICLES_PER_CASE = 4
VERIFY_CASES_PER_CALL = 8
VERIFY_ACCEPT_RELATIONSHIPS = {"same_event", "same_story_arc", "direct_follow_up"}
VERIFY_RELATIONSHIPS = VERIFY_ACCEPT_RELATIONSHIPS | {
    "adjacent_topic", "broader_context", "unrelated", "uncertain",
}
VERIFY_CONFIDENCE_VALUES = {"high", "medium", "low"}
ARC_ACCEPT_RELATIONSHIPS = {"same_arc", "parent_context"}
ARC_RELATIONSHIPS = ARC_ACCEPT_RELATIONSHIPS | {
    "adjacent_topic", "broader_context", "unrelated", "uncertain",
}
ARC_CANDIDATES_PER_LABEL = 8
ARC_ASSIGNMENT_CASES_PER_CALL = 12
PARENT_ATTACH_RELATIONSHIPS = {
    "same_event", "same_story_arc", "direct_follow_up", "adjacent_topic", "broader_context",
}
PARENT_ARC_TOKENS = {
    "asylum", "attacks", "ceasefire", "conflict", "crisis", "debate",
    "diplomacy", "economy", "election", "fallout", "insurgency", "market",
    "markets", "migration", "offensive", "policy", "pressure", "sanctions",
    "strike", "strikes", "talks", "trade", "tensions", "violence", "war",
}
PARENT_ARC_PAIR_TOKENS = {
    ("drug", "strikes"),
    ("drug", "strike"),
    ("gang", "violence"),
}


def label_tokens(label):
    tokens = re.findall(r"[a-z0-9]+", str(label or "").casefold())
    return {token for token in tokens if len(token) > 1}


def truncate_text(value, limit):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip() + "..."


def clean_string(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def clean_list(value):
    if not isinstance(value, list):
        return []
    cleaned = []
    for item in value:
        text = clean_string(item)
        if text:
            cleaned.append(text)
    return cleaned


def article_date(value):
    text = clean_string(value)
    if not text:
        return ""
    try:
        return parsedate_to_datetime(text).date().isoformat()
    except Exception:
        pass
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except Exception:
        return text


def days_since(value, today, default_days):
    try:
        return (date.fromisoformat(str(today)) - date.fromisoformat(str(value))).days
    except Exception:
        return default_days + 1


def distinctive_label_tokens(label):
    return label_tokens(label) - LABEL_STOPWORDS - GENERIC_EVENT_TOKENS


def is_generic_event_label(label):
    return bool(label_tokens(label) & GENERIC_EVENT_TOKENS)


def labels_can_refer_to_same_story(left, right):
    """Reject obvious false merges for generic incident/category labels.

    LLM label matching is useful for paraphrases, but broad labels such as
    "accident" or "shooting" are unsafe without a shared distinctive token.
    A false negative creates a duplicate story; a false positive corrupts
    story memory across days.
    """
    if str(left or "").strip().casefold() == str(right or "").strip().casefold():
        return True
    if not (is_generic_event_label(left) and is_generic_event_label(right)):
        return True
    return bool(distinctive_label_tokens(left) & distinctive_label_tokens(right))


def compatible_label_clusters(labels):
    clusters = []
    for label in labels:
        placed = False
        for cluster in clusters:
            if all(labels_can_refer_to_same_story(label, existing) for existing in cluster):
                cluster.append(label)
                placed = True
                break
        if not placed:
            clusters.append([label])
    return clusters


def canonical_for_cluster(canonical, cluster, split_group):
    if not split_group:
        return canonical
    if canonical in cluster:
        return canonical
    if all(labels_can_refer_to_same_story(canonical, label) for label in cluster):
        return canonical
    return cluster[0]


def consolidate_today(story_groups, get_client, model):
    """Merge story labels that refer to the same event within today's batch."""
    labels = list(story_groups.keys())
    if len(labels) <= 1:
        return story_groups

    messages = [
        {"role": "system", "content": CONSOLIDATE_PROMPT},
        {"role": "user", "content": json.dumps(labels, ensure_ascii=False)},
    ]
    response, cache_metadata, cache_hit = create_cached_chat_completion(
        get_client,
        model=model,
        messages=messages,
        purpose="match-sameday",
        prompt_version=CONSOLIDATE_PROMPT_VERSION,
        response_format={"type": "json_object"},
    )
    payload = parse_json_object(response)
    groups = payload.get("groups")
    if not isinstance(groups, list):
        mark_schema_failure('Model response must contain a "groups" list', response=response)
        raise ValueError('Model response must contain a "groups" list')
    if not cache_hit:
        save_cached_chat_completion(cache_metadata, response)

    from collections import defaultdict
    consolidated = defaultdict(list)
    grouped_labels = set()
    for group in groups:
        if not isinstance(group, dict):
            continue
        canonical = str(group.get("canonical_label") or "").strip()
        group_labels = group.get("labels", [])
        if not canonical or not isinstance(group_labels, list):
            continue
        valid_labels = [
            label for label in group_labels
            if isinstance(label, str) and label in story_groups
        ]
        clusters = compatible_label_clusters(valid_labels)
        split_group = len(clusters) > 1
        for cluster in clusters:
            cluster_canonical = canonical_for_cluster(canonical, cluster, split_group)
            for label in cluster:
                grouped_labels.add(label)
                consolidated[cluster_canonical].extend(story_groups[label])

    for label, articles in story_groups.items():
        if label not in grouped_labels:
            consolidated[label].extend(articles)

    print(f"  Consolidated {len(story_groups)} labels -> {len(consolidated)} stories", flush=True)
    return consolidated


def recent_story_value_label(label, value):
    if isinstance(value, dict):
        return value.get("canonical_label") or label
    return label


def recent_story_text(label, value):
    if not isinstance(value, dict):
        return label
    parts = [
        label,
        value.get("canonical_label", ""),
        value.get("summary", ""),
        value.get("delta_summary", ""),
    ]
    for article in value.get("recent_articles", []):
        parts.append(article.get("title", ""))
    for development in value.get("recent_developments", []):
        parts.append(development.get("label", ""))
    return " ".join(str(part or "") for part in parts)


def has_parent_arc_shape(label):
    tokens = distinctive_label_tokens(label)
    if tokens & PARENT_ARC_TOKENS:
        return True
    return any(all(token in tokens for token in pair) for pair in PARENT_ARC_PAIR_TOKENS)


def should_attach_to_parent_arc(decision, candidate):
    """Return true when a rejected verifier match is still useful parent continuity.

    This is deliberately narrower than a story match. It lets a new development
    live inside a broad arc without claiming it is the same concrete event.
    """
    if decision.get("accepted"):
        return False
    relationship = clean_string(decision.get("relationship")).casefold()
    confidence = clean_string(decision.get("confidence")).casefold()
    if relationship not in PARENT_ATTACH_RELATIONSHIPS:
        return False
    if confidence not in {"high", "medium"}:
        return False
    if not clean_list(decision.get("continuity_evidence")):
        return False

    candidate_label = decision.get("candidate_label", "")
    today_label = decision.get("today_label", "")
    if not (has_parent_arc_shape(candidate_label) or has_parent_arc_shape(today_label)):
        return False

    if relationship == "broader_context":
        candidate_active_days = 0
        if isinstance(candidate, dict):
            candidate_active_days = int(candidate.get("active_days") or 0)
        if candidate_active_days < 2 and not has_parent_arc_shape(candidate_label):
            return False

    return True


def candidate_score(today_label, candidate_label, candidate, today=None, default_days=14):
    today_tokens = distinctive_label_tokens(today_label)
    candidate_tokens = distinctive_label_tokens(candidate_label)
    candidate_text_tokens = distinctive_label_tokens(recent_story_text(candidate_label, candidate))
    shared_label_tokens = today_tokens & candidate_tokens
    shared_context_tokens = today_tokens & candidate_text_tokens
    score = 0

    if str(today_label or "").strip().casefold() == str(candidate_label or "").strip().casefold():
        score += 100
    score += len(shared_label_tokens) * 12
    score += max(0, len(shared_context_tokens) - len(shared_label_tokens)) * 4

    today_all_tokens = label_tokens(today_label)
    candidate_all_tokens = label_tokens(recent_story_text(candidate_label, candidate))
    score += len((today_all_tokens & candidate_all_tokens) - LABEL_STOPWORDS) * 2

    if not labels_can_refer_to_same_story(today_label, candidate_label):
        score -= 50

    if score <= 0:
        return score

    if isinstance(candidate, dict) and today is not None:
        age_days = days_since(candidate.get("last_seen"), today, default_days)
        score += max(0, 8 - age_days)

    return score


def compact_story_option(label, value):
    if not isinstance(value, dict):
        return {"canonical_label": label}

    option = {
        "canonical_label": value.get("canonical_label") or label,
        "last_seen": value.get("last_seen", ""),
    }
    if value.get("delta_summary"):
        option["last_delta"] = truncate_text(value["delta_summary"], DELTA_CHAR_LIMIT)
    if value.get("summary"):
        option["summary"] = truncate_text(value["summary"], SUMMARY_CHAR_LIMIT)
    if value.get("active_days"):
        option["active_days"] = value["active_days"]
    recent_developments = []
    for development in value.get("recent_developments", [])[:3]:
        label = truncate_text(development.get("label", ""), TITLE_CHAR_LIMIT)
        if label:
            recent_developments.append({
                "date": development.get("date", ""),
                "label": label,
                "status": development.get("status", ""),
            })
    if recent_developments:
        option["recent_developments"] = recent_developments
    recent_titles = []
    for article in value.get("recent_articles", [])[:2]:
        title = truncate_text(article.get("title", ""), TITLE_CHAR_LIMIT)
        if title:
            recent_titles.append(title)
    if recent_titles:
        option["recent_titles"] = recent_titles
    return option


def compact_current_article(article):
    item = {
        "id": str(article.get("id") or ""),
        "source": article.get("source", ""),
        "title": truncate_text(article.get("title", ""), TITLE_CHAR_LIMIT),
        "description": truncate_text(article.get("description", ""), VERIFY_DESCRIPTION_CHAR_LIMIT),
        "article_date": article_date(article.get("published_at", "")),
        "reported_at": article.get("published_at", ""),
        "url": article.get("url", ""),
    }
    text = truncate_text(article.get("text", ""), VERIFY_ARTICLE_TEXT_CHAR_LIMIT)
    if text:
        item["article_text"] = text
    return item


def compact_verifier_candidate(label, value):
    option = compact_story_option(label, value)
    if isinstance(value, dict):
        option["story_id"] = value.get("story_id")
        recent_articles = []
        for article in value.get("recent_articles", [])[:3]:
            title = truncate_text(article.get("title", ""), TITLE_CHAR_LIMIT)
            if title:
                recent_articles.append({
                    "date": article.get("date", ""),
                    "source": article.get("source", ""),
                    "title": title,
                })
        if recent_articles:
            option["recent_articles"] = recent_articles
    return option


def verifier_cases_for_prompt(label_map, recent_stories, story_groups, today=None):
    cases = []
    for today_label in sorted(label_map):
        canonical_label = label_map[today_label]
        if canonical_label == "NEW" or canonical_label not in recent_stories:
            continue
        current_articles = [
            compact_current_article(article)
            for article in story_groups.get(today_label, [])[:VERIFY_ARTICLES_PER_CASE]
        ]
        if not current_articles:
            continue
        candidate = recent_stories[canonical_label]
        cases.append({
            "today_label": today_label,
            "run_date": today or "",
            "current_articles": current_articles,
            "candidate_story": compact_verifier_candidate(canonical_label, candidate),
        })
    return cases


def chunked(items, size):
    for index in range(0, len(items), size):
        yield items[index:index + size]


def case_key(case):
    return (
        case["today_label"],
        case["candidate_story"]["canonical_label"],
    )


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
    arcs = list(recent_arcs.values()) if isinstance(recent_arcs, dict) else list(recent_arcs or [])
    for today_label in sorted(today_labels):
        scored = []
        for arc in arcs:
            score = arc_candidate_score(today_label, arc, today=today, default_days=default_days)
            if score <= 0:
                continue
            scored.append((score, arc))
        scored.sort(key=lambda item: (-item[0], str(item[1].get("canonical_label", ""))))
        candidate_arcs = [compact_arc_option(arc) for _, arc in scored[:limit]]
        if not candidate_arcs:
            continue
        current_articles = [
            compact_current_article(article)
            for article in story_groups.get(today_label, [])[:VERIFY_ARTICLES_PER_CASE]
        ]
        if not current_articles:
            continue
        cases.append({
            "today_label": today_label,
            "run_date": today or "",
            "current_articles": current_articles,
            "candidate_arcs": candidate_arcs,
        })
    return cases


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
    cases = arc_assignment_cases_for_prompt(
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

    return assignments


def candidate_cases_for_prompt(today_labels, recent_stories, today=None, limit=CANDIDATES_PER_LABEL, default_days=14):
    cases = []
    for today_label in sorted(today_labels):
        scored = []
        for candidate_label, value in recent_stories.items():
            canonical_label = recent_story_value_label(candidate_label, value)
            score = candidate_score(
                today_label,
                canonical_label,
                value,
                today=today,
                default_days=default_days,
            )
            if score <= 0:
                continue
            scored.append((score, canonical_label, value))
        scored.sort(key=lambda item: (-item[0], item[1]))
        cases.append({
            "today_label": today_label,
            "candidates": [
                compact_story_option(candidate_label, value)
                for _, candidate_label, value in scored[:limit]
            ],
        })
    return cases


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
