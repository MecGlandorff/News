import pytest

from src.tracker.matching.schemas import (
    arc_decision_response_format,
    cross_day_decision_response_format,
    decision_response_keys,
    decisions_by_case_id,
    same_day_decision_response_format,
)


STORY_DECISION_FIELDS = {
    "same_story",
    "relationship",
    "confidence",
    "shared_anchors",
    "conflicts",
    "reject_reason",
}
ARC_DECISION_FIELDS = {
    "belongs_to_arc",
    "container_type",
    "relationship",
    "confidence",
    "shared_anchors",
    "conflicts",
    "parent_story_id",
    "proposed_arc_label",
    "reject_reason",
}


def _decisions_schema(response_format):
    return response_format["json_schema"]["schema"]["properties"]["decisions"]


def test_keyed_decisions_require_every_stable_response_key():
    keyed_format = same_day_decision_response_format(3)
    root_schema = keyed_format["json_schema"]["schema"]
    decisions_schema = _decisions_schema(keyed_format)

    assert decisions_schema["type"] == "object"
    assert decisions_schema["required"] == ["case_1", "case_2", "case_3"]
    assert set(decisions_schema["properties"]) == {"case_1", "case_2", "case_3"}
    assert decisions_schema["additionalProperties"] is False
    assert all(
        value == {"$ref": "#/$defs/decision"}
        for value in decisions_schema["properties"].values()
    )
    assert "case_id" not in root_schema["$defs"]["decision"]["required"]


@pytest.mark.parametrize(
    ("response_format", "expected_name", "required_fields"),
    [
        (
            same_day_decision_response_format,
            "same_day_match_decisions",
            STORY_DECISION_FIELDS,
        ),
        (
            cross_day_decision_response_format,
            "cross_day_story_match_decisions",
            STORY_DECISION_FIELDS,
        ),
        (
            arc_decision_response_format,
            "story_arc_match_decisions",
            ARC_DECISION_FIELDS,
        ),
    ],
)
def test_keyed_decision_formats_bind_their_domain_contract(
    response_format,
    expected_name,
    required_fields,
):
    keyed_format = response_format(1)
    json_schema = keyed_format["json_schema"]
    decision_schema = json_schema["schema"]["$defs"]["decision"]

    assert json_schema["name"] == expected_name
    assert set(decision_schema["required"]) == required_fields
    assert set(decision_schema["properties"]) == required_fields
    assert decision_schema["additionalProperties"] is False


def test_keyed_decision_formats_reject_empty_batches():
    with pytest.raises(ValueError, match="at least 1"):
        same_day_decision_response_format(0)


def test_keyed_decisions_bind_stable_keys_back_to_opaque_case_ids():
    decisions, complete = decisions_by_case_id(
        {
            "case_1": {"same_story": True},
            "case_2": {"same_story": False},
        },
        ["opaque::left", "opaque=>right"],
    )

    assert complete is True
    assert decisions["opaque::left"]["case_id"] == "opaque::left"
    assert decisions["opaque=>right"]["case_id"] == "opaque=>right"
    assert decision_response_keys(2) == ["case_1", "case_2"]


def test_keyed_decisions_reject_missing_or_extra_response_keys():
    decisions, complete = decisions_by_case_id(
        {
            "case_1": {"same_story": True},
            "invented": {"same_story": True},
        },
        ["first", "second"],
    )

    assert complete is False
    assert set(decisions) == {"first"}
