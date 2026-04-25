import pytest

import src.article_cache as article_cache
import src.classifier as classifier
from src.classifier import classify_articles
from src.env import load_dotenv_file
import src.llm as llm
from src.llm import require_openai_api_key, parse_json_object


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

    class Message:
        content = '{"results":[{"id":"article-1","theme":"Economy","story_label":"Market Rally","importance":4}]}'

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

    client = Client()
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

    assert client.chat.completions.calls == 1
    assert first == second
    assert second[0]["theme"] == "Economy"
    assert second[0]["story_label"] == "Market Rally"
    assert second[0]["importance"] == 4


def test_classify_articles_reclassifies_when_content_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(article_cache, "DB_PATH", tmp_path / "stories.db")

    class Completions:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            label = f"Story {self.calls}"

            class Message:
                content = (
                    '{"results":[{"id":"article-1","theme":"Economy",'
                    f'"story_label":"{label}","importance":3}}]'
                    '}'
                )

            class Choice:
                message = Message()

            class Response:
                choices = [Choice()]

            return Response()

    class Chat:
        def __init__(self):
            self.completions = Completions()

    class Client:
        def __init__(self):
            self.chat = Chat()

    client = Client()
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

    assert client.chat.completions.calls == 2
    assert result[0]["story_label"] == "Story 2"
