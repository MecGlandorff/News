import json

from src.tracker.matching.same_day import group_today_articles
from tests.fakes import FakeLLMClient
from tests.tracker.support import _article


MODEL = "gpt-5.4-mini-2026-03-17"


def _with_occurrence(article, occurrence_id):
    return {**article, "occurrence_id": occurrence_id}


def _decision_payload(*decisions):
    return {"decisions": list(decisions)}


def _response_for_cases(*, same_story, relationship, anchors, conflicts=None):
    def payload(kwargs):
        request = json.loads(kwargs["messages"][1]["content"])
        return _decision_payload(
            *[
                {
                    "case_id": case["case_id"],
                    "same_story": same_story,
                    "relationship": relationship,
                    "confidence": "high",
                    "shared_anchors": anchors,
                    "conflicts": conflicts or [],
                    "reject_reason": "" if same_story else "Different concrete events.",
                }
                for case in request["cases"]
            ]
        )

    return payload


def test_identical_classifier_label_can_split_unrelated_articles():
    articles = [
        _with_occurrence(
            {
                **_article("a", "Liverpool signs a new striker", "Football transfers"),
                "description": "Liverpool completes a deal for a forward.",
            },
            1,
        ),
        _with_occurrence(
            {
                **_article("b", "Real Madrid goalkeeper transfer stalls", "Football transfers"),
                "description": "Madrid negotiations for a goalkeeper break down.",
            },
            2,
        ),
    ]
    client = FakeLLMClient(
        _response_for_cases(
            same_story=False,
            relationship="unrelated",
            anchors=[],
        )
    )

    groups, decisions = group_today_articles(
        articles,
        get_client=lambda: client,
        model=MODEL,
    )

    assert len(groups) == 2
    assert groups[0].label == groups[1].label == "Football transfers"
    assert groups[0].group_id != groups[1].group_id
    assert decisions[0]["accepted"] is False
    assert decisions[0]["decision_route"] == "mini"


def test_different_labels_merge_when_grounded_named_event_matches():
    articles = [
        _with_occurrence(
            {
                **_article("a", "OpenAI agent deleted user data", "AI agent behavior"),
                "description": "The OpenAI agent incident affected Acme Cloud.",
            },
            1,
        ),
        _with_occurrence(
            {
                **_article("b", "Acme Cloud investigates OpenAI agent incident", "AI cyberattack"),
                "description": "Acme Cloud says the OpenAI agent deleted data.",
            },
            2,
        ),
    ]
    client = FakeLLMClient(
        _response_for_cases(
            same_story=True,
            relationship="same_event",
            anchors=["OpenAI agent", "Acme Cloud"],
        )
    )

    groups, decisions = group_today_articles(
        articles,
        get_client=lambda: client,
        model=MODEL,
    )

    assert len(groups) == 1
    assert decisions[0]["accepted"] is True
    assert decisions[0]["continuity_evidence"] == ["OpenAI agent", "Acme Cloud"]


def test_exact_url_duplicate_is_deterministic_and_skips_model():
    left = _with_occurrence(_article("a", "Original title", "First label"), 1)
    right = _with_occurrence(
        {
            **_article("b", "Syndicated title", "Second label"),
            "url": left["url"],
        },
        2,
    )
    client = FakeLLMClient([])

    groups, decisions = group_today_articles(
        [left, right],
        get_client=lambda: client,
        model=MODEL,
    )

    assert len(groups) == 1
    assert client.calls == 0
    assert decisions[0]["decision_route"] == "deterministic"
    assert decisions[0]["accepted"] is True


def test_missing_model_case_fails_closed():
    articles = [
        _with_occurrence(_article("a", "Tour de France stage result", "Tour de France"), 1),
        _with_occurrence(_article("b", "Tour de France standings", "Tour de France"), 2),
    ]
    client = FakeLLMClient({"decisions": []})

    groups, decisions = group_today_articles(
        articles,
        get_client=lambda: client,
        model=MODEL,
    )

    assert len(groups) == 2
    assert decisions[0]["accepted"] is False
    assert decisions[0]["decision_route"] == "fail_closed"
    assert decisions[0]["ambiguity_reason"] == "invalid_or_missing_case"


def test_complete_link_blocks_bridge_merge():
    articles = [
        _with_occurrence(
            {
                **_article("a", "Alpha summit opens in Brussels", "Summit coverage"),
                "description": "Alpha summit delegates meet in Brussels.",
            },
            1,
        ),
        _with_occurrence(
            {
                **_article("b", "Alpha summit discusses Beta accord", "Summit coverage"),
                "description": "Alpha summit delegates debate the Beta accord.",
            },
            2,
        ),
        _with_occurrence(
            {
                **_article("c", "Beta accord hearing begins", "Summit coverage"),
                "description": "A separate Beta accord court hearing begins.",
            },
            3,
        ),
    ]

    def payload(kwargs):
        cases = json.loads(kwargs["messages"][1]["content"])["cases"]
        decisions = []
        for case in cases:
            titles = " ".join(case["left"]["titles"] + case["right"]["titles"])
            same_story = not (
                "Alpha summit opens" in titles and "Beta accord hearing" in titles
            )
            decisions.append(
                {
                    "case_id": case["case_id"],
                    "same_story": same_story,
                    "relationship": "same_event" if same_story else "unrelated",
                    "confidence": "high",
                    "shared_anchors": (
                        ["Alpha summit", "Brussels"]
                        if "Alpha summit opens" in titles
                        else ["Beta accord", "hearing"]
                    ),
                    "conflicts": [],
                    "reject_reason": "" if same_story else "Different events.",
                }
            )
        return {"decisions": decisions}

    groups, decisions = group_today_articles(
        articles,
        get_client=lambda: FakeLLMClient(payload),
        model=MODEL,
    )

    assert len(decisions) == 3
    assert len(groups) == 2
    assert sorted(len(group.articles) for group in groups) == [1, 2]


def test_same_day_call_uses_strict_schema_and_reasoning_effort():
    captured = []
    articles = [
        _with_occurrence(_article("a", "Tour de France stage", "Tour de France"), 1),
        _with_occurrence(_article("b", "Tour de France result", "Tour de France"), 2),
    ]
    client = FakeLLMClient(
        _response_for_cases(
            same_story=True,
            relationship="direct_continuation",
            anchors=["Tour de France"],
        ),
        capture=captured,
    )

    group_today_articles(
        articles,
        get_client=lambda: client,
        model=MODEL,
        reasoning_effort="low",
    )

    assert captured[0]["model"] == MODEL
    assert captured[0]["reasoning_effort"] == "low"
    assert captured[0]["response_format"]["type"] == "json_schema"
    assert captured[0]["response_format"]["json_schema"]["strict"] is True
