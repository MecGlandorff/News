import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from src.llm import (
    create_cached_chat_completion,
    mark_schema_failure,
    parse_json_object,
    save_cached_chat_completion,
)
from src.source_agreement import claim_source_agreement, source_agreement_label


STATUS_VALUES = {"new", "developing", "escalating", "cooling", "disputed", "unresolved"}
CONFIDENCE_VALUES = {"high", "medium", "low"}
SOURCE_AGREEMENT_VALUES = {"broad", "partial", "mixed", "single-source", "disputed"}
DISPUTE_FLAG_VALUES = {"none", "possible conflict"}
BRIEFING_PROMPT_VERSION = "2026-05-20-v1"

BRIEFING_PROMPT = """You are writing a daily news intelligence briefing for an informed reader.

The voice should be sharp, analytical, and neutral: concise Economist-style judgment, not generic summary prose.

For each story, return structured story-card fields:
- status: one of new | developing | escalating | cooling | disputed | unresolved
- confidence: one of high | medium | low
- source_agreement: one of broad | partial | mixed | single-source | disputed
- dispute_flag: one of none | possible conflict
- delta_summary: one sentence answering what materially changed today
- briefing: 120-190 words explaining what happened, why it matters, and the stakes
- open_questions: 0-3 concrete things to watch next

Rules:
- Base current developments on today's article titles, descriptions, reported_at timestamps, and supplied structured claims.
- If structured claims are supplied, use them as the primary factual grounding. Do not assert factual details unsupported by either claims or today's article metadata.
- Use previous_context only for continuity and comparison. Do not present old context as fresh reporting.
- If previous_context is absent, delta_summary must be exactly: First detected today.
- If current_developments contains a new_child item, write delta_summary as a new development inside the existing arc or parent context, not as a first-detected story.
- Use arc_label and parent_label as context only; do not imply the child story is the same event as its arc or parent.
- Surface disagreement, allegations, uncertainty, or divergent numbers/status claims instead of smoothing them into confident prose.
- Use possible conflict for source divergence; do not claim a confirmed contradiction.
- Do not invent source URLs; URLs are supplied separately in the output.
- Avoid filler phrases and generic endings.

Return a JSON object with key "briefings": array of {canonical_label, status, confidence, source_agreement, dispute_flag, delta_summary, briefing, open_questions}."""


def parse_reported_at(value):
    try:
        parsed = parsedate_to_datetime(value)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def latest_reported_at(articles):
    parsed = [parse_reported_at(article.get("published_at")) for article in articles]
    parsed = [value for value in parsed if value]
    if not parsed:
        return "unknown time"
    return max(parsed).strftime("%Y-%m-%d %H:%M UTC")


def choice(value, allowed, default):
    aliases = {
        "single source": "single-source",
        "single_source": "single-source",
        "possible-conflict": "possible conflict",
        "possible_conflict": "possible conflict",
        "confirmed-conflict": "possible conflict",
        "confirmed_conflict": "possible conflict",
        "confirmed conflict": "possible conflict",
        "no conflict": "none",
        "none detected": "none",
    }
    normalized = str(value or "").strip().casefold().replace("_", "-")
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in allowed else default


def display_choice(value):
    return str(value or "").replace("-", " ").title()


def clean_open_questions(value):
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    questions = []
    for item in value:
        text = str(item or "").strip()
        if text:
            questions.append(text)
        if len(questions) >= 3:
            break
    return questions


def local_dispute_flag(story):
    claim_agreement = story.get("claim_source_agreement") or {}
    if claim_agreement.get("source_divergence_notes"):
        return "possible conflict"
    text = " ".join(
        [story.get("canonical_label", "")]
        + [article.get("title", "") for article in story.get("articles", [])]
        + [article.get("description", "") for article in story.get("articles", [])]
    ).casefold()
    cues = (
        "allege", "alleged", "accuse", "accused", "contradict",
        "denies", "denied", "dispute", "disputed", "reject",
        "rejected", "unconfirmed",
    )
    return "possible conflict" if any(cue in text for cue in cues) else "none"


def default_status(story):
    dispute_flag = local_dispute_flag(story)
    if dispute_flag != "none":
        return "disputed"
    if any(development.get("status") == "new_child" for development in story.get("developments", [])):
        return "developing"
    trend = story.get("trend", "steady")
    if trend == "new":
        return "new"
    if trend == "up":
        return "escalating"
    if trend == "down":
        return "cooling"
    return "developing"


def default_confidence(story):
    if local_dispute_flag(story) != "none":
        return "medium"
    source_count = story.get("source_count", 0)
    if source_count >= 3:
        return "high"
    if source_count >= 2:
        return "medium"
    return "low"


def default_source_agreement(story):
    claim_agreement = story.get("claim_source_agreement") or {}
    if claim_agreement.get("label"):
        return claim_agreement["label"]
    return source_agreement_label(
        story.get("articles", []),
        has_dispute=local_dispute_flag(story) != "none",
    )


def default_briefing_payload(story=None):
    story = story or {}
    return {
        "briefing": "",
        "delta_summary": "",
        "status": default_status(story) if story else "developing",
        "confidence": default_confidence(story) if story else "medium",
        "source_agreement": default_source_agreement(story) if story else "partial",
        "dispute_flag": local_dispute_flag(story) if story else "none",
        "open_questions": [],
    }


def defaults_by_label(stories):
    return {
        story["canonical_label"]: default_briefing_payload(story)
        for story in stories
    }


