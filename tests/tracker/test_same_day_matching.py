import json

from src.tracker.matching.same_day import (
    SAME_DAY_CANDIDATES_PER_ARTICLE,
    group_today_articles,
    groups_as_story_mapping,
    same_day_candidate_edges,
)
from src.tracker.matching.profiles import profile_from_articles
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


def test_model_accept_can_use_two_grounded_cross_language_headline_signals():
    articles = [
        _with_occurrence(
            _article(
                "a",
                "Was de AI-agent op hol geslagen?",
                "AI agent behavior",
            ),
            1,
        ),
        _with_occurrence(
            _article(
                "b",
                "OpenAI says its AI went rogue in a cyberattack",
                "AI cyberattack",
            ),
            2,
        ),
    ]
    client = FakeLLMClient(
        _response_for_cases(
            same_story=True,
            relationship="same_event",
            anchors=["AI"],
        )
    )

    groups, decisions = group_today_articles(
        articles,
        get_client=lambda: client,
        model=MODEL,
    )

    assert len(groups) == 1
    assert decisions[0]["accepted"] is True
    assert {"ai", "rogue"} <= set(decisions[0]["continuity_evidence"])


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
    decisions_schema = captured[0]["response_format"]["json_schema"]["schema"][
        "properties"
    ]["decisions"]
    assert decisions_schema["minItems"] == 1
    assert decisions_schema["maxItems"] == 1


def test_mapping_disambiguates_split_identical_classifier_labels_with_titles():
    articles = [
        _with_occurrence(
            _article("a", "Liverpool signs striker", "Football transfers"),
            1,
        ),
        _with_occurrence(
            _article("b", "Madrid goalkeeper deal", "Football transfers"),
            2,
        ),
    ]
    groups, _ = group_today_articles(
        articles,
        get_client=lambda: FakeLLMClient(
            _response_for_cases(
                same_story=False,
                relationship="unrelated",
                anchors=[],
            )
        ),
        model=MODEL,
    )

    mapped = groups_as_story_mapping(groups)

    assert set(mapped) == {"Liverpool signs striker", "Madrid goalkeeper deal"}


def test_same_label_candidate_edges_are_capped_per_article():
    profiles = [
        profile_from_articles(
            [
                _with_occurrence(
                    _article(
                        str(index),
                        f"Transfer report number {index}",
                        "Football transfers",
                    ),
                    index,
                )
            ],
            profile_id=f"today:{index}",
        )
        for index in range(1, 16)
    ]

    edges = same_day_candidate_edges(profiles)

    assert len(edges) <= len(profiles) * SAME_DAY_CANDIDATES_PER_ARTICLE
