import sqlite3
import sys
from types import SimpleNamespace

import pytest

import src.article_cache as article_cache
import src.claims as claims
import src.llm_response_cache as llm_response_cache
import src.observability as observability
import src.run as run
import src.sources as sources
import src.tracker as tracker


def _args(**overrides):
    values = {
        "max_per_source": 1,
        "today": "2026-04-28",
        "skip_digest": True,
        "skip_briefing": True,
        "skip_pdf": True,
        "db_off": False,
        "top_developments": 5,
        "fetch_article_text": False,
        "include_undated": False,
        "show_evidence": False,
        "verify_story_matches": False,
        "pipeline_report": False,
        "log_level": "INFO",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture(autouse=True)
def isolate_run_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(observability, "RUN_ARTIFACTS_DIR", tmp_path / "run_artifacts")


def test_db_off_uses_temporary_database_paths_and_restores_originals(tmp_path, monkeypatch):
    real_db = tmp_path / "real" / "stories.db"
    real_daily = tmp_path / "real" / "daily"
    monkeypatch.setattr(article_cache, "DB_PATH", real_db)
    monkeypatch.setattr(claims, "DB_PATH", real_db)
    monkeypatch.setattr(llm_response_cache, "DB_PATH", real_db)
    monkeypatch.setattr(observability, "DB_PATH", real_db)
    monkeypatch.setattr(sources, "DB_PATH", real_db)
    monkeypatch.setattr(tracker, "DB_PATH", real_db)
    monkeypatch.setattr(tracker, "DATA_DIR", real_daily)
    monkeypatch.setattr(run, "parse_args", lambda: _args(db_off=True))
    monkeypatch.setattr(run, "require_openai_api_key", lambda: None)
    monkeypatch.setattr(run, "scrape_all", lambda **kwargs: [{"id": "article-1"}])

    seen = {}

    def fake_classify(articles):
        seen["article_cache_db"] = article_cache.DB_PATH
        seen["sources_db"] = sources.DB_PATH
        return [{"id": "article-1"}]

    def fake_track(classified, today=None):
        seen["tracker_db"] = tracker.DB_PATH
        seen["tracker_daily"] = tracker.DATA_DIR
        seen["claims_db"] = claims.DB_PATH
        seen["llm_response_cache_db"] = llm_response_cache.DB_PATH
        seen["observability_db"] = observability.DB_PATH
        return []

    monkeypatch.setattr(run, "classify_articles", fake_classify)
    monkeypatch.setattr(run, "track", fake_track)

    assert run.main() == []

    assert seen["article_cache_db"] != real_db
    assert seen["tracker_db"] == seen["article_cache_db"]
    assert seen["claims_db"] == seen["article_cache_db"]
    assert seen["llm_response_cache_db"] == seen["article_cache_db"]
    assert seen["observability_db"] == seen["article_cache_db"]
    assert seen["sources_db"] == seen["article_cache_db"]
    assert seen["tracker_daily"].parent == seen["tracker_db"].parent
    assert article_cache.DB_PATH == real_db
    assert claims.DB_PATH == real_db
    assert llm_response_cache.DB_PATH == real_db
    assert observability.DB_PATH == real_db
    assert sources.DB_PATH == real_db
    assert tracker.DB_PATH == real_db
    assert tracker.DATA_DIR == real_daily
    assert not real_db.exists()


def test_normal_run_uses_configured_database_paths(tmp_path, monkeypatch):
    real_db = tmp_path / "real" / "stories.db"
    real_daily = tmp_path / "real" / "daily"
    monkeypatch.setattr(article_cache, "DB_PATH", real_db)
    monkeypatch.setattr(claims, "DB_PATH", real_db)
    monkeypatch.setattr(llm_response_cache, "DB_PATH", real_db)
    monkeypatch.setattr(observability, "DB_PATH", real_db)
    monkeypatch.setattr(sources, "DB_PATH", real_db)
    monkeypatch.setattr(tracker, "DB_PATH", real_db)
    monkeypatch.setattr(tracker, "DATA_DIR", real_daily)
    monkeypatch.setattr(run, "parse_args", lambda: _args(db_off=False))
    monkeypatch.setattr(run, "require_openai_api_key", lambda: None)

    seen = {}

    def fake_scrape(**kwargs):
        seen["scrape_kwargs"] = kwargs
        return [{"id": "article-1"}]

    def fake_classify(articles):
        seen["article_cache_db"] = article_cache.DB_PATH
        seen["sources_db"] = sources.DB_PATH
        return []

    def fake_track(classified, today=None):
        seen["tracker_db"] = tracker.DB_PATH
        seen["claims_db"] = claims.DB_PATH
        seen["llm_response_cache_db"] = llm_response_cache.DB_PATH
        seen["observability_db"] = observability.DB_PATH
        return []

    monkeypatch.setattr(run, "scrape_all", fake_scrape)
    monkeypatch.setattr(run, "classify_articles", fake_classify)
    monkeypatch.setattr(run, "track", fake_track)

    assert run.main() == []

    assert seen["article_cache_db"] == real_db
    assert seen["sources_db"] == real_db
    assert seen["tracker_db"] == real_db
    assert seen["claims_db"] == real_db
    assert seen["llm_response_cache_db"] == real_db
    assert seen["observability_db"] == real_db
    assert seen["scrape_kwargs"]["target_date"] == "2026-04-28"
    assert seen["scrape_kwargs"]["fetch_article_text"] is False
    assert seen["scrape_kwargs"]["include_undated"] is False


def test_show_evidence_requests_article_text(monkeypatch):
    seen = {}

    def fake_scrape(**kwargs):
        seen.update(kwargs)
        return []

    monkeypatch.setattr(run, "scrape_all", fake_scrape)

    run.scrape_articles(_args(show_evidence=True), "2026-04-28")

    assert seen["fetch_article_text"] is True


def test_include_undated_flag_is_passed_to_scraper(monkeypatch):
    seen = {}

    def fake_scrape(**kwargs):
        seen.update(kwargs)
        return []

    monkeypatch.setattr(run, "scrape_all", fake_scrape)

    run.scrape_articles(_args(include_undated=True), "2026-04-28")

    assert seen["include_undated"] is True


def test_parse_args_defaults_include_undated_off(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run.py"])

    args = run.parse_args()

    assert args.include_undated is False


def test_parse_args_allows_include_undated(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run.py", "--include-undated"])

    args = run.parse_args()

    assert args.include_undated is True


def test_pipeline_report_prints_run_totals(tmp_path, monkeypatch, capsys):
    real_db = tmp_path / "real" / "stories.db"
    real_daily = tmp_path / "real" / "daily"
    monkeypatch.setattr(article_cache, "DB_PATH", real_db)
    monkeypatch.setattr(claims, "DB_PATH", real_db)
    monkeypatch.setattr(observability, "DB_PATH", real_db)
    monkeypatch.setattr(sources, "DB_PATH", real_db)
    monkeypatch.setattr(tracker, "DB_PATH", real_db)
    monkeypatch.setattr(tracker, "DATA_DIR", real_daily)
    monkeypatch.setattr(run, "parse_args", lambda: _args(pipeline_report=True))
    monkeypatch.setattr(run, "require_openai_api_key", lambda: None)

    monkeypatch.setattr(
        run,
        "scrape_all",
        lambda **kwargs: [{"id": "article-1"}, {"id": "article-2"}],
    )
    monkeypatch.setattr(run, "classify_articles", lambda articles: articles)
    monkeypatch.setattr(
        run,
        "track",
        lambda classified, today=None: [
            {"id": "article-1", "story_id": 7},
            {"id": "article-2", "story_id": 7},
        ],
    )

    assert run.main() == []

    output = capsys.readouterr().out
    assert "Run #1 (2026-04-28, ok" in output
    assert "Articles returned:      2" in output
    assert "Claims saved:           0" in output
    assert "Stories touched:        1" in output
    assert "LLM errors:             0" in output

    conn = sqlite3.connect(real_db)
    try:
        row = conn.execute(
            """
            SELECT status, articles_returned, stories_touched
            FROM runs
            """
        ).fetchone()
    finally:
        conn.close()

    assert row == ("ok", 2, 1)


def test_main_writes_run_artifact_markdown(tmp_path, monkeypatch):
    real_db = tmp_path / "real" / "stories.db"
    real_daily = tmp_path / "real" / "daily"
    monkeypatch.setattr(article_cache, "DB_PATH", real_db)
    monkeypatch.setattr(claims, "DB_PATH", real_db)
    monkeypatch.setattr(observability, "DB_PATH", real_db)
    monkeypatch.setattr(sources, "DB_PATH", real_db)
    monkeypatch.setattr(tracker, "DB_PATH", real_db)
    monkeypatch.setattr(tracker, "DATA_DIR", real_daily)
    monkeypatch.setattr(run, "parse_args", lambda: _args())
    monkeypatch.setattr(run, "require_openai_api_key", lambda: None)
    monkeypatch.setattr(run, "scrape_all", lambda **kwargs: [{"id": "article-1"}])
    monkeypatch.setattr(run, "classify_articles", lambda articles: articles)
    monkeypatch.setattr(
        run,
        "track",
        lambda classified, today=None: [{"id": "article-1", "story_id": 7}],
    )

    assert run.main() == []

    artifact = observability.RUN_ARTIFACTS_DIR / "run_2026-04-28.md"
    assert artifact.exists()
    markdown = artifact.read_text(encoding="utf-8")
    assert "# Run Report: 2026-04-28" in markdown
    assert "| Articles returned | 1 |" in markdown
    assert "| Stories touched | 1 |" in markdown


def test_verify_story_matches_flag_is_passed_to_tracker(tmp_path, monkeypatch):
    real_db = tmp_path / "real" / "stories.db"
    real_daily = tmp_path / "real" / "daily"
    monkeypatch.setattr(article_cache, "DB_PATH", real_db)
    monkeypatch.setattr(claims, "DB_PATH", real_db)
    monkeypatch.setattr(observability, "DB_PATH", real_db)
    monkeypatch.setattr(sources, "DB_PATH", real_db)
    monkeypatch.setattr(tracker, "DB_PATH", real_db)
    monkeypatch.setattr(tracker, "DATA_DIR", real_daily)
    monkeypatch.setattr(run, "parse_args", lambda: _args(verify_story_matches=True))
    monkeypatch.setattr(run, "require_openai_api_key", lambda: None)

    seen = {}

    monkeypatch.setattr(run, "scrape_all", lambda **kwargs: [{"id": "article-1"}])
    monkeypatch.setattr(run, "classify_articles", lambda articles: articles)

    def fake_track(classified, today=None, verify_story_matches=False):
        seen["verify_story_matches"] = verify_story_matches
        return []

    monkeypatch.setattr(run, "track", fake_track)

    assert run.main() == []
    assert seen["verify_story_matches"] is True


def test_main_finalizes_run_as_error_when_pipeline_fails(tmp_path, monkeypatch):
    real_db = tmp_path / "real" / "stories.db"
    real_daily = tmp_path / "real" / "daily"
    monkeypatch.setattr(article_cache, "DB_PATH", real_db)
    monkeypatch.setattr(claims, "DB_PATH", real_db)
    monkeypatch.setattr(observability, "DB_PATH", real_db)
    monkeypatch.setattr(sources, "DB_PATH", real_db)
    monkeypatch.setattr(tracker, "DB_PATH", real_db)
    monkeypatch.setattr(tracker, "DATA_DIR", real_daily)
    monkeypatch.setattr(run, "parse_args", lambda: _args())
    monkeypatch.setattr(run, "require_openai_api_key", lambda: None)

    def fail_scrape(**kwargs):
        raise RuntimeError("scrape failed")

    monkeypatch.setattr(run, "scrape_all", fail_scrape)

    try:
        run.main()
    except RuntimeError as exc:
        assert str(exc) == "scrape failed"
    else:
        raise AssertionError("run.main should raise the pipeline error")

    conn = sqlite3.connect(real_db)
    try:
        row = conn.execute(
            "SELECT status, error_message FROM runs"
        ).fetchone()
    finally:
        conn.close()

    assert row == ("error", "scrape failed")


def test_missing_api_key_does_not_create_run_row(tmp_path, monkeypatch):
    real_db = tmp_path / "real" / "stories.db"
    real_daily = tmp_path / "real" / "daily"
    monkeypatch.setattr(article_cache, "DB_PATH", real_db)
    monkeypatch.setattr(claims, "DB_PATH", real_db)
    monkeypatch.setattr(observability, "DB_PATH", real_db)
    monkeypatch.setattr(sources, "DB_PATH", real_db)
    monkeypatch.setattr(tracker, "DB_PATH", real_db)
    monkeypatch.setattr(tracker, "DATA_DIR", real_daily)
    monkeypatch.setattr(run, "parse_args", lambda: _args())
    monkeypatch.setattr(
        run,
        "require_openai_api_key",
        lambda: (_ for _ in ()).throw(RuntimeError("missing key")),
    )

    try:
        run.main()
    except RuntimeError as exc:
        assert str(exc) == "missing key"
    else:
        raise AssertionError("run.main should raise when the API key is missing")

    assert not real_db.exists()
