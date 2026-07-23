from __future__ import annotations

from copy import deepcopy
from typing import Any


def _string_array() -> dict:
    return {
        "type": "array",
        "items": {"type": "string"},
    }


def _strict_array_response(
    *,
    name: str,
    property_name: str,
    item_properties: dict,
    required: list[str],
) -> dict:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    property_name: {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": item_properties,
                            "required": required,
                            "additionalProperties": False,
                        },
                    }
                },
                "required": [property_name],
                "additionalProperties": False,
            },
        },
    }


def _story_decision_response_format(name: str) -> dict:
    return _strict_array_response(
        name=name,
        property_name="decisions",
        item_properties={
        "case_id": {"type": "string"},
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
            "case_id",
            "same_story",
            "relationship",
            "confidence",
            "shared_anchors",
            "conflicts",
            "reject_reason",
        ],
    )


def with_exact_decision_count(
    response_format: dict[str, Any],
    decision_count: int,
) -> dict[str, Any]:
    """Return a strict response format requiring one result per supplied case."""
    if decision_count < 1:
        raise ValueError("decision_count must be at least 1")
    exact_format = deepcopy(response_format)
    decisions = exact_format["json_schema"]["schema"]["properties"]["decisions"]
    decisions["minItems"] = decision_count
    decisions["maxItems"] = decision_count
    return exact_format


SAME_DAY_DECISION_RESPONSE_FORMAT = _story_decision_response_format(
    "same_day_match_decisions"
)

STORY_DECISION_RESPONSE_FORMAT = _story_decision_response_format(
    "cross_day_story_match_decisions"
)

ARC_DECISION_RESPONSE_FORMAT = _strict_array_response(
    name="story_arc_match_decisions",
    property_name="decisions",
    item_properties={
        "case_id": {"type": "string"},
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
        "case_id",
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
)
