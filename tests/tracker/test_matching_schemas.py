import pytest

from src.tracker.matching.schemas import (
    SAME_DAY_DECISION_RESPONSE_FORMAT,
    decision_response_keys,
    decisions_by_case_id,
    keyed_decision_response_format,
)


def _decisions_schema(response_format):
    return response_format["json_schema"]["schema"]["properties"]["decisions"]


def test_keyed_decisions_require_every_stable_response_key_without_mutating_base():
    keyed_format = keyed_decision_response_format(
        SAME_DAY_DECISION_RESPONSE_FORMAT,
        3,
    )
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
    assert _decisions_schema(SAME_DAY_DECISION_RESPONSE_FORMAT)["type"] == "array"


def test_keyed_decision_format_rejects_empty_batches():
    with pytest.raises(ValueError, match="at least 1"):
        keyed_decision_response_format(SAME_DAY_DECISION_RESPONSE_FORMAT, 0)


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
