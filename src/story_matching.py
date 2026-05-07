import json
import re
from datetime import date

from src.llm import create_chat_completion, mark_schema_failure, parse_json_object


CONSOLIDATE_PROMPT = """You are grouping today's news story labels that refer to the same ongoing story.

Given a list of story labels from today, identify groups that are clearly about the same event.
For each group, pick the best canonical label (clear, concise, in English).

Return a JSON object with key "groups": array of {canonical_label, labels} where labels is the list of today's labels that belong to this group.
Labels that stand alone still appear as a group of one."""

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
SUMMARY_CHAR_LIMIT = 400
DELTA_CHAR_LIMIT = 240
TITLE_CHAR_LIMIT = 160


def label_tokens(label):
    tokens = re.findall(r"[a-z0-9]+", str(label or "").casefold())
    return {token for token in tokens if len(token) > 1}


def truncate_text(value, limit):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip() + "..."


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

    client = get_client()
    response = create_chat_completion(
        client,
        model=model,
        messages=[
            {"role": "system", "content": CONSOLIDATE_PROMPT},
            {"role": "user", "content": json.dumps(labels, ensure_ascii=False)},
        ],
        purpose="match-sameday",
        response_format={"type": "json_object"},
    )
    payload = parse_json_object(response)
    groups = payload.get("groups")
    if not isinstance(groups, list):
        mark_schema_failure('Model response must contain a "groups" list', response=response)
        raise ValueError('Model response must contain a "groups" list')

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
    return " ".join(str(part or "") for part in parts)


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
    recent_titles = []
    for article in value.get("recent_articles", [])[:2]:
        title = truncate_text(article.get("title", ""), TITLE_CHAR_LIMIT)
        if title:
            recent_titles.append(title)
    if recent_titles:
        option["recent_titles"] = recent_titles
    return option


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

    client = get_client()
    response = create_chat_completion(
        client,
        model=model,
        messages=[
            {"role": "system", "content": MATCH_PROMPT},
            {"role": "user", "content": json.dumps({
                "match_cases": match_cases,
            }, ensure_ascii=False)},
        ],
        purpose="match-crossday",
        response_format={"type": "json_object"},
    )
    payload = parse_json_object(response)
    matches = payload.get("matches")
    if not isinstance(matches, list):
        mark_schema_failure('Model response must contain a "matches" list', response=response)
        raise ValueError('Model response must contain a "matches" list')
    matched = {}
    for match in matches:
        if not isinstance(match, dict) or match.get("today_label") not in today_labels:
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
