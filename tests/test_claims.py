import json
import sqlite3
import pytest

import src.claims as claims_module
from src.claims import extract_and_save_claims, get_claims_for_story


ARTICLE = {
    "id": "article-abc123",
    "story_id": 42,
    "source": "Reuters",
    "title": "Iran offers uranium deal",
    "description": "Iran proposed capping enrichment at 3.67%. Officials confirmed the offer.",
    "url": "https://reuters.com/iran",
    "published_at": "Fri, 1 May 2026 12:00:00 GMT",
}

CLAIM_RESPONSE = {
    "claims": [
        {
            "claim_text": "Iran proposed capping uranium enrichment at 3.67%.",
            "claim_type": "number",
            "entities": ["Iran"],
            "evidence_span": "Iran proposed capping enrichment at 3.67%.",
            "confidence": 0.95,
        },
        {
            "claim_text": "Officials confirmed the offer.",
            "claim_type": "fact",
            "entities": [],
            "evidence_span": "Officials confirmed the offer.",
            "confidence": 0.8,
        },
    ]
}


def _fake_client(response_content):
    class Message:
        content = json.dumps(response_content)

    class Choice:
        message = Message()

    class Response:
        choices = [Choice()]

    class Completions:
        calls = 0

        def create(self, **kwargs):
            self.calls += 1
            return Response()

    class Chat:
        def __init__(self):
            self.completions = Completions()

    class Client:
        def __init__(self):
            self.chat = Chat()

    return Client()


def test_extract_and_save_claims_skips_empty_tracked():
    # Should not raise and not call LLM
    extract_and_save_claims([])


def test_extract_saves_claims_and_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(claims_module, "DB_PATH", tmp_path / "stories.db")

    client = _fake_client(CLAIM_RESPONSE)
    monkeypatch.setattr(claims_module, "get_openai_client", lambda: client)

    extract_and_save_claims([ARTICLE])

    assert client.chat.completions.calls == 1
    saved = get_claims_for_story(42)
    assert len(saved) == 2
    assert saved[0]["claim_type"] == "number"
    assert "3.67%" in saved[0]["evidence_span"]


def test_extract_skips_already_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(claims_module, "DB_PATH", tmp_path / "stories.db")

    client = _fake_client(CLAIM_RESPONSE)
    monkeypatch.setattr(claims_module, "get_openai_client", lambda: client)

    extract_and_save_claims([ARTICLE])
    extract_and_save_claims([ARTICLE])  # second call — should hit cache

    assert client.chat.completions.calls == 1


def test_extract_caches_zero_claim_results(tmp_path, monkeypatch):
    monkeypatch.setattr(claims_module, "DB_PATH", tmp_path / "stories.db")

    client = _fake_client({"claims": []})
    monkeypatch.setattr(claims_module, "get_openai_client", lambda: client)

    extract_and_save_claims([ARTICLE])
    extract_and_save_claims([ARTICLE])

    assert client.chat.completions.calls == 1
    assert get_claims_for_story(42) == []


def test_extract_rejects_invalid_or_ungrounded_claims(tmp_path, monkeypatch):
    monkeypatch.setattr(claims_module, "DB_PATH", tmp_path / "stories.db")

    response = {
        "claims": [
            {
                "claim_text": "Officials confirmed the offer.",
                "claim_type": "fact",
                "entities": [],
                "evidence_span": "Officials confirmed the offer.",
                "confidence": 0.8,
            },
            {
                "claim_text": "Iran proposed a deal.",
                "claim_type": "rumor",
                "entities": ["Iran"],
                "evidence_span": "Iran proposed capping enrichment at 3.67%.",
                "confidence": 0.7,
            },
            {
                "claim_text": "Iran proposed a deal.",
                "claim_type": "fact",
                "entities": ["Iran"],
                "evidence_span": "",
                "confidence": 0.7,
            },
            {
                "claim_text": "Iran signed a final agreement.",
                "claim_type": "fact",
                "entities": ["Iran"],
                "evidence_span": "Iran signed a final agreement.",
                "confidence": 0.7,
            },
            {
                "claim_text": "Iran proposed a deal.",
                "claim_type": "fact",
                "entities": ["Iran"],
                "evidence_span": "Iran proposed capping enrichment at 3.67%.",
                "confidence": "high",
            },
            {
                "claim_text": "Iran proposed a deal.",
                "claim_type": "fact",
                "entities": "Iran",
                "evidence_span": "Iran proposed capping enrichment at 3.67%.",
                "confidence": 0.7,
            },
        ]
    }
    client = _fake_client(response)
    monkeypatch.setattr(claims_module, "get_openai_client", lambda: client)

    extract_and_save_claims([ARTICLE])

    saved = get_claims_for_story(42)
    assert len(saved) == 1
    assert saved[0]["claim_text"] == "Officials confirmed the offer."
    assert saved[0]["evidence_span"] == "Officials confirmed the offer."


