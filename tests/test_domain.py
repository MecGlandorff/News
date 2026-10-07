from copy import deepcopy

import pytest

from news.domain import validate_input


def test_input_is_copied_and_sorted(snapshot):
    original = deepcopy(snapshot)
    accepted = validate_input(snapshot)
    assert accepted == original
    accepted["articles"][0]["text"] = "changed"
    assert snapshot == original


@pytest.mark.parametrize(
    "field,value",
    [
        ("url", []),
        ("url", "https://:secret@example.test/a"),
        ("id", ""),
        ("source", "  "),
        ("title", []),
        ("text", ""),
        ("text", "x" * 20_001),
        ("text", "nul\x00character"),
        ("url", "javascript:alert(1)"),
        ("url", "https://user:password@example.test/a"),
        ("url", "https://example.test/bad url"),
        ("url", "https://example.test:wrong/a"),
        ("published_at", "2026-10-01T08:00:00"),
        ("published_at", "no date"),
        ("published_at", "2026-10-02T08:00:00Z"),
        ("published_at", None),
    ],
)
def test_input_rejects_invalid_values(snapshot, field, value):
    snapshot["articles"][0][field] = value
    with pytest.raises(ValueError):
        validate_input(snapshot)


@pytest.mark.parametrize("case", ["empty", "missing", "extra", "duplicate", "date", "too_many"])
def test_input_structure(snapshot, case):
    if case == "empty":
        snapshot["articles"] = []
    elif case == "missing":
        del snapshot["articles"][0]["text"]
    elif case == "extra":
        snapshot["memory"] = []
    elif case == "duplicate":
        snapshot["articles"].append(deepcopy(snapshot["articles"][0]))
    elif case == "date":
        snapshot["day"] = "20261001"
    else:
        snapshot["articles"] *= 51
    with pytest.raises(ValueError):
        validate_input(snapshot)


def test_day_uses_brussels_calendar(snapshot):
    snapshot["articles"][0]["published_at"] = "2026-10-01T23:00:00Z"
    with pytest.raises(ValueError):
        validate_input(snapshot)
    snapshot["day"] = "2026-10-02"
    validate_input(snapshot)
