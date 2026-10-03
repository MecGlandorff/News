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
def decision(snapshot):
    article = snapshot["articles"][0]
    return {
        "events": [
            {
                "title": article["title"],
                "previous_event_id": None,
                "article_ids": [article["id"]],
                "evidence": [{"article_id": article["id"], "quote": article["text"]}],
            }
        ]
    }


@pytest.fixture
def fake_model(monkeypatch):
    calls = []

    def call(task, payload, directory, **kwargs):
        calls.append(deepcopy(payload))
        return {
            "events": [
                {
                    "title": article["title"],
                    "previous_event_id": payload["memory"][0]["id"] if payload["memory"] else None,
                    "article_ids": [article["id"]],
                    "evidence": [{"article_id": article["id"], "quote": article["text"]}],
                }
                for article in payload["articles"]
            ]
        }

    monkeypatch.setattr("news.pipeline.run_task", call)
    return calls
