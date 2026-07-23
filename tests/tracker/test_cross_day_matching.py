import json

from src.tracker.matching.cross_day import match_story_groups
from tests.fakes import FakeLLMClient
from tests.tracker.support import _article


MODEL = "gpt-5.4-mini-2026-03-17"


def _story(story_id, label, title, *, description="", url=""):
    return {
        "story_id": story_id,
        "canonical_label": label,
        "last_seen": "2026-07-22",
        "first_seen": "2026-07-21",
        "active_days": 2,
        "theme": "World",
        "recent_articles": [
            {
                "title": title,
                "description": description,
                "url": url,
                "date": "2026-07-22",
            }
        ],
    }


def _payload(*, accepted, relationship, anchors):
    def response(kwargs):
        cases = json.loads(kwargs["messages"][1]["content"])["cases"]
        return {
            "decisions": {
                case["response_key"]: {
                    "same_story": accepted,
                    "relationship": relationship,
                    "confidence": "high",
                    "shared_anchors": anchors,
                    "conflicts": [],
                    "reject_reason": "" if accepted else "Different event.",
                }
                for case in cases
            }
        }

    return response


def test_cross_day_accepts_grounded_direct_continuation():
    article = {
        **_article(
            "new",
            "France advances phone-free youth plan",
            "Phone-free youth",
        ),
        "description": "France would bar social media for children under 15.",
    }
    recent = {
        "France social media ban": _story(
            7,
            "France social media ban",
            "France proposes social media ban for under-15s",
            description="The French government proposed the under-15 ban.",
        )
    }
    client = FakeLLMClient(
        _payload(
            accepted=True,
            relationship="direct_continuation",
            anchors=["France", "social media", "under 15"],
        )
    )

    label_map, decisions = match_story_groups(
        {"Phone-free youth"},
        recent,
        {"Phone-free youth": [article]},
        get_client=lambda: client,
        model=MODEL,
    )

    assert label_map == {"Phone-free youth": "France social media ban"}
    assert decisions[0]["accepted"] is True
    assert decisions[0]["decision_route"] == "mini"


def test_cross_day_accept_uses_two_grounded_headline_signals():
    article = {
        **_article(
            "new",
            "France youth phone restrictions explained",
            "Phone-free youth",
        ),
    }
    recent = {
        "France youth restrictions": _story(
            7,
            "France youth restrictions",
            "France introduces youth social-media restrictions",
        )
    }
    client = FakeLLMClient(
        _payload(
            accepted=True,
            relationship="direct_continuation",
            anchors=["France"],
        )
    )

    label_map, decisions = match_story_groups(
        {"Phone-free youth"},
        recent,
        {"Phone-free youth": [article]},
        get_client=lambda: client,
        model=MODEL,
    )

    assert label_map == {"Phone-free youth": "France youth restrictions"}
    assert decisions[0]["accepted"] is True
    assert {"france", "youth"} <= set(
        decisions[0]["continuity_evidence"]
    )


def test_cross_day_rejects_generic_bridge_despite_shared_label():
    current = {
        **_article(
            "new",
            "Tram crashes into Erasmus Bridge barrier",
            "Erasmus Bridge tram crash",
        ),
        "description": "A Rotterdam tram hit a barrier on Erasmus Bridge.",
    }
    recent = {
        "Bridge safety inspections": _story(
            8,
            "Bridge safety inspections",
            "Authorities inspect London bridge supports",
            description="Routine safety inspections began in London.",
        )
    }
    client = FakeLLMClient(
        _payload(
            accepted=False,
            relationship="related_context",
            anchors=[],
        )
    )

    label_map, decisions = match_story_groups(
        {"Erasmus Bridge tram crash"},
        recent,
        {"Erasmus Bridge tram crash": [current]},
        get_client=lambda: client,
        model=MODEL,
    )

    assert label_map == {"Erasmus Bridge tram crash": "NEW"}
    assert decisions == []
    assert client.calls == 0


def test_cross_day_fails_closed_when_multiple_candidates_are_accepted():
    article = {
        **_article("new", "Tour de France 2026 stage result", "Tour de France 2026"),
        "description": "The Tour de France 2026 stage changed the standings.",
    }
    recent = {
        "Tour de France standings": _story(
            1,
            "Tour de France standings",
            "Tour de France 2026 standings",
        ),
        "Tour de France stage": _story(
            2,
            "Tour de France stage",
            "Tour de France 2026 stage result",
        ),
    }
    client = FakeLLMClient(
        _payload(
            accepted=True,
            relationship="direct_continuation",
            anchors=["Tour de France 2026"],
        )
    )

    label_map, decisions = match_story_groups(
        {"Tour de France 2026"},
        recent,
        {"Tour de France 2026": [article]},
        get_client=lambda: client,
        model=MODEL,
    )

    assert label_map == {"Tour de France 2026": "NEW"}
    assert len(decisions) == 2
    assert all(not decision["accepted"] for decision in decisions)
    assert {
        decision["ambiguity_reason"] for decision in decisions
    } == {"multiple_accepted_candidates"}


def test_cross_day_uses_strict_schema_and_requested_effort():
    article = {
        **_article("new", "Iran Hormuz gas disruption", "Hormuz gas disruption"),
        "description": "Iranian action in Hormuz disrupted gas traffic.",
    }
    recent = {
        "Iran Hormuz crisis": _story(
            3,
            "Iran Hormuz crisis",
            "Iran tensions close Hormuz shipping lanes",
        )
    }
    captured = []
    client = FakeLLMClient(
        _payload(
            accepted=True,
            relationship="direct_continuation",
            anchors=["Iran", "Hormuz"],
        ),
        capture=captured,
    )

    match_story_groups(
        {"Hormuz gas disruption"},
        recent,
        {"Hormuz gas disruption": [article]},
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
    assert decisions_schema["type"] == "object"
    assert decisions_schema["required"] == ["case_1"]
    assert set(decisions_schema["properties"]) == {"case_1"}
