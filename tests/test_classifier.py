import json
import sqlite3

import pytest

import src.article_cache as article_cache
import src.classifier as classifier
from src.classifier import classify_articles
from src.env import load_dotenv_file
import src.llm as llm
from src.llm import require_openai_api_key, parse_json_object
from tests.fakes import FakeLLMClient


def _article(article_id, title="Story title", description="Story description"):
    return {
        "id": article_id,
        "source": "Example",
        "language": "en",
        "title": title,
        "description": description,
        "url": f"https://example.com/{article_id}",
        "published_at": "Sat, 18 Apr 2026 12:00:00 GMT",
        "text": "",
    }


def test_classify_handles_empty_articles():
    assert classify_articles([]) == []


def test_require_openai_api_key_explains_how_to_set_key(monkeypatch):
    monkeypatch.setattr(llm, "load_dotenv_file", lambda: None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="Add it to .env"):
        require_openai_api_key()


def test_load_dotenv_file_sets_missing_values(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY='from-file'\nEXISTING=from-file\n", encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("EXISTING", "from-env")

    load_dotenv_file(env_file)

    assert llm.has_openai_api_key()
    assert llm.os.environ["OPENAI_API_KEY"] == "from-file"
    assert llm.os.environ["EXISTING"] == "from-env"


def test_parse_json_object_rejects_non_object():
    class Message:
        content = "[]"

    class Choice:
        message = Message()

    class Response:
        choices = [Choice()]

    with pytest.raises(ValueError, match="JSON object"):
        parse_json_object(Response())


def test_classify_articles_caches_model_results(tmp_path, monkeypatch):
    monkeypatch.setattr(article_cache, "DB_PATH", tmp_path / "stories.db")

    client = FakeLLMClient({
        "results": [{
            "id": "article-1",
            "theme": "Economy",
            "story_label": "Market Rally",
            "importance": 4,
        }]
    })
    monkeypatch.setattr(classifier, "get_openai_client", lambda: client)

    article = {
        "id": "article-1",
        "source": "Example",
        "language": "en",
        "title": "Stocks rise",
        "description": "Markets move higher.",
        "url": "https://example.com/stocks",
        "published_at": "Sat, 18 Apr 2026 12:00:00 GMT",
        "text": "",
    }

    first = classify_articles([article])
    second = classify_articles([article])

    assert client.calls == 1
    assert first == second
    assert second[0]["theme"] == "Economy"
    assert second[0]["story_label"] == "Market Rally"
    assert second[0]["importance"] == 4


def test_classify_articles_bounds_initial_batches_and_text(tmp_path, monkeypatch):
    monkeypatch.setattr(article_cache, "DB_PATH", tmp_path / "stories.db")
    captured = []

    def classify_batch(kwargs):
        items = json.loads(kwargs["messages"][1]["content"])
        return {
            "results": [
                {
                    "id": item["id"],
                    "theme": "Other",
                    "story_label": f"Story {item['id']}",
                    "importance": 2,
                }
                for item in items
            ]
        }

    client = FakeLLMClient(classify_batch, capture=captured)
    monkeypatch.setattr(classifier, "get_openai_client", lambda: client)
    articles = [
        _article(f"article-{index}", "T" * 500, "D" * 2000)
        for index in range(51)
    ]

    result = classify_articles(articles)

    batches = [json.loads(call["messages"][1]["content"]) for call in captured]
    assert [len(batch) for batch in batches] == [50, 1]
    assert len(batches[0][0]["title"]) <= 301
    assert len(batches[0][0]["description"]) <= 1501
    assert len(result) == 51


def test_classify_articles_retries_omitted_article_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(article_cache, "DB_PATH", tmp_path / "stories.db")
    captured = []

    client = FakeLLMClient([
        {
            "results": [
                {
                    "id": "article-1",
                    "theme": "Economy",
                    "story_label": "Market Rally",
                    "importance": 4,
                },
                {
                    "id": "article-2",
                    "theme": "Other",
                    "story_label": "Uncategorized",
                    "importance": 1,
                },
            ]
        },
        {
            "results": [{
                "id": "article-2",
                "theme": "Tech",
                "story_label": "AI Earnings",
                "importance": 3,
            }]
        },
    ], capture=captured)
    monkeypatch.setattr(classifier, "get_openai_client", lambda: client)

    result = classify_articles([
        _article("article-1", "Stocks rise", "Markets move higher."),
        _article("article-2", "AI company reports earnings", "Revenue rises."),
    ])

    assert [item["story_label"] for item in result] == ["Market Rally", "AI Earnings"]
    captured_batches = [
        json.loads(call["messages"][1]["content"])
        for call in captured
    ]
    assert [[item["id"] for item in batch] for batch in captured_batches] == [
        ["article-1", "article-2"],
        ["article-2"],
    ]

    conn = sqlite3.connect(tmp_path / "stories.db")
    try:
        cached_count = conn.execute("SELECT COUNT(*) FROM article_classifications").fetchone()[0]
    finally:
        conn.close()
    assert cached_count == 2


def test_classify_articles_fails_when_retry_still_omits_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(article_cache, "DB_PATH", tmp_path / "stories.db")

    client = FakeLLMClient([
        {
            "results": [{
                "id": "article-1",
                "theme": "Economy",
                "story_label": "Market Rally",
                "importance": 4,
            }]
        },
        {"results": []},
    ])
    monkeypatch.setattr(classifier, "get_openai_client", lambda: client)

    with pytest.raises(ValueError, match="Classifier omitted classifications"):
        classify_articles([
            _article("article-1", "Stocks rise", "Markets move higher."),
            _article("article-2", "AI company reports earnings", "Revenue rises."),
        ])

    conn = sqlite3.connect(tmp_path / "stories.db")
    try:
        cached_count = conn.execute("SELECT COUNT(*) FROM article_classifications").fetchone()[0]
    finally:
        conn.close()
    assert cached_count == 0


def test_classify_articles_reclassifies_when_content_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(article_cache, "DB_PATH", tmp_path / "stories.db")

    counter = {"calls": 0}

    def dynamic_payload(kwargs):
        counter["calls"] += 1
        return {
            "results": [{
                "id": "article-1",
                "theme": "Economy",
                "story_label": f"Story {counter['calls']}",
                "importance": 3,
            }]
        }

    client = FakeLLMClient(dynamic_payload)
    monkeypatch.setattr(classifier, "get_openai_client", lambda: client)

    article = {
        "id": "article-1",
        "source": "Example",
        "language": "en",
        "title": "Stocks rise",
        "description": "Markets move higher.",
        "url": "https://example.com/stocks",
        "published_at": "Sat, 18 Apr 2026 12:00:00 GMT",
        "text": "",
    }

    changed = {**article, "description": "Markets fall sharply."}

    classify_articles([article])
    result = classify_articles([changed])

    assert client.calls == 2
    assert result[0]["story_label"] == "Story 2"
