from datetime import datetime

from src.briefing import grounding as briefing_generation
from src.briefing import selection as briefing_selection


def _default_briefing_payload(story=None):
    return briefing_generation.default_briefing_payload(story)


def _defaults_by_label(stories):
    return briefing_generation.defaults_by_label(stories)


def _normalize_briefing_payloads(payloads, defaults_by_label=None):
    return briefing_generation.normalize_briefing_payloads(payloads, defaults_by_label)


def _merge_briefing_payloads(existing, updates, defaults_by_label=None):
    return briefing_generation.merge_briefing_payloads(existing, updates, defaults_by_label)


def _fallback_delta_summary(story):
    return briefing_generation.fallback_delta_summary(story)


def _remember_story_briefings(
    stories,
    briefings,
    deltas,
    save_observation_memory,
):
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


def build_briefing_package(
    tracked,
    n=3,
    global_n=10,
    include_evidence=False,
    *,
    get_briefings,
    save_observation_memory,
):
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
        briefing_payloads = _normalize_briefing_payloads(get_briefings(to_brief, include_evidence=True), defaults)
    else:
        briefing_payloads = _normalize_briefing_payloads(get_briefings(to_brief), defaults)
    missing = _missing_briefing_stories(to_brief, briefing_payloads)
    if missing:
        missing_defaults = _defaults_by_label(missing)
        if include_evidence:
            _merge_briefing_payloads(
                briefing_payloads,
                get_briefings(missing, include_evidence=True),
                missing_defaults,
            )
        else:
            _merge_briefing_payloads(briefing_payloads, get_briefings(missing), missing_defaults)
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
    _remember_story_briefings(
        to_brief,
        briefings,
        deltas,
        save_observation_memory,
    )

    return {
        "generated_at": datetime.now(),
        "stories": stories,
        "sections": sections,
        "display_stories": to_brief,
        "briefings": briefings,
        "deltas": deltas,
        "briefing_cards": briefing_payloads,
    }
