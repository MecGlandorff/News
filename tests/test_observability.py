import json
import sqlite3
from types import SimpleNamespace

import pytest

import src.article_cache as article_cache
import src.classifier as classifier
from src.classifier import classify_articles
import src.observability as observability
from src.llm import create_chat_completion, parse_json_object


def _row(db_path, query, params=()):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return dict(conn.execute(query, params).fetchone())
    finally:
        conn.close()


def _run_args():
    return SimpleNamespace(today="2026-05-07", pipeline_report=True)


def test_run_lifecycle_records_success_totals(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    monkeypatch.setattr(observability, "DB_PATH", db_path)

    run_id = observability.start_run(_run_args(), run_date="2026-05-07")
    observability.update_run_totals(
        run_id,
        articles_returned=8,
        claims_saved=12,
        stories_touched=3,
    )
    observability.finish_run(run_id, status="ok")

    row = _row(db_path, "SELECT * FROM runs WHERE run_id = ?", (run_id,))
    assert row["status"] == "ok"
    assert row["articles_returned"] == 8
    assert row["claims_saved"] == 12
    assert row["stories_touched"] == 3
    assert row["finished_at"] is not None


def test_pipeline_report_includes_story_match_verifier_totals(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    monkeypatch.setattr(observability, "DB_PATH", db_path)

    run_id = observability.start_run(_run_args(), run_date="2026-05-07")
    observability.update_run_totals(
        run_id,
        story_match_verifications=6,
        story_match_accepts=4,
        story_match_rejections=2,
    )
    observability.finish_run(run_id, status="ok")

    report = observability.pipeline_report(run_id)

    assert "Story match checks:     6" in report
    assert "Story match accepted:   4" in report
    assert "Story match rejected:   2" in report


def test_pipeline_report_includes_story_development_totals(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    monkeypatch.setattr(observability, "DB_PATH", db_path)

    run_id = observability.start_run(_run_args(), run_date="2026-05-07")
    observability.update_run_totals(
        run_id,
        story_developments_saved=8,
        story_parent_attachments=3,
        story_new_parent_arcs=2,
        story_unmatched_new_stories=2,
    )
    observability.finish_run(run_id, status="ok")

    report = observability.pipeline_report(run_id)

    assert "Developments saved:     8" in report
    assert "Parent attachments:     3" in report
    assert "New parent arcs:        2" in report
    assert "Unmatched new stories:  2" in report


def test_pipeline_report_includes_scraper_claim_and_cost_totals(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    monkeypatch.setattr(observability, "DB_PATH", db_path)

    run_id = observability.start_run(_run_args(), run_date="2026-05-07")
    observability.update_run_totals(
        run_id,
        duplicate_url_skips=2,
        feed_fetch_failures=1,
        feed_items_outside_date_skipped=9,
        feed_items_missing_timestamp_skipped=3,
        feed_items_unparseable_timestamp_skipped=2,
        feed_items_missing_timestamp_included=4,
        feed_items_unparseable_timestamp_included=1,
        article_text_fetch_successes=7,
        article_text_fetch_failures=3,
        claim_articles_extracted=4,
        claim_articles_cached=5,
        claim_invalid_dropped=6,
        claim_extraction_failures=1,
        claim_zero_results=2,
    )
    observability.record_llm_call(
        run_id=run_id,
        model="gpt-5.4-nano",
        purpose="claim",
        usage={"prompt_tokens": 1000, "completion_tokens": 500},
        latency_ms=1200,
    )
    observability.finish_run(run_id, status="ok")

    report = observability.pipeline_report(run_id)

    assert "Duplicate URLs skipped: 2" in report
    assert "Feed fetch failures:    1" in report
    assert "Outside date skipped:   9" in report
    assert "Undated included:      5 (4 missing, 1 unparseable)" in report
    assert "Undated skipped:       5 (3 missing, 2 unparseable)" in report
    assert "Article text fetched:   7" in report
    assert "Article text failures:  3" in report
    assert "Claims extracted:       4" in report
    assert "Claims cached:          5" in report
    assert "Claims invalid:         6" in report
    assert "Claim failures:         1" in report
    assert "Zero-claim results:     2" in report
    assert "Estimated cost:         EUR 0.0007" in report
    assert "claim: 1 calls, tokens 1000/500, latency 1.2s, EUR 0.0007" in report


def test_write_run_report_artifact_outputs_markdown_overview(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    monkeypatch.setattr(observability, "DB_PATH", db_path)

    run_id = observability.start_run(_run_args(), run_date="2026-05-10")
    observability.update_run_totals(
        run_id,
        articles_returned=345,
        feed_fetch_failures=1,
        feed_items_outside_date_skipped=12,
        feed_items_missing_timestamp_included=2,
        feed_items_unparseable_timestamp_included=1,
        stories_touched=164,
        llm_cache_hits=4,
    )
    observability.record_llm_call(
        run_id=run_id,
        model="gpt-5.5",
        purpose="brief",
        usage={"prompt_tokens": 33200, "completion_tokens": 7365},
        latency_ms=145000,
    )
    observability.finish_run(run_id, status="ok")

    artifact = observability.write_run_report_artifact(
        run_id,
        output_dir=tmp_path / "run_artifacts",
    )

    assert artifact == tmp_path / "run_artifacts" / "run_2026-05-10.md"
    markdown = artifact.read_text(encoding="utf-8")
    assert "# Run Report: 2026-05-10" in markdown
    assert "| Articles returned | 345 |" in markdown
    assert "| Feed fetch failures | 1 |" in markdown
    assert "| Feed items outside date skipped | 12 |" in markdown
    assert "| Undated feed items included | 3 |" in markdown
    assert "| Stories touched | 164 |" in markdown
    assert "| LLM cache hits | 4 |" in markdown
    assert "| brief | 1 | 33,200 | 7,365 | 145.0s |" in markdown


def test_run_lifecycle_records_error_status(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    monkeypatch.setattr(observability, "DB_PATH", db_path)

    run_id = observability.start_run(_run_args(), run_date="2026-05-07")
    observability.finish_run(run_id, status="error", error_message="boom")

    row = _row(db_path, "SELECT status, error_message FROM runs WHERE run_id = ?", (run_id,))
    assert row == {"status": "error", "error_message": "boom"}


def test_llm_call_records_usage_tokens(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    monkeypatch.setattr(observability, "DB_PATH", db_path)
    run_id = observability.start_run(_run_args(), run_date="2026-05-07")
    observability.set_current_run_id(run_id)

    class Message:
        content = '{"ok": true}'

    class Choice:
        message = Message()

    class Usage:
        prompt_tokens = 11
        completion_tokens = 5

    class Response:
        choices = [Choice()]
        usage = Usage()

    class Completions:
        def create(self, **kwargs):
            return Response()

    class Chat:
        completions = Completions()

    class Client:
        chat = Chat()

    try:
        response = create_chat_completion(
            Client(),
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

    class Message:
        content = "not json"

    class Choice:
        message = Message()

    class Response:
        choices = [Choice()]

    class Completions:
        def create(self, **kwargs):
            return Response()

    class Chat:
        completions = Completions()

    class Client:
        chat = Chat()

    try:
        response = create_chat_completion(
            Client(),
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

    class Completions:
        def create(self, **kwargs):
            raise RuntimeError("provider down")

    class Chat:
        completions = Completions()

    class Client:
        chat = Chat()

    try:
        with pytest.raises(RuntimeError, match="provider down"):
            create_chat_completion(
                Client(),
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

    class Message:
        def __init__(self, content):
            self.content = content

    class Choice:
        def __init__(self, content):
            self.message = Message(content)

    class Response:
        def __init__(self, content):
            self.choices = [Choice(content)]

    class Completions:
        def __init__(self):
            self.responses = [Response("not json"), Response('{"ok": true}')]

        def create(self, **kwargs):
            return self.responses.pop(0)

    class Chat:
        def __init__(self):
            self.completions = Completions()

    class Client:
        def __init__(self):
            self.chat = Chat()

    try:
        client = Client()
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

    class Message:
        content = json.dumps({
            "results": [{
                "id": "article-1",
                "theme": "Economy",
                "story_label": "Market Rally",
                "importance": 4,
            }]
        })

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

    try:
        classify_articles([article])
        classify_articles([article])
        observability.finish_run(run_id, status="ok")
    finally:
        observability.clear_current_run_id()

    run = _row(db_path, "SELECT llm_calls_count, llm_cache_hits FROM runs WHERE run_id = ?", (run_id,))
    calls = _row(db_path, "SELECT COUNT(*) AS count FROM llm_calls WHERE run_id = ?", (run_id,))
    assert client.chat.completions.calls == 1
    assert run == {"llm_calls_count": 1, "llm_cache_hits": 1}
    assert calls == {"count": 1}
