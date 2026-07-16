from datetime import datetime, timezone

from src.article_dates import parse_reported_at
from src.briefing import grounding as briefing_generation
from src.briefing import selection as briefing_selection
from src.briefing.inputs import story_editorial_date


TREND_ICON = {
    "new": "NEW STORY",
    "up": "COVERAGE INCREASING",
    "steady": "COVERAGE STEADY",
    "down": "COVERAGE DECREASING",
}


def _format_reported_at(value):
    parsed = parse_reported_at(value)
    if parsed:
        return parsed.strftime("%Y-%m-%d %H:%M UTC")
    return value or "unknown time"


def _latest_reported_at(articles):
    parsed = [parse_reported_at(a.get("published_at")) for a in articles]
    parsed = [p for p in parsed if p]
    if not parsed:
        return "unknown time"
    return max(parsed).strftime("%Y-%m-%d %H:%M UTC")


def _source_lines(articles):
    def sort_key(article):
        return parse_reported_at(article.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc)

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


def _has_new_child_development(story):
    return any(
        development.get("status") == "new_child"
        for development in story.get("developments", [])
    )


def _trend_label(story):
    if _has_new_child_development(story):
        return "NEW DEVELOPMENT"
    return TREND_ICON.get(story.get("trend"), "")


def _development_summary_line(story):
    context_parts = []
    arc_label = str(story.get("arc_label") or "").strip()
    parent_label = str(story.get("parent_label") or "").strip()
    if arc_label and arc_label != story.get("canonical_label"):
        context_parts.append(f"**Arc:** {arc_label}")
    if parent_label and parent_label != story.get("canonical_label"):
        context_parts.append(f"**Parent story:** {parent_label}")

    developments = story.get("developments") or []
    labels = [development.get("label", "") for development in developments if development.get("label")]
    labels = [label for label in labels if label and label != story.get("canonical_label")]
    if labels:
        label_text = "; ".join(labels[:4])
        if not context_parts:
            context_parts.append(f"**Parent arc:** {story['canonical_label']}")
        context_parts.append(f"**Today's development:** {label_text}")
    if context_parts:
        return " | ".join(context_parts)
    return ""


def _evidence_lines(story_id, as_of_date=None):
    """Return formatted evidence lines for a story, or [] if none."""
    if story_id is None:
        return []
    from src.claims import get_claims_for_story
    claims = [
        claim for claim in get_claims_for_story(story_id, as_of_date=as_of_date, history_days=7)
        if claim.get("evidence_span")
    ]
    if not claims:
        return []
    lines = ["", "### Evidence"]
    for c in claims[:8]:
        span = c["evidence_span"]
        pct  = int((c["confidence"] or 0.5) * 100)
        source = c.get("source") or "Unknown source"
        url = c.get("url")
        if url:
            source_ref = f"[{source}]({url})"
        else:
            source_ref = source
        claim_date = str(c.get("editorial_date") or "")
        history_label = ""
        if as_of_date and claim_date and claim_date != as_of_date:
            history_label = f" — historical context ({claim_date})"
        lines.append(
            f'- `{c["claim_type"]}`{history_label} — {source_ref} — "{span}" _({pct}%)_'
        )
    return lines


def _theme_summary(story):
    return briefing_selection.theme_summary(story)


def _display_choice(value):
    return briefing_generation.display_choice(value)


def _clean_open_questions(value):
    return briefing_generation.clean_open_questions(value)


def _default_briefing_payload(story=None):
    return briefing_generation.default_briefing_payload(story)


def _fallback_delta_summary(story):
    return briefing_generation.fallback_delta_summary(story)


def build_briefing_markdown(tracked, n=3, global_n=10, package=None, show_evidence=False):
    if package is None:
        raise ValueError("briefing package is required")

    if not package["stories"]:
        ts = package["generated_at"].strftime("%Y-%m-%d %H:%M")
        return "\n".join([
            "# Top Developments",
            f"_{ts}_",
            "",
            "No tracked stories found.",
        ])

    sections = package["sections"]
    briefings = package["briefings"]
    deltas = package.get("deltas", {})
    cards = package.get("briefing_cards", {})
    ts = package["generated_at"].strftime("%Y-%m-%d %H:%M")
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
            icon       = _trend_label(s)
            importance = round(s["importance_avg"], 1)
            sources    = s["source_count"]
            reported   = _latest_reported_at(s["articles"])
            delta      = str(deltas.get(label, "")).strip() or _fallback_delta_summary(s)
            card       = cards.get(label) or _default_briefing_payload(s)
            open_questions = _clean_open_questions(card.get("open_questions"))
            story_lines = [
                f"## {i}. {icon} {label}",
                f"_{_theme_summary(s)} — importance {importance} — {sources} {'sources' if sources > 1 else 'source'} — latest reported {reported}_",
                "",
                (
                    f"**Status:** {_display_choice(card.get('status'))} | "
                    f"**Confidence:** {_display_choice(card.get('confidence'))} | "
                    f"**Source agreement:** {_display_choice(card.get('source_agreement'))} | "
                    f"**Dispute:** {_display_choice(card.get('dispute_flag'))}"
                ),
                "",
                f"**What changed today:** {delta}",
                "",
                "### Why it matters",
                briefings.get(label, ""),
                "",
            ]
            development_line = _development_summary_line(s)
            if development_line:
                story_lines += [development_line, ""]
            if open_questions:
                story_lines += [
                    "### What to watch",
                    *[f"- {question}" for question in open_questions],
                    "",
                ]
            story_lines += _source_lines(s["articles"])
            if show_evidence:
                story_lines += _evidence_lines(
                    s.get("story_id"),
                    as_of_date=story_editorial_date(s),
                )
            story_lines.append("")
            lines += story_lines

    return "\n".join(lines)
