"""The decoding contract can enforce structure, not whether a story link is true."""

import json
from copy import deepcopy

import pytest

from news import trajectory
from news.domain import TASKS, validate_schema


def article(key, text):
    return trajectory.capture(
        {
            "id": key,
            "source": "Example News",
            "url": f"https://example.test/{key}",
            "published_at": "2026-01-01T08:00:00Z",
            "title": text,
            "text": text,
        },
        "2026-01-01",
    )


def reference(source):
    return {"capture_id": source["capture_id"], "quote": source["text"]}


def observation(source, change="new_development", comparison=()):
    return {
        "change": change,
        "summary": source["text"],
        "unresolved": None,
        "article_ids": [source["id"]],
        "evidence": [reference(source)],
        "comparison_evidence": list(comparison),
    }


@pytest.fixture
def current():
    return article("today", "The dock reopened.")


@pytest.fixture
def prior():
    return dict(article("prior", "The dock closed."), story_id="s-dock", event_id="e-closure")


def result(current, *, story_id=None, event_id=None, continuity=()):
    return {
        "stories": [
            {
                "story_id": story_id,
                "title": "Dock closure and reopening",
                "events": [
                    {
                        "event_id": event_id,
                        "title": "Dock reopened",
                        "identity_uncertain": False,
                        "continuity_evidence": list(continuity),
                        "observations": [observation(current)],
                    }
                ],
            }
        ]
    }


def payload(current, prior=None):
    return {
        "day": "2026-01-01",
        "articles": [current],
        "prior_sources": [prior] if prior else [],
        "stories": [{"id": prior["story_id"], "events": [{"id": prior["event_id"]}]}]
        if prior
        else [],
    }


def test_new_story_allows_new_event_without_prior_continuity(current):
    value = result(current)
    validate_schema("trajectory", value)
    trajectory.validate(payload(current), value)


@pytest.mark.parametrize("event_id", [None, "e-closure"])
def test_existing_story_requires_continuity_during_schema_validation(current, event_id):
    value = result(current, story_id="s-dock", event_id=event_id)
    with pytest.raises(ValueError, match="output does not match its schema"):
        validate_schema("trajectory", value)


def test_existing_story_can_contain_a_distinct_new_event_with_an_anchor(current, prior):
    value = result(current, story_id=prior["story_id"], continuity=[reference(prior)])
    assert value["stories"][0]["events"][0]["event_id"] is None
    validate_schema("trajectory", value)
    trajectory.validate(payload(current, prior), value)


@pytest.mark.parametrize("existing_story", [False, True])
@pytest.mark.parametrize("uncertain", [False, True])
def test_new_event_preserves_both_identity_judgments(current, prior, existing_story, uncertain):
    value = result(
        current,
        story_id=prior["story_id"] if existing_story else None,
        continuity=[reference(prior)] if existing_story else [],
    )
    value["stories"][0]["events"][0]["identity_uncertain"] = uncertain
    validate_schema("trajectory", value)
    trajectory.validate(payload(current, prior), value)


@pytest.mark.parametrize("uncertain", [False, True])
def test_existing_event_reuse_requires_a_certain_identity(current, prior, uncertain):
    value = result(
        current,
        story_id=prior["story_id"],
        event_id=prior["event_id"],
        continuity=[reference(prior)],
    )
    event = value["stories"][0]["events"][0]
    event["identity_uncertain"] = uncertain
    event["observations"] = [observation(current, "unclear")]
    if uncertain:
        with pytest.raises(ValueError, match="output does not match its schema"):
            validate_schema("trajectory", value)
    else:
        validate_schema("trajectory", value)
        trajectory.validate(payload(current, prior), value)


@pytest.mark.parametrize("event_id", [None, "e-closure"])
@pytest.mark.parametrize("violation", ["missing_uncertainty", "non_boolean", "extra_field"])
def test_each_continuing_event_branch_remains_closed_and_typed(current, prior, event_id, violation):
    value = result(
        current, story_id=prior["story_id"], event_id=event_id, continuity=[reference(prior)]
    )
    event = value["stories"][0]["events"][0]
    if violation == "missing_uncertainty":
        del event["identity_uncertain"]
    elif violation == "non_boolean":
        event["identity_uncertain"] = 0
    else:
        event["confidence"] = 1
    with pytest.raises(ValueError, match="output does not match its schema"):
        validate_schema("trajectory", value)


