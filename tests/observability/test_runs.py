

import src.observability as observability
from tests.observability.support import _row, _run_args


def test_start_run_marks_unfinished_previous_run_abandoned(tmp_path):
    db_path = tmp_path / "stories.db"

    first = observability.start_run(_run_args(), run_date="2026-05-07", db_path=db_path)
    second = observability.start_run(_run_args(), run_date="2026-05-07", db_path=db_path)

    abandoned = _row(
        db_path,
        "SELECT status, finished_at, error_message FROM runs WHERE run_id = ?",
        (first,),
    )
    current = _row(db_path, "SELECT status FROM runs WHERE run_id = ?", (second,))
    assert abandoned["status"] == "abandoned"
    assert abandoned["finished_at"] is not None
    assert "before the run was finalized" in abandoned["error_message"]
    assert current["status"] == "running"


def test_cache_hits_are_attributed_by_layer(tmp_path):
    db_path = tmp_path / "stories.db"
    run_id = observability.start_run(
        _run_args(), run_date="2026-05-07", db_path=db_path
    )

    observability.increment_cache_hits(2, run_id, layer="classification", db_path=db_path)
    observability.increment_cache_hits(3, run_id, layer="claims", db_path=db_path)
    observability.increment_cache_hits(
        1, run_id, layer="exact", purpose="brief", db_path=db_path
    )

    row = _row(
        db_path,
        """
        SELECT llm_cache_hits, classification_cache_hits,
               claim_cache_hits, briefing_cache_hits
        FROM runs WHERE run_id = ?
        """,
        (run_id,),
    )
    assert row == {
        "llm_cache_hits": 6,
        "classification_cache_hits": 2,
        "claim_cache_hits": 3,
        "briefing_cache_hits": 1,
    }


def test_exact_matching_cache_purposes_are_attributed_to_matching(tmp_path):
    db_path = tmp_path / "stories.db"
    run_id = observability.start_run(
        _run_args(), run_date="2026-05-07", db_path=db_path
    )

    for purpose in ("match-sameday", "match-crossday", "match-verify", "match-arc"):
        observability.increment_cache_hits(
            run_id=run_id,
            layer="exact",
            purpose=purpose,
            db_path=db_path,
        )

    row = _row(
        db_path,
        """
        SELECT llm_cache_hits, matching_cache_hits, other_cache_hits
        FROM runs WHERE run_id = ?
        """,
        (run_id,),
    )
    assert row == {
        "llm_cache_hits": 4,
        "matching_cache_hits": 4,
        "other_cache_hits": 0,
    }


def test_run_lifecycle_records_success_totals(tmp_path):
    db_path = tmp_path / "stories.db"

    run_id = observability.start_run(
        _run_args(), run_date="2026-05-07", db_path=db_path
    )
    observability.update_run_totals(
        run_id,
        articles_returned=8,
        claims_saved=12,
        stories_touched=3,
        db_path=db_path,
    )
    observability.finish_run(run_id, status="ok", db_path=db_path)

    row = _row(db_path, "SELECT * FROM runs WHERE run_id = ?", (run_id,))
    assert row["status"] == "ok"
    assert row["articles_returned"] == 8
    assert row["claims_saved"] == 12
    assert row["stories_touched"] == 3
    assert row["finished_at"] is not None


def test_increment_run_totals_adds_to_existing_counts(tmp_path):
    db_path = tmp_path / "stories.db"

    run_id = observability.start_run(
        _run_args(), run_date="2026-05-07", db_path=db_path
    )
    observability.update_run_totals(
        run_id,
        article_text_fetch_successes=2,
        article_text_fetch_failures=1,
        db_path=db_path,
    )
    observability.increment_run_totals(
        run_id,
        article_text_fetch_successes=3,
        article_text_fetch_failures=2,
        db_path=db_path,
    )

    row = _row(db_path, "SELECT * FROM runs WHERE run_id = ?", (run_id,))
    assert row["article_text_fetch_successes"] == 5
    assert row["article_text_fetch_failures"] == 3


def test_run_lifecycle_records_error_status(tmp_path):
    db_path = tmp_path / "stories.db"

    run_id = observability.start_run(
        _run_args(), run_date="2026-05-07", db_path=db_path
    )
    observability.finish_run(
        run_id,
        status="error",
        error_message="boom",
        db_path=db_path,
    )

    row = _row(db_path, "SELECT status, error_message FROM runs WHERE run_id = ?", (run_id,))
    assert row == {"status": "error", "error_message": "boom"}
