import sqlite3

import pytest

import src.tracker as tracker
from src.tracker import replay


def _article(article_id, title):
    return {
        "id": article_id,
        "source": "Test Source",
        "language": "en",
        "title": title,
        "description": "Stored description",
        "url": f"https://example.com/{article_id}",
        "published_at": "Sat, 18 Apr 2026 12:00:00 GMT",
        "text": "Stored full text",
        "theme": "World",
        "story_label": "Continuing story",
        "importance": 4,
    }


def _configure_tracking(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    monkeypatch.setattr(tracker, "DB_PATH", db_path)
    monkeypatch.setattr(tracker, "DATA_DIR", tmp_path / "daily")
    monkeypatch.setattr(
        tracker,
        "_match_labels",
        lambda labels, recent, today=None: {
            label: label if label in recent else "NEW" for label in labels
        },
    )
    return db_path


def _derived_snapshot(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return {
            "stories": conn.execute(
                """
                SELECT story_id, arc_id, parent_story_id, canonical_label,
                       first_seen, last_seen
                FROM stories ORDER BY story_id
                """
            ).fetchall(),
            "daily": conn.execute(
                "SELECT story_id, date, source_count, labels_seen FROM story_daily ORDER BY date"
            ).fetchall(),
            "observations": conn.execute(
                """
                SELECT story_id, date, article_count, summary, delta_summary
                FROM story_observations ORDER BY date
                """
            ).fetchall(),
            "articles": conn.execute(
                """
                SELECT id, occurrence_id, story_id, date, title
                FROM articles ORDER BY date, id
                """
            ).fetchall(),
        }
    finally:
        conn.close()


def test_replay_rebuilds_forward_from_stored_snapshots(tmp_path, monkeypatch):
    db_path = _configure_tracking(tmp_path, monkeypatch)

    first = tracker.track(
        [_article(1, "Day one")],
        today="2026-04-18",
        verify_story_matches=False,
    )
    tracker.save_observation_memory(
        [{
            "observation_id": first[0]["observation_id"],
            "summary": "Reviewed summary.",
            "delta_summary": "Reviewed delta.",
        }]
    )
    tracker.track(
        [_article(2, "Day two")],
        today="2026-04-19",
        verify_story_matches=False,
    )
    expected = _derived_snapshot(db_path)

    result = replay.rebuild_from_date(db_path, "2026-04-18")

    assert result.dates_rebuilt == 2
    assert result.occurrences_rebuilt == 2
    assert _derived_snapshot(db_path) == expected

    # A second replay from identical stored snapshots is idempotent.
    replay.rebuild_from_date(db_path, "2026-04-18")
    assert _derived_snapshot(db_path) == expected

    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM article_occurrences").fetchone()[0] == 2
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()


def test_replay_missing_assignment_fails_before_deleting_state(tmp_path, monkeypatch):
    db_path = _configure_tracking(tmp_path, monkeypatch)
    tracker.track(
        [_article(1, "Day one")],
        today="2026-04-18",
        verify_story_matches=False,
    )

    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM occurrence_assignments")
    conn.commit()
    before = conn.execute("SELECT COUNT(*) FROM story_daily").fetchone()[0]
    conn.close()

    with pytest.raises(replay.ReplayError, match="assignment snapshots"):
        replay.rebuild_from_date(db_path, "2026-04-18")

    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM story_daily").fetchone()[0] == before
    finally:
        conn.close()


def test_replay_rolls_back_when_rebuild_fails(tmp_path, monkeypatch):
    db_path = _configure_tracking(tmp_path, monkeypatch)
    tracker.track(
        [_article(1, "Day one")],
        today="2026-04-18",
        verify_story_matches=False,
    )
    before = _derived_snapshot(db_path)
    monkeypatch.setattr(
        replay,
        "_rebuild_rows",
        lambda conn, rows, memories: (_ for _ in ()).throw(RuntimeError("rebuild failed")),
    )

    with pytest.raises(RuntimeError, match="rebuild failed"):
        replay.rebuild_from_date(db_path, "2026-04-18")

    assert _derived_snapshot(db_path) == before


def test_same_day_rerun_does_not_replay_omitted_occurrences(tmp_path, monkeypatch):
    db_path = _configure_tracking(tmp_path, monkeypatch)
    first_article = _article(1, "First article")
    second_article = _article(2, "Second article")

    tracker.track(
        [first_article, second_article],
        today="2026-04-18",
        verify_story_matches=False,
    )
    tracker.track(
        [first_article],
        today="2026-04-18",
        verify_story_matches=False,
    )

    result = replay.rebuild_from_date(db_path, "2026-04-18")

    assert result.occurrences_rebuilt == 1
    conn = sqlite3.connect(db_path)
    try:
        article_ids = conn.execute(
            "SELECT id FROM articles ORDER BY id"
        ).fetchall()
        raw_occurrence_count = conn.execute(
            "SELECT COUNT(*) FROM article_occurrences"
        ).fetchone()[0]
        assignment_count = conn.execute(
            "SELECT COUNT(*) FROM occurrence_assignments"
        ).fetchone()[0]
    finally:
        conn.close()

    assert article_ids == [("1",)]
    assert raw_occurrence_count == 2
    assert assignment_count == 1


def test_failed_reclassification_does_not_change_replay_snapshot(tmp_path, monkeypatch):
    db_path = _configure_tracking(tmp_path, monkeypatch)
    original = _article(1, "Original title")
    tracker.track(
        [original],
        today="2026-04-18",
        verify_story_matches=False,
    )

    reclassified = {
        **original,
        "theme": "Changed theme",
        "story_label": "Changed label",
        "importance": 1,
    }
    monkeypatch.setattr(
        tracker,
        "_consolidate_today",
        lambda groups: (_ for _ in ()).throw(RuntimeError("tracking failed")),
    )
    with pytest.raises(RuntimeError, match="tracking failed"):
        tracker.track(
            [reclassified],
            today="2026-04-18",
            verify_story_matches=False,
        )

    replay.rebuild_from_date(db_path, "2026-04-18")

    conn = sqlite3.connect(db_path)
    try:
        classification = conn.execute(
            "SELECT theme, story_label, importance FROM occurrence_classifications"
        ).fetchone()
        assignment = conn.execute(
            "SELECT theme, story_label, importance FROM occurrence_assignments"
        ).fetchone()
        rebuilt = conn.execute(
            """
            SELECT s.theme, sd.labels_seen, sd.importance_avg
            FROM stories s
            JOIN story_daily sd ON sd.story_id = s.story_id
            """
        ).fetchone()
    finally:
        conn.close()

    assert classification == ("Changed theme", "Changed label", 1)
    assert assignment == ("World", "Continuing story", 4)
    assert rebuilt == ("World", '["Continuing story"]', 4.0)