def claims_for_prompt(story):
    if story.get("claims_for_prompt") is not None:
        return story["claims_for_prompt"]
    from src.claims import get_claims_for_story
    article_by_id = {str(article.get("id")): article for article in story.get("articles", [])}
    claims = []
    for claim in get_claims_for_story(story.get("story_id"))[:12]:
        article = article_by_id.get(str(claim.get("article_id")), {})
        claims.append({
            "article_id": claim.get("article_id"),
            "source_id": article.get("source_id"),
            "claim_text": claim.get("claim_text", ""),
            "claim_type": claim.get("claim_type", ""),
            "evidence_span": claim.get("evidence_span", ""),
            "confidence": claim.get("confidence"),
            "source": claim.get("source") or article.get("source", ""),
            "article_title": claim.get("article_title") or article.get("title", ""),
            "url": claim.get("url") or article.get("url", ""),
        })
    return claims


def attach_claim_source_agreement(story):
    claims = claims_for_prompt(story)
    agreement = claim_source_agreement(claims, story.get("articles", []))
    story["claims_for_prompt"] = claims
    story["claim_source_agreement"] = agreement
    return agreement


def apply_claim_backed_agreement(payloads, stories):
    for story in stories:
        label = story.get("canonical_label")
        agreement = story.get("claim_source_agreement") or {}
        agreement_label = agreement.get("label")
        if not label or not agreement_label:
            continue
        payload = payloads.setdefault(label, default_briefing_payload(story))
        payload["source_agreement"] = agreement_label
        if agreement.get("source_divergence_notes"):
            payload["dispute_flag"] = "possible conflict"
    return payloads


def get_briefings(stories, get_client, model, include_evidence=False):
    """Make one briefing model call for all selected stories."""
    if not stories:
        return {}

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
            "articles": [
                {
                    "source_id": article.get("source_id"),
                    "source": article["source"],
                    "title": article["title"],
                    "description": article["description"],
                    "reported_at": article.get("published_at", ""),
                    "url": article.get("url", ""),
                }
                for article in story["articles"]
            ],
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
    if include_evidence:
        apply_claim_backed_agreement(normalized, stories)
    return normalized


def normalize_briefing_payloads(payloads, defaults_by_label=None):
    """Accept new structured payloads and legacy label->text test doubles."""
    normalized = {}
    for label, payload in (payloads or {}).items():
        defaults = dict((defaults_by_label or {}).get(label, default_briefing_payload()))
        if isinstance(payload, dict):
            briefing = str(payload.get("briefing", "")).strip()
            delta_summary = str(payload.get("delta_summary") or payload.get("delta") or "").strip()
            status = choice(payload.get("status"), STATUS_VALUES, defaults["status"])
            confidence = choice(payload.get("confidence"), CONFIDENCE_VALUES, defaults["confidence"])
            source_agreement = choice(
                payload.get("source_agreement"),
                SOURCE_AGREEMENT_VALUES,
                defaults["source_agreement"],
            )
            dispute_flag = choice(payload.get("dispute_flag"), DISPUTE_FLAG_VALUES, defaults["dispute_flag"])
            open_questions = clean_open_questions(payload.get("open_questions"))
        else:
            briefing = str(payload or "").strip()
            delta_summary = ""
            status = defaults["status"]
            confidence = defaults["confidence"]
            source_agreement = defaults["source_agreement"]
            dispute_flag = defaults["dispute_flag"]
            open_questions = defaults["open_questions"]
        defaults.update({
            "briefing": briefing,
            "delta_summary": delta_summary,
            "status": status,
            "confidence": confidence,
            "source_agreement": source_agreement,
            "dispute_flag": dispute_flag,
            "open_questions": open_questions,
        })
        normalized[label] = defaults
    return normalized


def merge_briefing_payloads(existing, updates, defaults_by_label=None):
    for label, update in normalize_briefing_payloads(updates, defaults_by_label).items():
        current = existing.setdefault(label, dict((defaults_by_label or {}).get(label, default_briefing_payload())))
        for key in (
            "briefing",
            "delta_summary",
            "status",
            "confidence",
            "source_agreement",
            "dispute_flag",
            "open_questions",
        ):
            if update.get(key):
                current[key] = update[key]
    return existing


def payload_briefing(payloads, label):
    payload = payloads.get(label, {})
    if isinstance(payload, dict):
        return str(payload.get("briefing", "")).strip()
    return str(payload or "").strip()


def fallback_delta_summary(story):
    previous_context = story.get("previous_context") or {}
    new_children = [
        development.get("label", "")
        for development in story.get("developments", [])
        if development.get("status") == "new_child" and development.get("label")
    ]
    if new_children:
        labels = "; ".join(new_children[:3])
        return f"New development inside the existing arc: {labels}."
    if not previous_context:
        return "First detected today."

    trend = story.get("trend", "steady")
    if trend == "up":
        return "Coverage increased today, but the available reporting did not isolate a distinct new turn."
    if trend == "down":
        return "Coverage cooled today, with reporting shifting toward follow-up coverage rather than a new turn."
    return "Today's reporting continued the story without a distinct new turn."


def missing_briefing_stories(stories, briefing_payloads):
    return [
        story for story in stories
        if not payload_briefing(briefing_payloads, story["canonical_label"])
    ]


def fallback_briefing(story):
    articles = sorted(
        story["articles"],
        key=lambda article: parse_reported_at(article.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    first = articles[0]
    latest = latest_reported_at(articles)
    title = first.get("title") or story["canonical_label"]
    source = first.get("source", "A source")
    source_count = story["source_count"]
    source_word = "sources" if source_count > 1 else "source"
    return (
        f"{story['canonical_label']} is included based on {source_count} {source_word}, "
        f"with the latest report at {latest}. The lead item is from {source}: {title}."
    )
