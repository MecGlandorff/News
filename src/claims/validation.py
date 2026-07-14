import re

from src.claims.constants import CLAIM_TYPES
from src.claims.content import _evidence_in_content, _normalize_for_span_match
from src.number_normalization import normalized_number_tokens


_WORD_PATTERN = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?")

_NEGATION_TOKENS = {"no", "not", "never", "neither", "nor", "without"}

_UP_DIRECTION_TOKENS = {
    "gain", "gained", "grew", "grow", "higher", "increase", "increased",
    "increases", "raising", "raise", "raised", "rise", "rises", "rose", "up",
}

_DOWN_DIRECTION_TOKENS = {
    "decline", "declined", "decrease", "decreased", "decreases", "down", "drop",
    "dropped", "fall", "fell", "falls", "lower", "lowered", "reduce", "reduced",
}

_UNIT_GROUPS = {
    "percent": {"percent", "percentage", "pct"},
    "currency": {"dollar", "dollars", "euro", "euros", "pound", "pounds", "yen"},
    "magnitude": {"billion", "billions", "million", "millions", "thousand", "thousands"},
    "distance": {"kilometer", "kilometers", "km", "mile", "miles"},
}


def _number_tokens(text):
    return normalized_number_tokens(text)


def _word_tokens(text):
    return set(_WORD_PATTERN.findall(_normalize_for_span_match(text)))


def _direction(text):
    tokens = _word_tokens(text)
    if tokens & _UP_DIRECTION_TOKENS:
        return "up"
    if tokens & _DOWN_DIRECTION_TOKENS:
        return "down"
    return None


def _unit_groups(text):
    tokens = _word_tokens(text)
    groups = {name for name, values in _UNIT_GROUPS.items() if tokens & values}
    if "%" in str(text or ""):
        groups.add("percent")
    if re.search(r"[$€£¥]", str(text or "")):
        groups.add("currency")
    return groups


def _semantic_mismatch(claim_text, evidence_span):
    claim_tokens = _word_tokens(claim_text)
    span_tokens = _word_tokens(evidence_span)
    if bool(claim_tokens & _NEGATION_TOKENS) != bool(span_tokens & _NEGATION_TOKENS):
        return True

    claim_direction = _direction(claim_text)
    span_direction = _direction(evidence_span)
    if claim_direction and span_direction and claim_direction != span_direction:
        return True

    claim_units = _unit_groups(claim_text)
    span_units = _unit_groups(evidence_span)
    return bool(claim_units and span_units and claim_units.isdisjoint(span_units))


def _derivability_check(claim_text, evidence_span, _entities):
    """Decide whether evidence_span deterministically supports claim_text.

    Returns one of:
      "reject"    — quantities or basic semantic direction conflict.
      "accept"    — evidence_span contains claim_text near-verbatim.
      "uncertain" — neither rule applies; needs the LLM verifier.
    """
    claim_numbers = _number_tokens(claim_text)
    span_numbers = _number_tokens(evidence_span)
    if claim_numbers - span_numbers:
        return "reject"

    normalized_claim = _normalize_for_span_match(claim_text)
    normalized_span = _normalize_for_span_match(evidence_span)
    if normalized_claim and normalized_claim in normalized_span:
        return "accept"

    if _semantic_mismatch(claim_text, evidence_span):
        return "reject"

    return "uncertain"


def validate_claims_for_content(claims_data, content, verify_claim):
    valid_claims = []
    dropped = 0
    for claim in claims_data:
        validated, _decision = _validated_claim(claim, content, verify_claim)
        if not validated:
            dropped += 1
            continue
        valid_claims.append(validated)
    return valid_claims, dropped


def classify_claims(claims_data, content, verify_claim):
    """Validate every claim and return [(validated_or_None, decision), ...].

    Runs the LLM verifier for uncertain claims. Must be called outside any
    open SQLite transaction so the verifier's network call does not hold a
    write lock.
    """
    return [_validated_claim(claim, content, verify_claim) for claim in claims_data]


def _clean_string(value):
    return value.strip() if isinstance(value, str) else ""


def _validated_confidence(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    confidence = float(value)
    if confidence < 0.0 or confidence > 1.0:
        return None
    return confidence


def _validated_claim(claim, content, verify_claim):
    """Return (validated_dict_or_None, decision).

    decision is one of:
      "invalid"             — failed schema / field / span-in-article checks.
      "derivability_reject" — deterministic quantity or semantic mismatch.
      "cheap_accept"        — deterministic near-verbatim accept.
      "verifier_accept"     — LLM verifier confirmed support.
      "verifier_reject"     — LLM verifier rejected support or failed.
    """
    if not isinstance(claim, dict):
        return None, "invalid"

    claim_text = _clean_string(claim.get("claim_text"))
    claim_type = _clean_string(claim.get("claim_type"))
    evidence_span = _clean_string(claim.get("evidence_span"))
    entities = claim.get("entities")
    confidence = _validated_confidence(claim.get("confidence"))

    if not claim_text or claim_type not in CLAIM_TYPES:
        return None, "invalid"
    if not isinstance(entities, list):
        return None, "invalid"
    if not all(isinstance(entity, str) and entity.strip() for entity in entities):
        return None, "invalid"
    if not evidence_span or not _evidence_in_content(evidence_span, content):
        return None, "invalid"
    if confidence is None:
        return None, "invalid"

    cleaned_entities = [entity.strip() for entity in entities]
    derivability = _derivability_check(claim_text, evidence_span, cleaned_entities)
    if derivability == "reject":
        return None, "derivability_reject"
    if derivability == "uncertain":
        if not verify_claim(claim_text, evidence_span):
            return None, "verifier_reject"
        decision = "verifier_accept"
    else:
        decision = "cheap_accept"

    return {
        "claim_text": claim_text,
        "claim_type": claim_type,
        "entities": cleaned_entities,
        "evidence_span": evidence_span,
        "confidence": confidence,
    }, decision
