from __future__ import annotations

import sqlite3

from src import sources
from src.config import (
    STORY_MEMORY_BLOCKED_LABELS,
    STORY_MEMORY_QUARANTINE_LABEL,
    STORY_MEMORY_QUARANTINE_SOURCE_LABELS,
)
from src.tracker import occurrences


QUARANTINED_STORY_LABEL = STORY_MEMORY_QUARANTINE_LABEL
BLOCKED_MEMORY_LABELS = STORY_MEMORY_BLOCKED_LABELS


def _normalized_label(label):
    return " ".join(str(label or "").strip().casefold().split())


NORMALIZED_BLOCKED_MEMORY_LABELS = {
    _normalized_label(blocked)
    for blocked in BLOCKED_MEMORY_LABELS
}


def is_blocked_memory_label(label):
    return _normalized_label(label) in NORMALIZED_BLOCKED_MEMORY_LABELS


def quarantine_uncategorized_memory(conn):
    """Move legacy classifier-omission memory out of future matching surfaces."""
    for source_label in STORY_MEMORY_QUARANTINE_SOURCE_LABELS:
        normalized_source = _normalized_label(source_label)
        conn.execute(
            """
            UPDATE stories
            SET canonical_label = ?
            WHERE LOWER(TRIM(canonical_label)) = ?
            """,
            (QUARANTINED_STORY_LABEL, normalized_source),
        )
        conn.execute(
            """
            UPDATE story_arcs
            SET canonical_label = ?
            WHERE LOWER(TRIM(canonical_label)) = ?
            """,
            (QUARANTINED_STORY_LABEL, normalized_source),
        )


def ensure_column(conn, table, column, definition):
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def backfill_story_arcs(conn):
    """Give legacy flat story rows a one-story compatibility arc."""
    rows = conn.execute("""
        SELECT story_id, canonical_label, theme, first_seen, last_seen
        FROM stories
        WHERE arc_id IS NULL
        ORDER BY story_id
    """).fetchall()
    for row in rows:
        cur = conn.execute(
            """
            INSERT INTO story_arcs (canonical_label, theme, first_seen, last_seen)
            VALUES (?, ?, ?, ?)
            """,
            (
                row["canonical_label"],
                row["theme"],
                row["first_seen"],
                row["last_seen"],
            ),
        )
        conn.execute(
            "UPDATE stories SET arc_id = ?, parent_story_id = NULL WHERE story_id = ?",
            (cur.lastrowid, row["story_id"]),
        )


