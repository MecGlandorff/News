import sqlite3

import pytest

import src.article_cache as article_cache
import src.classifier as classifier
import src.observability as observability
from src.classifier import classify_articles
from src.llm import create_chat_completion, parse_json_object
from tests.fakes import FakeLLMClient, FakeUsage
from tests.observability.support import _row, _run_args


def test_llm_call_records_usage_tokens(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    monkeypatch.setattr(observability, "DB_PATH", db_path)
    run_id = observability.start_run(_run_args(), run_date="2026-05-07")
    observability.set_current_run_id(run_id)

    try:
        response = create_chat_completion(
            FakeLLMClient({"ok": True}, usage=FakeUsage(prompt_tokens=11, completion_tokens=5)),
            model="test-model",
            messages=[{"role": "user", "content": "test"}],
            purpose="test",
            prompt_version="v1",
            response_format={"type": "json_object"},
        )
        assert parse_json_object(response) == {"ok": True}
        observability.finish_run(run_id, status="ok")
    finally:
        observability.clear_current_run_id()

    call = _row(db_path, "SELECT * FROM llm_calls WHERE run_id = ?", (run_id,))
    run = _row(db_path, "SELECT llm_calls_count, prompt_tokens, completion_tokens FROM runs WHERE run_id = ?", (run_id,))
    assert call["model"] == "test-model"
    assert call["purpose"] == "test"
    assert call["prompt_version"] == "v1"
    assert call["prompt_tokens"] == 11
    assert call["completion_tokens"] == 5
    assert run == {"llm_calls_count": 1, "prompt_tokens": 11, "completion_tokens": 5}


def test_schema_failure_marks_call_and_run(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    monkeypatch.setattr(observability, "DB_PATH", db_path)
    run_id = observability.start_run(_run_args(), run_date="2026-05-07")
    observability.set_current_run_id(run_id)

    try:
        response = create_chat_completion(
            FakeLLMClient("not json"),
            model="test-model",
            messages=[{"role": "user", "content": "test"}],
            purpose="test",
            response_format={"type": "json_object"},
        )
        with pytest.raises(ValueError, match="invalid JSON"):
            parse_json_object(response)
        observability.finish_run(run_id, status="ok")
    finally:
        observability.clear_current_run_id()

    call = _row(db_path, "SELECT schema_failure, error_type FROM llm_calls WHERE run_id = ?", (run_id,))
    run = _row(db_path, "SELECT llm_errors_count, schema_failures FROM runs WHERE run_id = ?", (run_id,))
    assert call == {"schema_failure": 1, "error_type": "schema"}
    assert run == {"llm_errors_count": 1, "schema_failures": 1}


def test_provider_error_is_visible_in_run_totals(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    monkeypatch.setattr(observability, "DB_PATH", db_path)
    run_id = observability.start_run(_run_args(), run_date="2026-05-07")
    observability.set_current_run_id(run_id)

    def raise_provider_error(kwargs):
        raise RuntimeError("provider down")

    try:
        with pytest.raises(RuntimeError, match="provider down"):
            create_chat_completion(
                FakeLLMClient(raise_provider_error),
                model="test-model",
                messages=[{"role": "user", "content": "test"}],
                purpose="test",
                response_format={"type": "json_object"},
            )
        observability.finish_run(run_id, status="ok")
    finally:
        observability.clear_current_run_id()

    call = _row(db_path, "SELECT error_type, error_message FROM llm_calls WHERE run_id = ?", (run_id,))
    run = _row(db_path, "SELECT llm_errors_count FROM runs WHERE run_id = ?", (run_id,))
    assert call == {"error_type": "RuntimeError", "error_message": "provider down"}
    assert run == {"llm_errors_count": 1}


def test_schema_failure_marks_the_failed_response_call(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    monkeypatch.setattr(observability, "DB_PATH", db_path)
    run_id = observability.start_run(_run_args(), run_date="2026-05-07")
    observability.set_current_run_id(run_id)

    try:
        client = FakeLLMClient(["not json", {"ok": True}])
        first = create_chat_completion(
            client,
            model="test-model",
            messages=[{"role": "user", "content": "first"}],
            purpose="first",
        )
        second = create_chat_completion(
            client,
            model="test-model",
            messages=[{"role": "user", "content": "second"}],
            purpose="second",
        )
        assert parse_json_object(second) == {"ok": True}
        with pytest.raises(ValueError, match="invalid JSON"):
            parse_json_object(first)
        observability.finish_run(run_id, status="ok")
    finally:
        observability.clear_current_run_id()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT purpose, schema_failure
                FROM llm_calls
                WHERE run_id = ?
                ORDER BY call_id
                """,
                (run_id,),
            )
        ]
    finally:
        conn.close()

    assert rows == [
        {"purpose": "first", "schema_failure": 1},
        {"purpose": "second", "schema_failure": 0},
    ]


def test_classification_cache_hits_are_run_totals_not_llm_calls(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    monkeypatch.setattr(article_cache, "DB_PATH", db_path)
    monkeypatch.setattr(observability, "DB_PATH", db_path)
    run_id = observability.start_run(_run_args(), run_date="2026-05-07")
    observability.set_current_run_id(run_id)

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

    try:
        classify_articles([article])
        classify_articles([article])
        observability.finish_run(run_id, status="ok")
    finally:
        observability.clear_current_run_id()

    run = _row(db_path, "SELECT llm_calls_count, llm_cache_hits FROM runs WHERE run_id = ?", (run_id,))
    calls = _row(db_path, "SELECT COUNT(*) AS count FROM llm_calls WHERE run_id = ?", (run_id,))
    assert client.calls == 1
    assert run == {"llm_calls_count": 1, "llm_cache_hits": 1}
    assert calls == {"count": 1}