def test_extract_does_not_cache_schema_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(claims_module, "DB_PATH", tmp_path / "stories.db")

    client = _fake_client({"claims": {"claim_text": "not a list"}})
    monkeypatch.setattr(claims_module, "get_openai_client", lambda: client)

    extract_and_save_claims([ARTICLE])
    extract_and_save_claims([ARTICLE])

    assert client.chat.completions.calls == 2
    assert get_claims_for_story(42) == []


def test_get_claims_for_story_ignores_old_prompt_versions(tmp_path, monkeypatch):
    monkeypatch.setattr(claims_module, "DB_PATH", tmp_path / "stories.db")

    client = _fake_client(CLAIM_RESPONSE)
    monkeypatch.setattr(claims_module, "get_openai_client", lambda: client)
    extract_and_save_claims([ARTICLE])

    conn = sqlite3.connect(tmp_path / "stories.db")
    conn.execute(
        """
        INSERT INTO claims (
            article_id, story_id, claim_text, claim_type, entities,
            evidence_span, confidence, prompt_version
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ARTICLE["id"],
            ARTICLE["story_id"],
            "Old cached claim.",
            "fact",
            "[]",
            "Old cached evidence.",
            0.99,
            "old-version",
        ),
    )
    conn.commit()
    conn.close()

    saved = get_claims_for_story(42)
    assert len(saved) == 2
    assert "Old cached claim." not in [claim["claim_text"] for claim in saved]


def test_cached_claims_follow_story_reassignment(tmp_path, monkeypatch):
    monkeypatch.setattr(claims_module, "DB_PATH", tmp_path / "stories.db")

    client = _fake_client(CLAIM_RESPONSE)
    monkeypatch.setattr(claims_module, "get_openai_client", lambda: client)

    extract_and_save_claims([ARTICLE])
    extract_and_save_claims([{**ARTICLE, "story_id": 84}])

    assert client.chat.completions.calls == 1
    assert get_claims_for_story(42) == []
    assert len(get_claims_for_story(84)) == 2


def test_content_change_invalidates_stale_claims_before_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(claims_module, "DB_PATH", tmp_path / "stories.db")

    client = _fake_client(CLAIM_RESPONSE)
    monkeypatch.setattr(claims_module, "get_openai_client", lambda: client)
    extract_and_save_claims([ARTICLE])
    assert len(get_claims_for_story(42)) == 2

    class Completions:
        def create(self, **kwargs):
            raise RuntimeError("LLM down")

    class Chat:
        completions = Completions()

    class Client:
        chat = Chat()

    monkeypatch.setattr(claims_module, "get_openai_client", lambda: Client())
    extract_and_save_claims([{**ARTICLE, "description": "Updated article text."}])

    assert get_claims_for_story(42) == []


def test_extract_handles_llm_failure_gracefully(tmp_path, monkeypatch):
    monkeypatch.setattr(claims_module, "DB_PATH", tmp_path / "stories.db")

    def boom(**kwargs):
        raise RuntimeError("LLM down")

    class Completions:
        def create(self, **kwargs):
            boom()

    class Chat:
        completions = Completions()

    class Client:
        chat = Chat()

    monkeypatch.setattr(claims_module, "get_openai_client", lambda: Client())

    # Should not raise — failure is logged and skipped
    extract_and_save_claims([ARTICLE])

    assert get_claims_for_story(42) == []


def test_get_claims_for_story_returns_empty_for_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(claims_module, "DB_PATH", tmp_path / "stories.db")
    assert get_claims_for_story(9999) == []


def test_extract_strips_html_from_description(tmp_path, monkeypatch):
    monkeypatch.setattr(claims_module, "DB_PATH", tmp_path / "stories.db")

    captured_content = {}

    class Completions:
        def create(self, **kwargs):
            captured_content["user"] = kwargs["messages"][1]["content"]

            class Message:
                content = json.dumps({"claims": []})

            class Choice:
                message = Message()

            class Response:
                choices = [Choice()]

            return Response()

    class Chat:
        completions = Completions()

    class Client:
        chat = Chat()

    monkeypatch.setattr(claims_module, "get_openai_client", lambda: Client())

    html_article = {
        **ARTICLE,
        "id": "html-article",
        "description": "<p>Iran <b>offered</b> a deal.</p>",
    }
    extract_and_save_claims([html_article])

    assert "<p>" not in captured_content["user"]
    assert "<b>" not in captured_content["user"]
    assert "Iran" in captured_content["user"]
