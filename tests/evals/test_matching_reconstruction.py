import sqlite3

import pytest

import src.tracker as tracker
from evals.run_matching_reconstruction import (
    ReconstructionError,
    _observed_review_decision,
    archive_database,
    format_markdown_report,
    reconstruct_effort,
    score_review_cases,
    snapshot_manifest,
)
from tests.tracker.support import _article


def _source_database(tmp_path):
    db_path = tmp_path / "source.db"
    tracker.track(
        [_article(1, "Stored day one", "Stored event")],
        today="2026-07-21",
        verify_story_matches=False,
        db_path=db_path,
        data_dir=tmp_path / "source-daily",
    )
    return db_path


def test_manifest_and_archive_are_read_only_for_source(tmp_path):
    source_db = _source_database(tmp_path)
    before = source_db.read_bytes()

    manifest = snapshot_manifest(source_db, "2026-07-21", "2026-07-21")
    archive = tmp_path / "archive.db"
    archive_database(source_db, archive)

    assert manifest["article_count"] == 1
    assert source_db.read_bytes() == before
    connection = sqlite3.connect(archive)
    try:
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        connection.close()


def test_archive_refuses_to_overwrite_existing_file(tmp_path):
    source_db = _source_database(tmp_path)
    archive = tmp_path / "archive.db"
    archive.write_bytes(b"keep")

    with pytest.raises(ReconstructionError, match="already exists"):
        archive_database(source_db, archive)

    assert archive.read_bytes() == b"keep"


def test_single_day_reconstruction_writes_only_isolated_copy(tmp_path):
    source_db = _source_database(tmp_path)
    source_before = source_db.read_bytes()
    archive = tmp_path / "archive.db"
    archive_database(source_db, archive)
    output = tmp_path / "reconstructed.db"
    articles = {
        "2026-07-21": [
            {
                **_article(1, "Stored day one", "Stored event"),
                "editorial_date": "2026-07-21",
            }
        ]
    }

    result = reconstruct_effort(
        archive,
        output,
        articles,
        start_date="2026-07-21",
        effort="none",
    )

    assert result["integrity"]["quick_check"] == "ok"
    assert output.is_file()
    assert source_db.read_bytes() == source_before
    connection = sqlite3.connect(output)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM articles WHERE date = '2026-07-21'"
        ).fetchone()[0] == 1
    finally:
        connection.close()


def test_review_case_accepts_any_reviewed_candidate_alias(tmp_path):
    db_path = tmp_path / "review.db"
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE article_occurrences (
            occurrence_id INTEGER PRIMARY KEY,
            article_id TEXT NOT NULL,
            editorial_date TEXT NOT NULL
        );
        CREATE TABLE occurrence_assignments (
            occurrence_id INTEGER PRIMARY KEY,
            story_id INTEGER NOT NULL,
            arc_id INTEGER NOT NULL,
            development_label TEXT NOT NULL
        );
        CREATE TABLE story_match_decisions (
            decision_id INTEGER PRIMARY KEY,
            run_id INTEGER NOT NULL,
            today_label TEXT NOT NULL,
            candidate_story_id INTEGER NOT NULL,
            accepted INTEGER NOT NULL,
            relationship TEXT NOT NULL,
            decision_route TEXT NOT NULL
        );
        """
    )
    connection.executemany(
        "INSERT INTO article_occurrences VALUES (?, ?, ?)",
        [
            (1, "today", "2026-07-22"),
            (2, "primary", "2026-07-21"),
            (3, "alias", "2026-07-21"),
        ],
    )
    connection.executemany(
        "INSERT INTO occurrence_assignments VALUES (?, ?, ?, ?)",
        [
            (1, 20, 20, "Current label"),
            (2, 30, 30, "Primary label"),
            (3, 31, 31, "Alias label"),
        ],
    )
    connection.execute(
        """
        INSERT INTO story_match_decisions
            (run_id, today_label, candidate_story_id, accepted,
             relationship, decision_route)
        VALUES (7, 'Current label', 31, 1, 'same_event', 'mini')
        """
    )

    observed = _observed_review_decision(
        connection,
        {
            "layer": "story",
            "today_date": "2026-07-22",
            "today_article_id": "today",
            "candidate_date": "2026-07-21",
            "candidate_article_id": "primary",
            "candidate_article_ids": ["alias"],
        },
        {"2026-07-22": 7},
    )

    assert observed == (True, "same_event", "mini")
    connection.close()


def test_insufficient_evidence_is_reported_but_excluded_from_scoring(tmp_path):
    db_path = tmp_path / "review.db"
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE article_occurrences (
            occurrence_id INTEGER PRIMARY KEY,
            article_id TEXT NOT NULL,
            editorial_date TEXT NOT NULL
        );
        CREATE TABLE occurrence_assignments (
            occurrence_id INTEGER PRIMARY KEY,
            story_id INTEGER NOT NULL,
            arc_id INTEGER NOT NULL,
            development_label TEXT NOT NULL
        );
        CREATE TABLE story_match_decisions (
            decision_id INTEGER PRIMARY KEY,
            run_id INTEGER NOT NULL,
            today_label TEXT NOT NULL,
            candidate_story_id INTEGER NOT NULL,
            accepted INTEGER NOT NULL,
            relationship TEXT NOT NULL,
            decision_route TEXT NOT NULL
        );
        INSERT INTO article_occurrences VALUES
            (1, 'today', '2026-07-22'),
            (2, 'thin-evidence', '2026-07-21'),
            (3, 'clear-evidence', '2026-07-21');
        INSERT INTO occurrence_assignments VALUES
            (1, 20, 20, 'Current label'),
            (2, 30, 30, 'Thin label'),
            (3, 31, 31, 'Clear label');
        INSERT INTO story_match_decisions VALUES
            (1, 7, 'Current label', 30, 0, 'uncertain', 'fail_closed'),
            (2, 7, 'Current label', 31, 1, 'same_event', 'mini');
        """
    )
    connection.close()
    shared = {
        "layer": "story",
        "today_date": "2026-07-22",
        "today_article_id": "today",
        "candidate_date": "2026-07-21",
        "expected_accepted": True,
    }
    review = score_review_cases(
        db_path,
        [
            {
                **shared,
                "case_id": "thin",
                "candidate_article_id": "thin-evidence",
                "review_status": "insufficient_evidence",
                "evidence_gap": "No retained description or body text.",
            },
            {
                **shared,
                "case_id": "clear",
                "candidate_article_id": "clear-evidence",
            },
        ],
        {"2026-07-22": 7},
    )

    assert review["cases"] == 2
    assert review["scored_cases"] == 1
    assert review["insufficient_evidence_cases"] == 1
    assert review["accepted_positives"] == 1
    assert review["clear_positive_recall"] == 1.0
    assert review["results"][0]["outcome"] == "insufficient_evidence"

    markdown = format_markdown_report(
        {
            "created_at": "2026-07-23T00:00:00+00:00",
            "manifest": {
                "start_date": "2026-07-21",
                "end_date": "2026-07-22",
                "article_count": 2,
                "dates": [{}, {}],
            },
            "archive": "source-archive.db",
            "review_dataset": "review.jsonl",
            "active_database_replaced": False,
            "efforts": [
                {
                    "effort": "none",
                    "cost": {"cost_eur": 0.01},
                    "review": review,
                }
            ],
            "recommendation": {
                "status": "incomplete",
                "selected_effort": None,
                "reason": "Both efforts are required.",
            },
        }
    )

    assert "These cases remain fail-closed" in markdown
    assert "No retained description or body text." in markdown
