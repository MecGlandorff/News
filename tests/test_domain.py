from copy import deepcopy

import pytest

from news.domain import render, validate_input, validate_result


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


@pytest.mark.parametrize(
    "case",
    [
        "omission",
        "unknown_article",
        "duplicate_member",
        "duplicate_event",
        "no_evidence",
        "other_source",
        "invented_quote",
        "empty_quote",
        "duplicate_quote",
        "unknown_memory",
        "extra_field",
        "blank_title",
        "giant_title",
        "control_title",
        "extra_top_level",
    ],
)
def test_model_failures_are_rejected(snapshot, decision, case):
    event = decision["events"][0]
    if case == "omission":
        decision["events"] = []
    elif case == "unknown_article":
        event["article_ids"] = ["unknown"]
    elif case == "duplicate_member":
        event["article_ids"] *= 2
    elif case == "duplicate_event":
        decision["events"] *= 2
    elif case == "no_evidence":
        event["evidence"] = []
    elif case == "other_source":
        event["evidence"][0]["article_id"] = "unknown"
    elif case == "invented_quote":
        event["evidence"][0]["quote"] = "The bridge is safe."
    elif case == "empty_quote":
        event["evidence"][0]["quote"] = " "
    elif case == "duplicate_quote":
        event["evidence"] *= 2
    elif case == "unknown_memory":
        event["previous_event_id"] = "invented"
    elif case == "extra_field":
        event["confidence"] = "certain"
    elif case == "blank_title":
        event["title"] = " \n "
    elif case == "giant_title":
        event["title"] = "x" * 181
    elif case == "control_title":
        event["title"] = "hello\x00world"
    else:
        decision["claims"] = []
    with pytest.raises(ValueError):
        validate_result(dict(snapshot, memory=[]), decision)


def test_one_previous_event_cannot_be_split_across_current_events(snapshot, decision):
    other = deepcopy(snapshot["articles"][0])
    other.update(id="b", url="https://example.test/b")
    snapshot["articles"].append(other)
    event = deepcopy(decision["events"][0])
    event.update(article_ids=["b"], previous_event_id="old")
    event["evidence"][0]["article_id"] = "b"
    decision["events"][0]["previous_event_id"] = "old"
    decision["events"].append(event)
    with pytest.raises(ValueError, match="multiply"):
        validate_result(dict(snapshot, memory=[{"id": "old"}]), decision)


def test_renderer_escapes_untrusted_markup():
    result = {
        "day": "2026-10-01",
        "events": [
            {
                "title": "<script>alert(1)</script>\n# next heading",
                "previous_event_id": None,
                "first_seen": "2026-10-01",
                "new_quote_count": 1,
                "evidence": [
                    {
                        "article_id": "x",
                        "quote": "[click](javascript:alert(1))\n# title",
                        "source": "<img src=x>",
                        "url": "https://example.test/(link)",
                        "published_at": "2026-10-01T08:00:00Z",
                    }
                ],
            }
        ],
    }
    output = render(result)
    assert "<script>" not in output
    assert "<img" not in output
    assert "\n# next" not in output
    assert "javascript:alert" in output  # Quoted text remains inspectable, but not a link.
    assert "\\[click\\]" in output
    assert "%28link%29" in output
