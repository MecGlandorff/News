from src.tracker.matching.gate import (
    grounded_shared_anchors,
    has_sufficient_shared_anchors,
)
from src.tracker.matching.profiles import profile_from_articles
from tests.tracker.support import _article


def test_gate_grounds_reviewed_cross_language_anchor_families():
    current = profile_from_articles(
        [
            {
                **_article(
                    1,
                    "Wijst Frankrijk de weg naar een telefoonvrije jeugd?",
                    "Phone Free Youth",
                ),
            }
        ]
    )
    candidate = profile_from_articles(
        [
            {
                **_article(
                    2,
                    "France introduces phone restrictions for children",
                    "France Social Media Ban",
                ),
                "description": "French law protects young people.",
            }
        ]
    )
    anchors = ["France", "phone-free youth"]

    assert grounded_shared_anchors(anchors, current, candidate) == anchors
    assert has_sufficient_shared_anchors(anchors, current, candidate) is True


def test_gate_grounds_reviewed_cross_language_event_phrase():
    current = profile_from_articles(
        [
            _article(
                1,
                "Was de AI-agent op hol geslagen?",
                "AI Agent Behavior",
            )
        ]
    )
    candidate = profile_from_articles(
        [
            _article(
                2,
                "OpenAI says its AI went rogue in a cyberattack",
                "AI Cyberattack",
            )
        ]
    )
    anchors = ["AI", "op hol geslagen"]

    assert grounded_shared_anchors(anchors, current, candidate) == anchors
    assert has_sufficient_shared_anchors(anchors, current, candidate) is True
