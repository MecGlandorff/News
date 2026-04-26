import json
from collections import defaultdict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from src.config import BRIEFING_MODEL
from src.llm import get_openai_client, parse_json_object

BRIEFINGS_DIR = Path("briefings")
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
TREND_ICON  = {"new": "NEW STORY", "up": "COVERAGE INCREASING", "steady": "COVERAGE STEADY", "down": "COVERAGE DECREASING"}

BRIEFING_PROMPT = """You are writing a daily news briefing for an informed reader who wants real depth.

For each story, write 2-3 solid paragraphs in English (150-250 words) that:
- Open with what happened and the immediate significance
- Explain the broader context — why this story matters, what led to it, who is affected
- Close with what to watch next — unresolved tensions, upcoming decisions, or likely consequences
- Synthesize across all sources provided, surfacing different angles where they exist
- Are factual, neutral, and written for an intelligent adult — no fluff, no filler
- Use the supplied reported_at timestamps to keep chronology clear where timing matters
- Do not invent source URLs; URLs are supplied separately in the output

Return a JSON object with key "briefings": array of {canonical_label, briefing}.
Base your writing only on the titles and descriptions provided."""


def _score(story):
    # Importance leads, but broad pickup should beat one-source opinion pieces.
    return story["importance_avg"] * 100 + story["source_count"] * 12 + TREND_SCORE.get(story["trend"], 0)


def _parse_reported_at(value):
    try:
        parsed = parsedate_to_datetime(value)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_reported_at(value):
    parsed = _parse_reported_at(value)
    if parsed:
        return parsed.strftime("%Y-%m-%d %H:%M UTC")
    return value or "unknown time"


def _latest_reported_at(articles):
    parsed = [_parse_reported_at(a.get("published_at")) for a in articles]
    parsed = [p for p in parsed if p]
    if not parsed:
        return "unknown time"
    return max(parsed).strftime("%Y-%m-%d %H:%M UTC")


def _source_lines(articles):
    def sort_key(article):
        return _parse_reported_at(article.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc)

    lines = ["Sources:"]
    for a in sorted(articles, key=sort_key, reverse=True):
        reported = _format_reported_at(a.get("published_at"))
        title = a.get("title", "Untitled")
        url = a.get("url")
        if url:
            lines.append(f"- {a['source']} — reported {reported} — [{title}]({url})")
        else:
            lines.append(f"- {a['source']} — reported {reported} — {title}")
    return lines


def _aggregate(tracked):
    """Group tracked articles by canonical story, compute scores and theme metadata."""
    stories = defaultdict(lambda: {"articles": [], "sources": set(), "importance_sum": 0, "theme_counts": defaultdict(int)})

    for a in tracked:
        label = a.get("canonical_label", a["story_label"])
        theme = a["theme"]
        stories[label]["articles"].append(a)
        stories[label]["sources"].add(a["source"])
        stories[label]["importance_sum"] += a["importance"]
        stories[label]["theme_counts"][theme] += 1

    result = []
    for label, data in stories.items():
        articles = data["articles"]
        themes = set(data["theme_counts"])
        primary_theme = max(
            themes,
            key=lambda theme: (
                data["theme_counts"][theme],
                sum(a["importance"] for a in articles if a["theme"] == theme),
            ),
        )
        result.append({
            "canonical_label": label,
            "theme":           primary_theme,
            "themes":          themes,
            "trend":           articles[0].get("trend", "steady"),
            "source_count":    len(data["sources"]),
            "importance_avg":  data["importance_sum"] / len(articles),
            "articles":        articles,
        })
    return result


def _theme_summary(story):
    themes = [theme for theme in THEME_ORDER if theme in story["themes"]]
    return " / ".join(themes)


def _is_lead_candidate(story):
    if story["themes"] & LEAD_EXCLUDED_THEMES:
        return False
    if _has_low_interest_keywords(story):
        return False
    if story["themes"] & LOW_INTEREST_LEAD_THEMES:
        return story["importance_avg"] >= 4.5 and story["source_count"] >= 3
    return True


def _has_low_interest_keywords(story):
    text = " ".join(
        [story["canonical_label"]]
        + [a.get("title", "") for a in story["articles"]]
        + [a.get("description", "") for a in story["articles"]]
    ).lower()
    return any(keyword in text for keyword in LOW_INTEREST_KEYWORDS)


def _is_other_important(story):
    if "Other" not in story["themes"] or _has_low_interest_keywords(story):
        return False
    return story["importance_avg"] >= 2.5 or story["source_count"] >= 2


def _section_candidates(stories, predicate, used_labels, limit):
    candidates = [
        story for story in stories
        if story["canonical_label"] not in used_labels
        and not (story["themes"] & SECTION_EXCLUDED_THEMES)
        and predicate(story)
    ]
    return sorted(candidates, key=_score, reverse=True)[:limit]


