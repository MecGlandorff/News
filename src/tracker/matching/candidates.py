from src.tracker.matching.constants import (
    CANDIDATES_PER_LABEL,
    DELTA_CHAR_LIMIT,
    LABEL_STOPWORDS,
    SUMMARY_CHAR_LIMIT,
    TITLE_CHAR_LIMIT,
    VERIFY_ARTICLES_PER_CASE,
    VERIFY_ARTICLE_TEXT_CHAR_LIMIT,
    VERIFY_DESCRIPTION_CHAR_LIMIT,
)
from src.tracker.matching.labels import (
    article_date,
    days_since,
    distinctive_label_tokens,
    label_tokens,
    labels_can_refer_to_same_story,
    truncate_text,
)


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
