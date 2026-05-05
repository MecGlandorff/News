import sqlite3
from pathlib import Path

from src import scraper


DB_PATH = Path("data/stories.db")

DEFAULT_SOURCE_TYPE = "publication"
DEFAULT_RELIABILITY = "unknown"
DEFAULT_BIAS_NOTES = ""


def _create_sources_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sources (
            source_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL UNIQUE,
            rss_url     TEXT NOT NULL,
            language    TEXT NOT NULL,
            type        TEXT NOT NULL,
            reliability TEXT NOT NULL DEFAULT 'unknown',
            bias_notes  TEXT NOT NULL DEFAULT '',
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_sources_name
            ON sources (name);
    """)


def _source_columns(conn):
    return {row["name"]: row for row in conn.execute("PRAGMA table_info(sources)")}


def _sources_schema_needs_rebuild(conn):
    columns = _source_columns(conn)
    if not columns:
        return False
    type_column = columns.get("type")
    bias_notes_column = columns.get("bias_notes")
    if not type_column or type_column["notnull"] != 1 or type_column["dflt_value"] is not None:
        return True
    if (
        not bias_notes_column
        or bias_notes_column["notnull"] != 1
        or bias_notes_column["dflt_value"] != "''"
    ):
        return True
    return False


def _rebuild_sources_schema(conn):
    conn.executescript("""
        CREATE TABLE sources_new (
            source_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL UNIQUE,
            rss_url     TEXT NOT NULL,
            language    TEXT NOT NULL,
            type        TEXT NOT NULL,
            reliability TEXT NOT NULL DEFAULT 'unknown',
            bias_notes  TEXT NOT NULL DEFAULT '',
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO sources_new (
            source_id, name, rss_url, language, type, reliability,
            bias_notes, created_at, updated_at
        )
        SELECT
            source_id,
            name,
            rss_url,
            language,
            COALESCE(NULLIF(type, ''), 'publication'),
            COALESCE(NULLIF(reliability, ''), 'unknown'),
            COALESCE(bias_notes, ''),
            COALESCE(created_at, CURRENT_TIMESTAMP),
            COALESCE(updated_at, CURRENT_TIMESTAMP)
        FROM sources;
        DROP TABLE sources;
        ALTER TABLE sources_new RENAME TO sources;
        CREATE INDEX IF NOT EXISTS idx_sources_name
            ON sources (name);
    """)


def _get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    _create_sources_schema(conn)
    if _sources_schema_needs_rebuild(conn):
        _rebuild_sources_schema(conn)
    conn.commit()
    return conn


def seed_sources(configured_sources=None):
    """Seed source metadata from the configured RSS feeds.

    Seeding updates fields owned by RSS configuration, but preserves metadata
    that may be edited manually later, such as reliability and bias notes.
    """
    configured_sources = scraper.SOURCES if configured_sources is None else configured_sources
    conn = _get_db()
    try:
        with conn:
            for name, language, rss_url in configured_sources:
                conn.execute(
                    """
                    INSERT INTO sources (
                        name, rss_url, language, type, reliability, bias_notes
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET
                        rss_url = excluded.rss_url,
                        language = excluded.language,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        name,
                        rss_url,
                        language,
                        DEFAULT_SOURCE_TYPE,
                        DEFAULT_RELIABILITY,
                        DEFAULT_BIAS_NOTES,
                    ),
                )
    finally:
        conn.close()


def list_sources():
    """Return source rows ordered by name for inspection and tests."""
    conn = _get_db()
    try:
        rows = conn.execute(
            """
            SELECT source_id, name, rss_url, language, type, reliability,
                   bias_notes, created_at, updated_at
            FROM sources
            ORDER BY name
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