@pytest.mark.parametrize("violation", ["existing_event", "prior_continuity"])
def test_new_story_cannot_adopt_existing_event_or_prior_continuity(current, prior, violation):
    value = result(current)
    event = value["stories"][0]["events"][0]
    if violation == "existing_event":
        event["event_id"] = prior["event_id"]
    else:
        event["continuity_evidence"] = [reference(prior)]
    with pytest.raises(ValueError, match="output does not match its schema"):
        validate_schema("trajectory", value)


@pytest.mark.parametrize("field", ["story_id", "event_id"])
def test_existing_identifiers_cannot_be_empty_strings(current, prior, field):
    value = result(current, story_id=prior["story_id"], continuity=[reference(prior)])
    container = value["stories"][0]
    if field == "event_id":
        container = container["events"][0]
    container[field] = ""
    with pytest.raises(ValueError, match="output does not match its schema"):
        validate_schema("trajectory", value)


def test_every_event_in_existing_story_requires_its_own_anchor(current, prior):
    value = result(current, story_id=prior["story_id"], continuity=[reference(prior)])
    second = deepcopy(value["stories"][0]["events"][0])
    second["continuity_evidence"] = []
    value["stories"][0]["events"].append(second)
    with pytest.raises(ValueError, match="output does not match its schema"):
        validate_schema("trajectory", value)


def test_two_current_conflicting_reports_can_share_a_new_event():
    first = article("first", "Agency A reported ten injuries.")
    second = article("second", "Agency B reported two injuries.")
    value = result(first)
    value["stories"][0]["events"][0]["observations"].append(
        observation(second, "disagreement", [reference(first)])
    )
    supplied = payload(first)
    supplied["articles"].append(second)
    validate_schema("trajectory", value)
    trajectory.validate(supplied, value)


def test_correction_and_disagreement_can_share_an_existing_event(prior):
    correction = article("correction", "The agency corrects its report: the dock stayed open.")
    conflict = article("conflict", "Another agency continues to report that the dock closed.")
    value = result(
        correction,
        story_id=prior["story_id"],
        event_id=prior["event_id"],
        continuity=[reference(prior)],
    )
    value["stories"][0]["events"][0]["observations"] = [
        observation(correction, "correction", [reference(prior)]),
        observation(conflict, "disagreement", [reference(correction)]),
    ]
    supplied = payload(correction, prior)
    supplied["articles"].append(conflict)
    validate_schema("trajectory", value)
    trajectory.validate(supplied, value)


def test_structural_checks_do_not_detect_semantic_false_merge_or_placeholder_summary(current):
    # Deliberately wrong: source entailment still needs independent semantic
    # evaluation. A nonempty exact anchor is no guarantee of relevance.
    unrelated = dict(
        article("festival", "A music festival announced its performers."),
        story_id="s-festival",
        event_id="e-lineup",
    )
    value = result(current, story_id="s-festival", continuity=[reference(unrelated)])
    value["stories"][0]["title"] = "Music festival"
    value["stories"][0]["events"][0]["observations"][0]["summary"] = "Placeholder"
    validate_schema("trajectory", value)
    trajectory.validate(payload(current, unrelated), value)


def test_false_certainty_with_an_exact_anchor_is_still_not_semantic_proof(prior):
    unrelated = article("train", "A train arrived at the station.")
    value = result(
        unrelated,
        story_id=prior["story_id"],
        event_id=prior["event_id"],
        continuity=[reference(prior)],
    )
    event = value["stories"][0]["events"][0]
    event["observations"] = [observation(unrelated, "unclear")]
    # A false certainty flag and an exact dock quote still pass structural
    # validation. Source entailment and event relevance require semantic review.
    validate_schema("trajectory", value)
    trajectory.validate(payload(unrelated, prior), value)


def test_runtime_guard_still_checks_the_anchor_capture_and_exact_quote(current, prior):
    value = result(current, story_id=prior["story_id"], continuity=[reference(prior)])
    value["stories"][0]["events"][0]["continuity_evidence"][0]["quote"] = "Fabricated anchor"
    validate_schema("trajectory", value)
    with pytest.raises(ValueError, match="exact span"):
        trajectory.validate(payload(current, prior), value)


def test_schema_uses_the_documented_strict_output_object_and_composition_subset():
    schema = json.loads((TASKS / "trajectory.schema.json").read_text())
    assert schema["type"] == "object" and "anyOf" not in schema
    pending = [schema]
    while pending:
        item = pending.pop()
        if isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, dict):
            assert not {
                "allOf",
                "if",
                "then",
                "else",
                "not",
                "dependentRequired",
                "dependentSchemas",
            }.intersection(item)
            if item.get("type") == "object":
                assert item["additionalProperties"] is False
                assert set(item["required"]) == set(item["properties"])
            pending.extend(item.values())
