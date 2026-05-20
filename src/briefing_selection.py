from collections import defaultdict
import re

from src.source_agreement import source_identity, source_support


THEME_ORDER = ["Geopolitics & War", "USA Politics", "Dutch Politics", "Economy", "Tech", "Climate", "Science", "Sports", "Other"]
POLITICS_THEMES = {"Geopolitics & War", "USA Politics", "Dutch Politics"}
SECTION_EXCLUDED_THEMES = set()
LEAD_EXCLUDED_THEMES = set()
LOW_INTEREST_LEAD_THEMES = set()
THEME_SELECTION_PENALTIES = {
    "Tech": 60,
    "Science": 60,
    "Sports": 260,
}
LOW_INTEREST_KEYWORD_PENALTY = 120
LOW_INTEREST_KEYWORDS = {
    "celebrity",
    "entertainment",
    "film",
    "ice spice",
    "mcdonald",
    "music",
    "showbiz",
}
TREND_SCORE = {"up": 2, "new": 1, "steady": 0, "down": -1}


def score(story):
    # Importance leads, but broad pickup should beat one-source opinion pieces.
    return story["importance_avg"] * 100 + story["source_count"] * 12 + TREND_SCORE.get(story["trend"], 0)


def selection_penalty(story):
    penalty = sum(THEME_SELECTION_PENALTIES.get(theme, 0) for theme in story["themes"])
    if has_low_interest_keywords(story):
        penalty += LOW_INTEREST_KEYWORD_PENALTY
    return penalty


def penalty_reasons(story):
    reasons = [
        f"{theme.lower()} theme"
        for theme in THEME_ORDER
        if theme in story["themes"] and THEME_SELECTION_PENALTIES.get(theme, 0)
    ]
    if has_low_interest_keywords(story):
        reasons.append("low-interest keyword")
    return reasons


def selection_score(story):
    return score(story) - selection_penalty(story)


def aggregate(tracked):
    """Group tracked articles by canonical story and compute story metadata."""
    stories = defaultdict(lambda: {
        "articles": [],
        "sources": set(),
        "importance_sum": 0,
        "theme_counts": defaultdict(int),
        "previous_context": None,
        "arc_id": None,
        "arc_label": "",
        "parent_story_id": None,
        "parent_label": "",
        "observation_ids": set(),
        "development_ids": set(),
        "developments": {},
    })

    for article in tracked:
        label = article.get("canonical_label", article["story_label"])
        theme = article["theme"]
        stories[label]["articles"].append(article)
        stories[label]["sources"].add(source_identity(article))
        stories[label]["importance_sum"] += article["importance"]
        stories[label]["theme_counts"][theme] += 1
        if article.get("previous_context") and not stories[label]["previous_context"]:
            stories[label]["previous_context"] = article["previous_context"]
        if article.get("arc_id") and not stories[label]["arc_id"]:
            stories[label]["arc_id"] = article["arc_id"]
        if article.get("arc_label") and not stories[label]["arc_label"]:
            stories[label]["arc_label"] = article["arc_label"]
        if article.get("parent_story_id") and not stories[label]["parent_story_id"]:
            stories[label]["parent_story_id"] = article["parent_story_id"]
        if article.get("parent_label") and not stories[label]["parent_label"]:
            stories[label]["parent_label"] = article["parent_label"]
        if article.get("observation_id"):
            stories[label]["observation_ids"].add(article["observation_id"])
        if article.get("development_id"):
            stories[label]["development_ids"].add(article["development_id"])
        development_label = article.get("development_label") or article.get("story_label") or label
        development = stories[label]["developments"].setdefault(development_label, {
            "label": development_label,
            "status": article.get("development_status", "continuing"),
            "parent_relationship": article.get("parent_relationship", ""),
            "parent_confidence": article.get("parent_confidence", ""),
            "articles": [],
        })
        development["articles"].append(article)
        if article.get("development_status") == "new_child":
            development["status"] = "new_child"

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
            "source_support": source_support(articles),
            "importance_avg": data["importance_sum"] / len(articles),
            "previous_context": data["previous_context"] or {},
            "arc_id": data["arc_id"],
            "arc_label": data["arc_label"],
            "parent_story_id": data["parent_story_id"],
            "parent_label": data["parent_label"],
            "observation_ids": sorted(data["observation_ids"]),
            "development_ids": sorted(data["development_ids"]),
            "developments": [
                {
                    "label": value["label"],
                    "status": value["status"],
                    "parent_relationship": value["parent_relationship"],
                    "parent_confidence": value["parent_confidence"],
                    "article_count": len(value["articles"]),
                    "source_count": len({source_identity(article) for article in value["articles"]}),
                }
                for value in data["developments"].values()
            ],
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
    return any(
        re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text)
        for keyword in LOW_INTEREST_KEYWORDS
    )


def is_lead_candidate(story):
    if "Sports" in story["themes"]:
        return is_exceptional_sports_story(story)
    return selection_score(story) > 0


def is_exceptional_sports_story(story):
    return selection_score(story) >= 450 or (
        story["importance_avg"] >= 4.5 and story["source_count"] >= 8
    )


def is_other_important(story):
    if story["themes"] & POLITICS_THEMES or "Economy" in story["themes"]:
        return False
    if has_low_interest_keywords(story) and selection_score(story) < 450:
        return False
    if "Sports" in story["themes"]:
        return is_exceptional_sports_story(story)
    if story["themes"] & {"Tech", "Science"}:
        return story["source_count"] >= 2 and selection_score(story) >= 300
    return story["importance_avg"] >= 2.5 or story["source_count"] >= 2


def section_candidates(stories, predicate, used_labels, limit):
    candidates = [
        story for story in stories
        if story["canonical_label"] not in used_labels
        and predicate(story)
    ]
    return sorted(candidates, key=selection_score, reverse=True)[:limit]


def select_story_sections(tracked, n=3, global_n=10):
    stories = sorted(aggregate(tracked), key=selection_score, reverse=True)

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
