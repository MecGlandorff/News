import json

from src.briefing.constants import BRIEFING_PROMPT, BRIEFING_PROMPT_VERSION
from src.briefing.grounding import (
    apply_claim_backed_agreement,
    apply_numeric_grounding_guard,
    attach_claim_source_agreement,
    defaults_by_label,
    normalize_briefing_payloads,
)
from src.briefing.inputs import articles_for_prompt
from src.config import BRIEFING_STORIES_PER_CALL
from src.llm import (
    create_cached_chat_completion,
    mark_schema_failure,
    parse_json_object,
    save_cached_chat_completion,
)


def get_briefings(stories, get_client, model, include_evidence=False):
    """Generate briefing payloads in bounded story batches."""
    if not stories:
        return {}
    if len(stories) > BRIEFING_STORIES_PER_CALL:
        merged = {}
        for index in range(0, len(stories), BRIEFING_STORIES_PER_CALL):
            merged.update(
                get_briefings(
                    stories[index:index + BRIEFING_STORIES_PER_CALL],
                    get_client,
                    model,
                    include_evidence=include_evidence,
                )
            )
        return merged

    items = []
    for story in stories:
        item = {
            "canonical_label": story["canonical_label"],
            "arc_label": story.get("arc_label", ""),
            "parent_label": story.get("parent_label", ""),
            "source_support": story.get("source_support", {}),
            "current_developments": [
                {
                    "label": development.get("label", ""),
                    "status": development.get("status", ""),
                    "article_count": development.get("article_count", 0),
                    "source_count": development.get("source_count", 0),
                    "parent_relationship": development.get("parent_relationship", ""),
                    "parent_confidence": development.get("parent_confidence", ""),
                }
                for development in story.get("developments", [])
            ],
            "articles": articles_for_prompt(story),
        }
        if story.get("previous_context"):
            item["previous_context"] = story["previous_context"]
        if include_evidence:
            agreement = attach_claim_source_agreement(story)
            item["claims"] = story["claims_for_prompt"]
            if agreement.get("label"):
                item["claim_source_agreement"] = agreement
        items.append(item)

    messages = [
        {"role": "system", "content": BRIEFING_PROMPT},
        {"role": "user", "content": json.dumps(items, ensure_ascii=False)},
    ]
    response, cache_metadata, cache_hit = create_cached_chat_completion(
        get_client,
        model=model,
        messages=messages,
        purpose="brief",
        prompt_version=BRIEFING_PROMPT_VERSION,
        response_format={"type": "json_object"},
    )

    payload = parse_json_object(response)
    briefings = payload.get("briefings")
    if not isinstance(briefings, list):
        mark_schema_failure('Model response must contain a "briefings" list', response=response)
        raise ValueError('Model response must contain a "briefings" list')
    if not cache_hit:
        save_cached_chat_completion(cache_metadata, response)
    normalized = normalize_briefing_payloads({
        briefing["canonical_label"]: {
            "briefing": str(briefing.get("briefing", "")).strip(),
            "delta_summary": str(briefing.get("delta_summary") or briefing.get("delta") or "").strip(),
            "status": briefing.get("status"),
            "confidence": briefing.get("confidence"),
            "source_agreement": briefing.get("source_agreement"),
            "dispute_flag": briefing.get("dispute_flag"),
            "open_questions": briefing.get("open_questions"),
        }
        for briefing in briefings
        if isinstance(briefing, dict) and "canonical_label" in briefing
    }, defaults_by_label(stories))
    apply_numeric_grounding_guard(normalized, stories)
    if include_evidence:
        apply_claim_backed_agreement(normalized, stories)
    return normalized
