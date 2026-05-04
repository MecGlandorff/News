from collections import defaultdict


THEME_ORDER = ["Geopolitics & War", "USA Politics", "Dutch Politics", "Economy", "Tech", "Climate", "Science", "Sports", "Other"]
POLITICS_THEMES = {"Geopolitics & War", "USA Politics", "Dutch Politics"}
SECTION_EXCLUDED_THEMES = {"Sports", "Tech", "Science"}
LEAD_EXCLUDED_THEMES = {"Sports"}
LOW_INTEREST_LEAD_THEMES = {"Tech", "Science"}
LOW_INTEREST_KEYWORDS = {
    "celebrity",
    "entertainment",
    "film",
    "ice spice",
    "mcdonald",
    "music",
    "showbiz",
    "tv",
    "video",
}
TREND_SCORE = {"up": 2, "new": 1, "steady": 0, "down": -1}


def score(story):
    # Importance leads, but broad pickup should beat one-source opinion pieces.
    return story["importance_avg"] * 100 + story["source_count"] * 12 + TREND_SCORE.get(story["trend"], 0)


def aggregate(tracked):
    """Group tracked articles by canonical story and compute story metadata."""
    stories = defaultdict(lambda: {
        "articles": [],
        "sources": set(),
        "importance_sum": 0,
        "theme_counts": defaultdict(int),
        "previous_context": None,
        "observation_ids": set(),
    })

    for article in tracked:
        label = article.get("canonical_label", article["story_label"])
        theme = article["theme"]
        stories[label]["articles"].append(article)
        stories[label]["sources"].add(article["source"])
        stories[label]["importance_sum"] += article["importance"]
        stories[label]["theme_counts"][theme] += 1
        if article.get("previous_context") and not stories[label]["previous_context"]:
            stories[label]["previous_context"] = article["previous_context"]
        if article.get("observation_id"):
            stories[label]["observation_ids"].add(article["observation_id"])

    result = []
    for label, data in stories.items():
        articles = data["articles"]
        themes = set(data["theme_counts"])
        primary_theme = max(
            themes,
            key=lambda theme: (
                data["theme_counts"][theme],
                sum(article["importance"] for article in articles if article["theme"] == theme),
            ),
        )
        result.append({
            "canonical_label": label,
            "theme": primary_theme,
            "themes": themes,
            "trend": articles[0].get("trend", "steady"),
            "source_count": len(data["sources"]),
            "importance_avg": data["importance_sum"] / len(articles),
            "previous_context": data["previous_context"] or {},
            "observation_ids": sorted(data["observation_ids"]),
            "story_id": articles[0].get("story_id"),
            "articles": articles,
        })
    return result


def theme_summary(story):
    themes = [theme for theme in THEME_ORDER if theme in story["themes"]]
    return " / ".join(themes)


def has_low_interest_keywords(story):
    text = " ".join(
        [story["canonical_label"]]
        + [article.get("title", "") for article in story["articles"]]
        + [article.get("description", "") for article in story["articles"]]
    ).lower()
    return any(keyword in text for keyword in LOW_INTEREST_KEYWORDS)


def is_lead_candidate(story):
    if story["themes"] & LEAD_EXCLUDED_THEMES:
        return False
    if has_low_interest_keywords(story):
        return False
    if story["themes"] & LOW_INTEREST_LEAD_THEMES:
        return story["importance_avg"] >= 4.5 and story["source_count"] >= 3
    return True


def is_other_important(story):
    if "Other" not in story["themes"] or has_low_interest_keywords(story):
        return False
    return story["importance_avg"] >= 2.5 or story["source_count"] >= 2


def section_candidates(stories, predicate, used_labels, limit):
    candidates = [
        story for story in stories
        if story["canonical_label"] not in used_labels
        and not (story["themes"] & SECTION_EXCLUDED_THEMES)
        and predicate(story)
    ]
    return sorted(candidates, key=score, reverse=True)[:limit]


def select_story_sections(tracked, n=3, global_n=10):
    stories = sorted(aggregate(tracked), key=score, reverse=True)

    lead_count = min(max(n, 3), 8)
    lead_stories = [story for story in stories if is_lead_candidate(story)][:lead_count]
    used_labels = {story["canonical_label"] for story in lead_stories}

    politics = section_candidates(
        stories,
        lambda story: bool(story["themes"] & POLITICS_THEMES),
        used_labels,
        global_n,
    )
    used_labels.update(story["canonical_label"] for story in politics)

    economy = section_candidates(
        stories,
        lambda story: "Economy" in story["themes"],
        used_labels,
        max(3, min(global_n, 6)),
    )
    used_labels.update(story["canonical_label"] for story in economy)

    other = section_candidates(
        stories,
        is_other_important,
        used_labels,
        max(3, min(global_n, 6)),
    )

    sections = [
        ("Top Developments", lead_stories),
        ("Politics", politics),
        ("Economy", economy),
        ("Other Important Stories", other),
    ]

    seen = set()
    display_stories = []
    for story in [story for _, section_stories in sections for story in section_stories]:
        if story["canonical_label"] not in seen:
            seen.add(story["canonical_label"])
            display_stories.append(story)

    return {
        "stories": stories,
        "sections": sections,
        "display_stories": display_stories,
    }
