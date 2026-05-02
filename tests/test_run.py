from types import SimpleNamespace

import src.article_cache as article_cache
import src.run as run
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
        "show_evidence": False,
        "log_level": "INFO",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_db_off_uses_temporary_database_paths_and_restores_originals(tmp_path, monkeypatch):
    real_db = tmp_path / "real" / "stories.db"
    real_daily = tmp_path / "real" / "daily"
    monkeypatch.setattr(article_cache, "DB_PATH", real_db)
    monkeypatch.setattr(tracker, "DB_PATH", real_db)
    monkeypatch.setattr(tracker, "DATA_DIR", real_daily)
    monkeypatch.setattr(run, "parse_args", lambda: _args(db_off=True))
    monkeypatch.setattr(run, "require_openai_api_key", lambda: None)
    monkeypatch.setattr(run, "scrape_all", lambda **kwargs: [{"id": "article-1"}])

    seen = {}

    def fake_classify(articles):
        seen["article_cache_db"] = article_cache.DB_PATH
        return [{"id": "article-1"}]

    def fake_track(classified, today=None):
        seen["tracker_db"] = tracker.DB_PATH
        seen["tracker_daily"] = tracker.DATA_DIR
        return []

    monkeypatch.setattr(run, "classify_articles", fake_classify)
    monkeypatch.setattr(run, "track", fake_track)

    assert run.main() == []

    assert seen["article_cache_db"] != real_db
    assert seen["tracker_db"] == seen["article_cache_db"]
    assert seen["tracker_daily"].parent == seen["tracker_db"].parent
    assert article_cache.DB_PATH == real_db
    assert tracker.DB_PATH == real_db
    assert tracker.DATA_DIR == real_daily
    assert not real_db.exists()


def test_normal_run_uses_configured_database_paths(tmp_path, monkeypatch):
    real_db = tmp_path / "real" / "stories.db"
    real_daily = tmp_path / "real" / "daily"
    monkeypatch.setattr(article_cache, "DB_PATH", real_db)
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
        return []

    def fake_track(classified, today=None):
        seen["tracker_db"] = tracker.DB_PATH
        return []

    monkeypatch.setattr(run, "scrape_all", fake_scrape)
    monkeypatch.setattr(run, "classify_articles", fake_classify)
    monkeypatch.setattr(run, "track", fake_track)

    assert run.main() == []

    assert seen["article_cache_db"] == real_db
    assert seen["tracker_db"] == real_db
    assert seen["scrape_kwargs"]["target_date"] == "2026-04-28"
