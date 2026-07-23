import sqlite3

import pytest

import src.tracker as tracker
from evals.run_matching_reconstruction import (
    ReconstructionError,
    _observed_review_decision,
    archive_database,
    reconstruct_effort,
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
