import json
import sqlite3

from src.tracker import store


def _insert_occurrence(conn, article_id, title):
    cursor = conn.execute(
        """
        INSERT INTO article_occurrences (
            article_id, editorial_date, source, title, description,
            body_text, url, published_at, content_hash, retrieval_status
        )
        VALUES (?, '2026-07-22', 'Example', ?, '', '', ?, '', ?, 'rss')
        """,
        (
            article_id,
            title,
            f"https://example.com/{article_id}",
            f"hash-{article_id}",
        ),
    )
    return cursor.lastrowid


def test_matching_audit_schema_migrates_legacy_decision_tables(tmp_path):
    db_path = tmp_path / "stories.db"
    legacy = sqlite3.connect(db_path)
    legacy.executescript(
        """
        CREATE TABLE story_match_decisions (
            decision_id INTEGER PRIMARY KEY,
            run_id INTEGER,
            run_date TEXT NOT NULL,
            today_label TEXT NOT NULL,
            candidate_label TEXT NOT NULL,
            candidate_story_id INTEGER,
            accepted INTEGER NOT NULL,
            same_event INTEGER NOT NULL,
            relationship TEXT NOT NULL,
            confidence TEXT,
            article_dates TEXT,
            candidate_last_seen TEXT,
            continuity_evidence TEXT,
            reject_reason TEXT,
            verifier_model TEXT,
            prompt_version TEXT NOT NULL,
            created_at TEXT
        );
        CREATE TABLE story_arc_decisions (
            decision_id INTEGER PRIMARY KEY,
            run_id INTEGER,
            run_date TEXT NOT NULL,
            today_label TEXT NOT NULL,
            candidates TEXT NOT NULL,
            arc_id INTEGER,
            parent_story_id INTEGER,
            story_id INTEGER,
            accepted INTEGER NOT NULL,
            relationship TEXT NOT NULL,
            confidence TEXT,
            continuity_evidence TEXT,
            reject_reason TEXT,
            assignment_model TEXT,
            prompt_version TEXT NOT NULL,
            created_at TEXT
        );
        """
    )
    legacy.close()

    conn = store.get_db(db_path)
    try:
        story_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(story_match_decisions)")
        }
        arc_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(story_arc_decisions)")
        }
        same_day_table = conn.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'same_day_match_decisions'
            """
        ).fetchone()
    finally:
        conn.close()

    assert {
        "decision_route",
        "candidate_signals",
        "conflicts",
        "ambiguity_reason",
        "reasoning_effort",
    } <= story_columns
    assert {
        "decision_route",
        "candidate_signals",
        "conflicts",
        "ambiguity_reason",
        "reasoning_effort",
        "proposed_arc_id",
        "proposed_parent_story_id",
        "previous_arc_label",
        "proposed_arc_label",
        "final_arc_label",
    } <= arc_columns
    assert same_day_table is not None


def test_matching_audit_writes_same_day_story_and_arc_routes(tmp_path):
    conn = store.get_db(tmp_path / "stories.db")
    try:
        with conn:
            left_id = _insert_occurrence(conn, "left", "Tour de France stage")
            right_id = _insert_occurrence(conn, "right", "Tour de France result")
            store.save_same_day_match_decisions(
                conn,
                [
                    {
                        "left_occurrence_id": right_id,
                        "right_occurrence_id": left_id,
                        "candidate_signals": {"shared_rare_tokens": ["tour", "france"]},
                        "accepted": True,
                        "relationship": "same_event",
                        "confidence": "high",
                        "continuity_evidence": ["Tour de France"],
                        "conflicts": [],
                        "decision_route": "mini",
                        "reasoning_effort": "none",
                    }
                ],
                "2026-07-22",
                "gpt-5.4-mini-2026-03-17",
                "test-v1",
            )
            store.save_story_match_decisions(
                conn,
                [
                    {
                        "today_label": "Phone-free youth",
                        "candidate_label": "France social media ban",
                        "accepted": False,
                        "same_event": False,
                        "relationship": "uncertain",
                        "candidate_signals": {"shared_numbers": ["15"]},
                        "conflicts": [],
                        "decision_route": "fail_closed",
                        "ambiguity_reason": "insufficient_shared_anchors",
                        "reasoning_effort": "none",
                    }
                ],
                "2026-07-22",
                "gpt-5.4-mini-2026-03-17",
                "test-v1",
            )
            store.save_story_arc_decisions(
                conn,
                [
                    {
                        "today_label": "Tour de France stage",
                        "candidates": [{"arc_id": 12, "score": 20}],
                        "proposed_arc_id": 12,
                        "accepted": True,
                        "relationship": "same_arc",
                        "candidate_signals": {"shared_named_anchors": ["Tour de France"]},
                        "conflicts": [],
                        "decision_route": "mini",
                        "reasoning_effort": "low",
                        "previous_arc_label": "Tour de France crash",
                        "proposed_arc_label": "Tour de France 2026",
                        "final_arc_label": "Tour de France 2026",
                    }
                ],
                "2026-07-22",
                "gpt-5.4-mini-2026-03-17",
                "test-v1",
            )

        same_day = conn.execute("SELECT * FROM same_day_match_decisions").fetchone()
        story = conn.execute("SELECT * FROM story_match_decisions").fetchone()
        arc = conn.execute("SELECT * FROM story_arc_decisions").fetchone()
    finally:
        conn.close()

    assert same_day["left_occurrence_id"] == left_id
    assert same_day["right_occurrence_id"] == right_id
    assert json.loads(same_day["candidate_signals"])["shared_rare_tokens"] == [
        "tour",
        "france",
    ]
    assert story["decision_route"] == "fail_closed"
    assert story["ambiguity_reason"] == "insufficient_shared_anchors"
    assert arc["proposed_arc_id"] == 12
    assert arc["previous_arc_label"] == "Tour de France crash"
    assert arc["final_arc_label"] == "Tour de France 2026"
