import pytest

from src.tracker.matching.schemas import (
    SAME_DAY_DECISION_RESPONSE_FORMAT,
    with_exact_decision_count,
)


def _decisions_schema(response_format):
    return response_format["json_schema"]["schema"]["properties"]["decisions"]


def test_exact_decision_count_constrains_copy_without_mutating_base():
    exact_format = with_exact_decision_count(
        SAME_DAY_DECISION_RESPONSE_FORMAT,
        3,
    )

    assert _decisions_schema(exact_format)["minItems"] == 3
    assert _decisions_schema(exact_format)["maxItems"] == 3
    assert "minItems" not in _decisions_schema(SAME_DAY_DECISION_RESPONSE_FORMAT)
    assert "maxItems" not in _decisions_schema(SAME_DAY_DECISION_RESPONSE_FORMAT)


def test_exact_decision_count_rejects_empty_batches():
    with pytest.raises(ValueError, match="at least 1"):
        with_exact_decision_count(SAME_DAY_DECISION_RESPONSE_FORMAT, 0)
