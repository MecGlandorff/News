from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from src.article_dates import parse_reported_at

THEME_ORDER = ["Geopolitics & War", "USA Politics", "Dutch Politics", "Economy", "Tech", "Climate", "Science", "Sports", "Other"]
OUTPUT_DIR  = Path("output")

TREND_ICON = {
    "new":    "🆕",
    "up":     "📈",
    "steady": "➡️",
    "down":   "📉",
}


def _parse_date(date_str):
    return parse_reported_at(date_str) or datetime.min.replace(tzinfo=timezone.utc)


def _format_reported_at(date_str):
    parsed = _parse_date(date_str)
    if parsed == datetime.min.replace(tzinfo=timezone.utc):
        return date_str or "unknown time"
    return parsed.strftime("%Y-%m-%d %H:%M UTC")


def build_themed_markdown(articles):
    if not articles:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        return "\n".join([
            "# News Digest",
            f"_Generated {ts} — 0 articles_",
            "",
            "No articles found.",
        ])

    # Use canonical_label if available (tracked), else story_label
    label_key = "canonical_label" if "canonical_label" in articles[0] else "story_label"

    # Choose one primary theme per canonical story so a cross-theme story is
    # rendered once rather than looking like multiple independent events.
    stories = defaultdict(list)
    seen_articles = defaultdict(set)
    for a in articles:
        label = a[label_key]
        story_key = (
            ("story_id", a["story_id"])
            if a.get("story_id") is not None
            else ("label", label)
        )
        identity = a.get("occurrence_id") or a.get("id") or a.get("url")
        if identity in seen_articles[story_key]:
            continue
        seen_articles[story_key].add(identity)
        stories[story_key].append(a)
    themes = defaultdict(lambda: defaultdict(list))
    for story_key, story_articles in stories.items():
        theme_counts = defaultdict(int)
        theme_importance = defaultdict(int)
        for article in story_articles:
            theme_counts[article["theme"]] += 1
            theme_importance[article["theme"]] += int(article.get("importance", 0))
        primary_theme = max(
            theme_counts,
            key=lambda theme: (theme_counts[theme], theme_importance[theme], theme),
        )
        themes[primary_theme][story_key].extend(story_articles)

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# News Digest",
        f"_Generated {ts} — {len(articles)} articles_",
        "",
        "---",
        "",
    ]

    for theme in THEME_ORDER:
        if theme not in themes:
            continue

        lines += [f"## {theme}", ""]

        # Sort stories by highest importance desc
        ordered_stories = sorted(
            themes[theme].items(),
            key=lambda x: max(a["importance"] for a in x[1]),
            reverse=True,
        )

        for _story_key, story_articles in ordered_stories:
            label = story_articles[0][label_key]
            max_importance = max(a["importance"] for a in story_articles)
            trend          = story_articles[0].get("trend", "")
            trend_icon     = TREND_ICON.get(trend, "")

            lines += [f"### {trend_icon} {label} _(importance {max_importance})_", ""]

            for a in sorted(story_articles, key=lambda x: _parse_date(x["published_at"]), reverse=True):
                reported = _format_reported_at(a.get("published_at"))
                url = a.get("url")
                if url:
                    lines.append(f"- {a['source']} — reported {reported} — [{a['title']}]({url})")
                else:
                    lines.append(f"- {a['source']} — reported {reported} — {a['title']}")

            lines.append("")

    return "\n".join(lines)


def write_digest(articles):
    OUTPUT_DIR.mkdir(exist_ok=True)
    md = build_themed_markdown(articles)
    out = OUTPUT_DIR / f"digest_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    out.write_text(md, encoding="utf-8")
    print(f"Written: {out}  ({out.stat().st_size / 1024:.1f} KB)")
    return out
