from copy import deepcopy

import pytest


@pytest.fixture
def snapshot():
    return {
        "day": "2026-10-01",
        "articles": [
            {
                "id": "bridge-1",
                "source": "Example News",
                "url": "https://example.test/bridge",
                "published_at": "2026-10-01T08:00:00Z",
                "title": "Brook bridge closes",
                "text": "The Brook bridge in Bergen closed after a truck collision on Thursday.",
            }
        ],
    }


@pytest.fixture
def fake_model(monkeypatch):
    """A structurally valid first observation; not a semantic model substitute."""
    calls = []

    def call(task, payload, directory, **kwargs):
        assert task == "trajectory"
        calls.append(deepcopy(payload))
        return {
            "stories": [
                {
                    "story_id": None,
                    "title": article["title"],
                    "events": [
                        {
                            "event_id": None,
                            "title": article["title"],
                            "identity_uncertain": False,
                            "continuity_evidence": [],
                            "observations": [
                                {
                                    "change": "new_development",
                                    "summary": article["text"],
                                    "unresolved": None,
                                    "article_ids": [article["id"]],
                                    "evidence": [
                                        {
                                            "capture_id": article["capture_id"],
                                            "quote": article["text"],
                                        }
                                    ],
                                    "comparison_evidence": [],
                                }
                            ],
                        }
                    ],
                }
                for article in payload["articles"]
            ]
        }

    monkeypatch.setattr("news.trajectory.run_task", call)
    return calls