def _get_briefings(stories):
    """One GPT call for all stories across all sections."""
    if not stories:
        return {}

    client = get_openai_client()

    items = [
        {
            "canonical_label": s["canonical_label"],
            "articles": [
                {
                    "source": a["source"],
                    "title": a["title"],
                    "description": a["description"],
                    "reported_at": a.get("published_at", ""),
                    "url": a.get("url", ""),
                }
                for a in s["articles"]
            ],
        }
        for s in stories
    ]

    response = client.chat.completions.create(
        model=BRIEFING_MODEL,
        messages=[
            {"role": "system", "content": BRIEFING_PROMPT},
            {"role": "user",   "content": json.dumps(items, ensure_ascii=False)},
        ],
        response_format={"type": "json_object"},
    )

    payload = parse_json_object(response)
    briefings = payload.get("briefings")
    if not isinstance(briefings, list):
        raise ValueError('Model response must contain a "briefings" list')
    return {
        b["canonical_label"]: str(b.get("briefing", "")).strip()
        for b in briefings
        if isinstance(b, dict) and "canonical_label" in b
    }


def _missing_briefing_stories(stories, briefings):
    return [
        story for story in stories
        if not briefings.get(story["canonical_label"], "").strip()
    ]


def _fallback_briefing(story):
    articles = sorted(
        story["articles"],
        key=lambda article: _parse_reported_at(article.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    first = articles[0]
    latest = _latest_reported_at(articles)
    title = first.get("title") or story["canonical_label"]
    source = first.get("source", "A source")
    source_count = story["source_count"]
    source_word = "sources" if source_count > 1 else "source"
    return (
        f"{story['canonical_label']} is included based on {source_count} {source_word}, "
        f"with the latest report at {latest}. The lead item is from {source}: {title}."
    )


def build_briefing_markdown(tracked, n=3, global_n=10):
    if not tracked:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        return "\n".join([
            "# Top Developments",
            f"_{ts}_",
            "",
            "No tracked stories found.",
        ])

    stories = sorted(_aggregate(tracked), key=_score, reverse=True)

    lead_count = min(max(n, 3), 8)
    lead_stories = [story for story in stories if _is_lead_candidate(story)][:lead_count]
    used_labels = {story["canonical_label"] for story in lead_stories}

    politics = _section_candidates(
        stories,
        lambda story: bool(story["themes"] & POLITICS_THEMES),
        used_labels,
        global_n,
    )
    used_labels.update(story["canonical_label"] for story in politics)

    economy = _section_candidates(
        stories,
        lambda story: "Economy" in story["themes"],
        used_labels,
        max(3, min(global_n, 6)),
    )
    used_labels.update(story["canonical_label"] for story in economy)

    other = _section_candidates(
        stories,
        _is_other_important,
        used_labels,
        max(3, min(global_n, 6)),
    )

    sections = [
        ("Top Developments", lead_stories),
        ("Politics", politics),
        ("Economy", economy),
        ("Other Important Stories", other),
    ]

    # One GPT call for all displayed stories, deduplicated.
    seen   = set()
    to_brief = []
    for s in [s for _, section_stories in sections for s in section_stories]:
        if s["canonical_label"] not in seen:
            seen.add(s["canonical_label"])
            to_brief.append(s)
    briefings = _get_briefings(to_brief)
    missing = _missing_briefing_stories(to_brief, briefings)
    if missing:
        briefings.update(_get_briefings(missing))
    for story in _missing_briefing_stories(to_brief, briefings):
        briefings[story["canonical_label"]] = _fallback_briefing(story)

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# Top Developments",
        f"_{ts}_",
        "",
    ]

    for section_title, section_stories in sections:
        if not section_stories:
            continue
        if section_title != "Top Developments":
            lines += ["---", "", f"# {section_title}", ""]
        for i, s in enumerate(section_stories, 1):
            label      = s["canonical_label"]
            icon       = TREND_ICON.get(s["trend"], "")
            importance = round(s["importance_avg"], 1)
            sources    = s["source_count"]
            reported   = _latest_reported_at(s["articles"])
            lines += [
                f"## {i}. {icon} {label}",
                f"_{_theme_summary(s)} — importance {importance} — {sources} {'sources' if sources > 1 else 'source'} — latest reported {reported}_",
                "",
                briefings.get(label, ""),
                "",
                *_source_lines(s["articles"]),
                "",
            ]

    return "\n".join(lines)


def write_top10(tracked, n=3):
    BRIEFINGS_DIR.mkdir(exist_ok=True)
    md  = build_briefing_markdown(tracked, n)
    out = BRIEFINGS_DIR / f"briefing_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    out.write_text(md, encoding="utf-8")
    print(f"Written: {out}")
    return out
