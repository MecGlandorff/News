from __future__ import annotations


JsonObject = dict[str, object]


def _string_array() -> JsonObject:
    return {
        "type": "array",
        "items": {"type": "string"},
    }


def decision_response_keys(decision_count: int) -> list[str]:
    if decision_count < 1:
        raise ValueError("decision_count must be at least 1")
    return [f"case_{index + 1}" for index in range(decision_count)]


def _strict_keyed_response(
    *,
    name: str,
    item_properties: JsonObject,
    required: list[str],
    decision_count: int,
) -> JsonObject:
    response_keys = decision_response_keys(decision_count)
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "decisions": {
                        "type": "object",
                        "properties": {
                            response_key: {"$ref": "#/$defs/decision"}
                            for response_key in response_keys
                        },
                        "required": response_keys,
                        "additionalProperties": False,
                    }
                },
                "required": ["decisions"],
                "additionalProperties": False,
                "$defs": {
                    "decision": {
                        "type": "object",
                        "properties": item_properties,
                        "required": required,
                        "additionalProperties": False,
                    }
                },
            },
        },
    }


def _story_decision_response_format(
    *,
    name: str,
    decision_count: int,
) -> JsonObject:
    return _strict_keyed_response(
        name=name,
        item_properties={
            "same_story": {"type": "boolean"},
            "relationship": {
                "type": "string",
                "enum": [
                    "same_event",
                    "direct_continuation",
                    "related_context",
                    "unrelated",
                    "uncertain",
                ],
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
            },
            "shared_anchors": _string_array(),
            "conflicts": _string_array(),
            "reject_reason": {"type": "string"},
        },
        required=[
            "same_story",
            "relationship",
            "confidence",
            "shared_anchors",
            "conflicts",
            "reject_reason",
        ],
        decision_count=decision_count,
    )


def same_day_decision_response_format(decision_count: int) -> JsonObject:
    return _story_decision_response_format(
        name="same_day_match_decisions",
        decision_count=decision_count,
    )


def cross_day_decision_response_format(decision_count: int) -> JsonObject:
    return _story_decision_response_format(
        name="cross_day_story_match_decisions",
        decision_count=decision_count,
    )


def arc_decision_response_format(decision_count: int) -> JsonObject:
    return _strict_keyed_response(
        name="story_arc_match_decisions",
        item_properties={
            "belongs_to_arc": {"type": "boolean"},
            "container_type": {
                "type": "string",
                "enum": [
                    "named_event",
                    "recurring_format",
                    "broad_topic",
                    "uncertain",
                ],
            },
            "relationship": {
                "type": "string",
                "enum": [
                    "same_arc",
                    "parent_context",
                    "related_context",
                    "unrelated",
                    "uncertain",
                ],
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
            },
            "shared_anchors": _string_array(),
            "conflicts": _string_array(),
            "parent_story_id": {
                "anyOf": [
                    {"type": "integer"},
                    {"type": "null"},
                ]
            },
            "proposed_arc_label": {"type": "string"},
            "reject_reason": {"type": "string"},
        },
        required=[
            "belongs_to_arc",
            "container_type",
            "relationship",
            "confidence",
            "shared_anchors",
            "conflicts",
            "parent_story_id",
            "proposed_arc_label",
            "reject_reason",
        ],
        decision_count=decision_count,
    )


def decisions_by_case_id(
    raw_decisions: object,
    case_ids: list[str],
) -> tuple[dict[str, JsonObject], bool]:
    """Bind keyed model decisions back to internal opaque case IDs."""
    response_keys = decision_response_keys(len(case_ids))
    if not isinstance(raw_decisions, dict):
        return {}, False
    decisions: dict[str, JsonObject] = {}
    for response_key, case_id in zip(response_keys, case_ids, strict=True):
        raw = raw_decisions.get(response_key)
        if isinstance(raw, dict):
            decisions[case_id] = {**raw, "case_id": case_id}
    complete = (
        set(raw_decisions) == set(response_keys)
        and len(decisions) == len(case_ids)
    )
    return decisions, complete
