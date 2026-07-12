import sqlite3

from src.tracker import store as tracker_store


def test_story_arc_schema_backfills_legacy_stories(tmp_path):
    db_path = tmp_path / "stories.db"

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript("""
            CREATE TABLE stories (
                story_id INTEGER PRIMARY KEY AUTOINCREMENT,
                canonical_label TEXT NOT NULL,
                theme TEXT,
                first_seen DATE NOT NULL,
                last_seen DATE NOT NULL
            );
            INSERT INTO stories (canonical_label, theme, first_seen, last_seen)
            VALUES ('Legacy Story', 'Tech', '2026-05-01', '2026-05-02');
        """)
        conn.commit()
    finally:
        conn.close()

    conn = tracker_store.get_db(db_path)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(stories)").fetchall()}
        row = conn.execute("""
            SELECT s.arc_id, a.canonical_label, a.first_seen, a.last_seen
            FROM stories s
            JOIN story_arcs a ON a.arc_id = s.arc_id
            WHERE s.canonical_label = 'Legacy Story'
        """).fetchone()
        arc_count = conn.execute("SELECT COUNT(*) FROM story_arcs").fetchone()[0]
    finally:
        conn.close()

    assert {"arc_id", "parent_story_id"} <= columns
    assert tuple(row) == (1, "Legacy Story", "2026-05-01", "2026-05-02")
    assert arc_count == 1


def test_tracker_schema_has_indexes_for_recent_story_article_lookups(tmp_path):
    conn = tracker_store.get_db(tmp_path / "stories.db")
    try:
        indexes = {
            row["name"]
            for row in conn.execute("PRAGMA index_list(articles)").fetchall()
        }
    finally:
        conn.close()

    assert {
        "idx_articles_story_date_published",
        "idx_articles_id_story",
        "idx_articles_date",
    } <= indexes


def test_trend_uses_latest_prior_day(tmp_path):
    db_path = tmp_path / "stories.db"
    conn = tracker_store.get_db(db_path)
    cur = conn.execute(
        "INSERT INTO stories (canonical_label, theme, first_seen, last_seen) VALUES (?, ?, ?, ?)",
        ("Test Story", "Tech", "2026-04-15", "2026-04-18"),
    )
    story_id = cur.lastrowid
    conn.execute(
        """
        INSERT INTO story_daily (story_id, date, source_count, importance_avg, labels_seen)
        VALUES (?, ?, ?, ?, ?)
        """,
        (story_id, "2026-04-16", 1, 3.0, "[]"),
    )
    conn.execute(
        """
        INSERT INTO story_daily (story_id, date, source_count, importance_avg, labels_seen)
        VALUES (?, ?, ?, ?, ?)
        """,
        (story_id, "2026-04-17", 4, 3.0, "[]"),
    )

    assert tracker_store.trend(story_id, 1, conn, "2026-04-18") == "down"
    conn.close()


def test_recent_story_lookup_uses_newest_duplicate_label(tmp_path):
    db_path = tmp_path / "stories.db"
    conn = tracker_store.get_db(db_path)

    old = conn.execute(
        "INSERT INTO stories (canonical_label, theme, first_seen, last_seen) VALUES (?, ?, ?, ?)",
        ("Duplicate Label", "Tech", "2026-04-18", "2026-04-18"),
    ).lastrowid
    new = conn.execute(
        "INSERT INTO stories (canonical_label, theme, first_seen, last_seen) VALUES (?, ?, ?, ?)",
        ("Duplicate Label", "Tech", "2026-04-20", "2026-04-20"),
    ).lastrowid
    conn.execute(
        """
        INSERT INTO story_daily (story_id, date, source_count, importance_avg, labels_seen)
        VALUES (?, ?, ?, ?, ?)
        """,
        (old, "2026-04-18", 1, 3.0, "[]"),
    )
    conn.execute(
        """
        INSERT INTO story_daily (story_id, date, source_count, importance_avg, labels_seen)
        VALUES (?, ?, ?, ?, ?)
        """,
        (new, "2026-04-20", 1, 3.0, "[]"),
    )

    recent = tracker_store.get_recent_stories(conn, "2026-04-21")
    conn.close()

    assert recent["Duplicate Label"] == new
