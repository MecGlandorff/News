import json
from datetime import datetime, timezone

from src.article_dates import parse_reported_at
from src.briefing.constants import (
    CONFIDENCE_VALUES,
    DISPUTE_FLAG_VALUES,
    SOURCE_AGREEMENT_VALUES,
    STATUS_VALUES,
)
from src.briefing.inputs import (
    articles_for_prompt,
    claims_for_prompt,
    latest_reported_at,
)
from src.number_normalization import normalized_number_tokens
from src.source_agreement import claim_source_agreement, source_agreement_label


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
        "conflicting reports",
        "contradictory accounts",
        "sources disagree",
        "accounts differ",
        "disputed by",
        "contested by",
        "unconfirmed",
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


def attach_claim_source_agreement(story):
    claims = claims_for_prompt(story)
    agreement = claim_source_agreement(
        [claim for claim in claims if claim.get("is_current")],
        story.get("articles", []),
    )
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


def apply_numeric_grounding_guard(payloads, stories):
    """Replace prose fields that introduce source-absent numeric facts."""
    stories_by_label = {story.get("canonical_label"): story for story in stories}
    for label, payload in payloads.items():
        story = stories_by_label.get(label)
        if not story:
            continue
        material = [
            label,
            story.get("arc_label", ""),
            story.get("parent_label", ""),
            json.dumps(story.get("source_support", {}), ensure_ascii=False),
            json.dumps(story.get("developments", []), ensure_ascii=False),
            json.dumps(story.get("previous_context", {}), ensure_ascii=False),
        ]
        for article in articles_for_prompt(story):
            material.extend(
                [
                    article.get("title", ""),
                    article.get("description", ""),
                    article.get("reported_at", ""),
                ]
            )
        for claim in story.get("claims_for_prompt", []):
            material.extend([
                claim.get("editorial_date", ""),
                claim.get("claim_text", ""),
                claim.get("evidence_span", ""),
            ])
        allowed_numbers = normalized_number_tokens(" ".join(str(value) for value in material))

        rejected_fields = []
        for field in ("briefing", "delta_summary"):
            generated_numbers = normalized_number_tokens(payload.get(field, ""))
            if generated_numbers - allowed_numbers:
                rejected_fields.append(field)
        open_questions = payload.get("open_questions", [])
        grounded_questions = [
            question
            for question in open_questions
            if not (
                normalized_number_tokens(question) - allowed_numbers
            )
        ]
        questions_rejected = len(grounded_questions) != len(open_questions)
        if not rejected_fields and not questions_rejected:
            continue
        if "briefing" in rejected_fields:
            payload["briefing"] = fallback_briefing(story)
        if "delta_summary" in rejected_fields:
            payload["delta_summary"] = fallback_delta_summary(story)
        payload["confidence"] = "low"
        question = "Verify the unsupported numeric detail omitted from generated prose."
        payload["open_questions"] = [
            question,
            *[item for item in grounded_questions if item != question],
        ][:3]


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
