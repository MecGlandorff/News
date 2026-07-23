import sqlite3

import pytest

import src.tracker as tracker
from evals.run_matching_reconstruction import (
    ReconstructionError,
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