def get_db(db_path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    sources.ensure_sources_schema(conn)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS story_arcs (
            arc_id          INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_label TEXT NOT NULL,
            theme           TEXT,
            first_seen      DATE NOT NULL,
            last_seen       DATE NOT NULL
        );
        CREATE TABLE IF NOT EXISTS stories (
            story_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            arc_id          INTEGER REFERENCES story_arcs(arc_id),
            parent_story_id INTEGER REFERENCES stories(story_id),
            canonical_label TEXT NOT NULL,
            theme           TEXT,
            first_seen      DATE NOT NULL,
            last_seen       DATE NOT NULL
        );
        CREATE TABLE IF NOT EXISTS story_daily (
            story_id       INTEGER NOT NULL,
            date           DATE NOT NULL,
            source_count   INTEGER,
            importance_avg REAL,
            labels_seen    TEXT,
            PRIMARY KEY (story_id, date)
        );
        CREATE TABLE IF NOT EXISTS story_observations (
            observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            story_id       INTEGER NOT NULL,
            date           DATE NOT NULL,
            label_seen     TEXT,
            source_count   INTEGER,
            article_count  INTEGER,
            importance_avg REAL,
            summary        TEXT,
            delta_summary  TEXT,
            created_at     TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (story_id, date)
        );
        CREATE TABLE IF NOT EXISTS story_developments (
            development_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            story_id            INTEGER NOT NULL,
            observation_id      INTEGER,
            date                DATE NOT NULL,
            development_label   TEXT NOT NULL,
            development_status  TEXT NOT NULL,
            source_count        INTEGER,
            article_count       INTEGER,
            importance_avg      REAL,
            parent_relationship TEXT,
            parent_confidence   TEXT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (story_id, date, development_label)
        );
        CREATE TABLE IF NOT EXISTS articles (
            id             TEXT,
            occurrence_id  INTEGER REFERENCES article_occurrences(occurrence_id),
            story_id       INTEGER,
            date           DATE,
            source_id      INTEGER REFERENCES sources(source_id),
            source         TEXT,
            title          TEXT,
            description    TEXT,
            url            TEXT,
            published_at   TEXT,
            importance     INTEGER
        );
        CREATE TABLE IF NOT EXISTS article_story_links (
            article_id      TEXT NOT NULL,
            occurrence_id   INTEGER REFERENCES article_occurrences(occurrence_id),
            story_id        INTEGER NOT NULL,
            observation_id  INTEGER,
            relevance       REAL,
            PRIMARY KEY (article_id, story_id, observation_id)
        );
        CREATE TABLE IF NOT EXISTS story_match_decisions (
            decision_id          INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id               INTEGER,
            run_date             TEXT NOT NULL,
            today_label          TEXT NOT NULL,
            candidate_label      TEXT NOT NULL,
            candidate_story_id   INTEGER,
            accepted             INTEGER NOT NULL,
            same_event           INTEGER NOT NULL,
            relationship         TEXT NOT NULL,
            confidence           TEXT,
            article_dates        TEXT,
            candidate_last_seen  TEXT,
            continuity_evidence  TEXT,
            reject_reason        TEXT,
            verifier_model       TEXT,
            prompt_version       TEXT NOT NULL,
            created_at           TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_story_match_decisions_run_id
            ON story_match_decisions (run_id);
        CREATE INDEX IF NOT EXISTS idx_story_match_decisions_run_date
            ON story_match_decisions (run_date);
        CREATE TABLE IF NOT EXISTS story_arc_decisions (
            decision_id          INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id               INTEGER,
            run_date             TEXT NOT NULL,
            today_label          TEXT NOT NULL,
            candidates           TEXT NOT NULL,
            arc_id               INTEGER,
            parent_story_id      INTEGER,
            story_id             INTEGER,
            accepted             INTEGER NOT NULL,
            relationship         TEXT NOT NULL,
            confidence           TEXT,
            continuity_evidence  TEXT,
            reject_reason        TEXT,
            assignment_model     TEXT,
            prompt_version       TEXT NOT NULL,
            created_at           TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_story_arc_decisions_run_id
            ON story_arc_decisions (run_id);
        CREATE INDEX IF NOT EXISTS idx_story_arc_decisions_run_date
            ON story_arc_decisions (run_date);
        CREATE INDEX IF NOT EXISTS idx_story_developments_story_date
            ON story_developments (story_id, date);
        CREATE INDEX IF NOT EXISTS idx_story_developments_date
            ON story_developments (date);
        CREATE INDEX IF NOT EXISTS idx_story_arcs_last_seen
            ON story_arcs (last_seen);
    """)
    ensure_column(conn, "stories", "arc_id", "INTEGER REFERENCES story_arcs(arc_id)")
    ensure_column(conn, "stories", "parent_story_id", "INTEGER REFERENCES stories(story_id)")
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_stories_arc_id
            ON stories (arc_id);
        CREATE INDEX IF NOT EXISTS idx_stories_parent_story_id
            ON stories (parent_story_id);
    """)
    ensure_column(conn, "articles", "description", "TEXT")
    ensure_column(conn, "articles", "source_id", "INTEGER REFERENCES sources(source_id)")
    ensure_column(
        conn,
        "articles",
        "occurrence_id",
        "INTEGER REFERENCES article_occurrences(occurrence_id)",
    )
    ensure_column(
        conn,
        "article_story_links",
        "occurrence_id",
        "INTEGER REFERENCES article_occurrences(occurrence_id)",
    )
    occurrences.ensure_schema(conn)
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_articles_story_date_published
            ON articles (story_id, date, published_at);
        CREATE INDEX IF NOT EXISTS idx_articles_id_story
            ON articles (id, story_id);
        CREATE INDEX IF NOT EXISTS idx_articles_date
            ON articles (date);
        CREATE INDEX IF NOT EXISTS idx_articles_occurrence
            ON articles (occurrence_id);
    """)
    backfill_story_arcs(conn)
    occurrences.backfill_legacy_articles(conn)
    conn.commit()
    return conn
