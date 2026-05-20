from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from src import briefing_generation, briefing_selection
from src.config import BRIEFING_MODEL
from src.llm import get_openai_client
from src.tracker import save_observation_memory

BRIEFINGS_DIR = Path("briefings")
THEME_ORDER = briefing_selection.THEME_ORDER
POLITICS_THEMES = briefing_selection.POLITICS_THEMES
SECTION_EXCLUDED_THEMES = briefing_selection.SECTION_EXCLUDED_THEMES
LEAD_EXCLUDED_THEMES = briefing_selection.LEAD_EXCLUDED_THEMES
LOW_INTEREST_LEAD_THEMES = briefing_selection.LOW_INTEREST_LEAD_THEMES
LOW_INTEREST_KEYWORDS = briefing_selection.LOW_INTEREST_KEYWORDS
TREND_SCORE = briefing_selection.TREND_SCORE
TREND_ICON  = {"new": "NEW STORY", "up": "COVERAGE INCREASING", "steady": "COVERAGE STEADY", "down": "COVERAGE DECREASING"}
STATUS_VALUES = briefing_generation.STATUS_VALUES
CONFIDENCE_VALUES = briefing_generation.CONFIDENCE_VALUES
SOURCE_AGREEMENT_VALUES = briefing_generation.SOURCE_AGREEMENT_VALUES
DISPUTE_FLAG_VALUES = briefing_generation.DISPUTE_FLAG_VALUES
BRIEFING_PROMPT = briefing_generation.BRIEFING_PROMPT


def _score(story):
    return briefing_selection.score(story)


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


def _evidence_lines(story_id):
    """Return formatted evidence lines for a story, or [] if none."""
    if story_id is None:
        return []
    from src.claims import get_claims_for_story
    claims = [
        claim for claim in get_claims_for_story(story_id)
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
        lines.append(f'- `{c["claim_type"]}` — {source_ref} — "{span}" _({pct}%)_')
    return lines


def _aggregate(tracked):
    return briefing_selection.aggregate(tracked)


def _theme_summary(story):
    return briefing_selection.theme_summary(story)


def _choice(value, allowed, default):
    return briefing_generation.choice(value, allowed, default)


def _display_choice(value):
    return briefing_generation.display_choice(value)


def _clean_open_questions(value):
    return briefing_generation.clean_open_questions(value)


def _local_dispute_flag(story):
    return briefing_generation.local_dispute_flag(story)


def _default_status(story):
    return briefing_generation.default_status(story)


def _default_confidence(story):
    return briefing_generation.default_confidence(story)


def _default_source_agreement(story):
    return briefing_generation.default_source_agreement(story)


def _default_briefing_payload(story=None):
    return briefing_generation.default_briefing_payload(story)


def _defaults_by_label(stories):
    return briefing_generation.defaults_by_label(stories)


def _is_lead_candidate(story):
    return briefing_selection.is_lead_candidate(story)


def _has_low_interest_keywords(story):
    return briefing_selection.has_low_interest_keywords(story)


def _is_other_important(story):
    return briefing_selection.is_other_important(story)


def _section_candidates(stories, predicate, used_labels, limit):
    return briefing_selection.section_candidates(stories, predicate, used_labels, limit)


def _claims_for_prompt(story):
    return briefing_generation.claims_for_prompt(story)


def _get_briefings(stories, include_evidence=False):
    return briefing_generation.get_briefings(
        stories,
        get_client=get_openai_client,
        model=BRIEFING_MODEL,
        include_evidence=include_evidence,
    )


def _normalize_briefing_payloads(payloads, defaults_by_label=None):
    return briefing_generation.normalize_briefing_payloads(payloads, defaults_by_label)


def _merge_briefing_payloads(existing, updates, defaults_by_label=None):
    return briefing_generation.merge_briefing_payloads(existing, updates, defaults_by_label)


def _payload_briefing(payloads, label):
    return briefing_generation.payload_briefing(payloads, label)


def _fallback_delta_summary(story):
    return briefing_generation.fallback_delta_summary(story)


def _remember_story_briefings(stories, briefings, deltas):
    memories = []
    for story in stories:
        label = story["canonical_label"]
        briefing = str(briefings.get(label, "")).strip()
        if not briefing:
            continue
        delta_summary = str(deltas.get(label, "")).strip() or _fallback_delta_summary(story)
        for observation_id in story.get("observation_ids", []):
            memories.append({
                "observation_id": observation_id,
                "summary": briefing,
                "delta_summary": delta_summary,
            })
    save_observation_memory(memories)


def _missing_briefing_stories(stories, briefing_payloads):
    return briefing_generation.missing_briefing_stories(stories, briefing_payloads)


def _fallback_briefing(story):
    return briefing_generation.fallback_briefing(story)


def build_briefing_package(tracked, n=3, global_n=10, include_evidence=False):
    if not tracked:
        return {
            "generated_at": datetime.now(),
            "stories": [],
            "sections": [],
            "display_stories": [],
            "briefings": {},
            "deltas": {},
            "briefing_cards": {},
        }

    selected = briefing_selection.select_story_sections(tracked, n=n, global_n=global_n)
    stories = selected["stories"]
    sections = selected["sections"]
    to_brief = selected["display_stories"]

    # Keep the expensive briefing call batched across displayed stories.
    defaults = _defaults_by_label(to_brief)
    if include_evidence:
        briefing_payloads = _normalize_briefing_payloads(_get_briefings(to_brief, include_evidence=True), defaults)
    else:
        briefing_payloads = _normalize_briefing_payloads(_get_briefings(to_brief), defaults)
    missing = _missing_briefing_stories(to_brief, briefing_payloads)
    if missing:
        missing_defaults = _defaults_by_label(missing)
        if include_evidence:
            _merge_briefing_payloads(
                briefing_payloads,
                _get_briefings(missing, include_evidence=True),
                missing_defaults,
            )
        else:
            _merge_briefing_payloads(briefing_payloads, _get_briefings(missing), missing_defaults)
    for story in to_brief:
        label = story["canonical_label"]
        payload = briefing_payloads.setdefault(label, _default_briefing_payload(story))
        if not payload.get("briefing"):
            payload["briefing"] = _fallback_briefing(story)
        if not payload.get("delta_summary"):
            payload["delta_summary"] = _fallback_delta_summary(story)

    briefings = {
        story["canonical_label"]: briefing_payloads[story["canonical_label"]]["briefing"]
        for story in to_brief
    }
    deltas = {
        story["canonical_label"]: briefing_payloads[story["canonical_label"]]["delta_summary"]
        for story in to_brief
    }
    _remember_story_briefings(to_brief, briefings, deltas)

    return {
        "generated_at": datetime.now(),
        "stories": stories,
        "sections": sections,
        "display_stories": to_brief,
        "briefings": briefings,
        "deltas": deltas,
        "briefing_cards": briefing_payloads,
    }


def build_briefing_markdown(tracked, n=3, global_n=10, package=None, show_evidence=False):
    package = package or build_briefing_package(tracked, n=n, global_n=global_n, include_evidence=show_evidence)

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
                story_lines += _evidence_lines(s.get("story_id"))
            story_lines.append("")
            lines += story_lines

    return "\n".join(lines)


def write_top10(tracked, n=3, package=None, show_evidence=False):
    BRIEFINGS_DIR.mkdir(exist_ok=True)
    md  = build_briefing_markdown(tracked, n, package=package, show_evidence=show_evidence)
    out = BRIEFINGS_DIR / f"briefing_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    out.write_text(md, encoding="utf-8")
    print(f"Written: {out}")
    return out
