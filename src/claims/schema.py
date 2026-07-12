import sqlite3

from src import sources
from src.tracker import occurrences


def get_db(db_path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    sources.ensure_sources_schema(conn)
    occurrences.ensure_schema(conn)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS claims (
            claim_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id     TEXT NOT NULL,
            occurrence_id  INTEGER REFERENCES article_occurrences(occurrence_id),
            story_id       INTEGER,
            claim_text     TEXT NOT NULL,
            claim_type     TEXT,
            entities       TEXT,
            evidence_span  TEXT,
            confidence     REAL,
            prompt_version TEXT,
            validation_version TEXT,
            created_at     TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_claims_article
            ON claims (article_id, prompt_version);
        CREATE INDEX IF NOT EXISTS idx_claims_story
            ON claims (story_id);
        CREATE TABLE IF NOT EXISTS claim_extractions (
            extraction_key TEXT NOT NULL,
            occurrence_id  INTEGER REFERENCES article_occurrences(occurrence_id),
            article_id     TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            story_id       INTEGER,
            content_hash   TEXT NOT NULL,
            claims_count   INTEGER NOT NULL,
            extractor_model TEXT,
            validation_version TEXT,
            extracted_at   TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (extraction_key, prompt_version)
        );
    """)
    _migrate_claim_extractions(conn)
    _ensure_column(
        conn,
        "claims",
        "occurrence_id",
        "INTEGER REFERENCES article_occurrences(occurrence_id)",
    )
    _ensure_column(conn, "claims", "validation_version", "TEXT")
    _ensure_column(conn, "claim_extractions", "extractor_model", "TEXT")
    _ensure_column(conn, "claim_extractions", "validation_version", "TEXT")
    conn.commit()
    return conn


def _ensure_column(conn, table, column, definition):
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _migrate_claim_extractions(conn):
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(claim_extractions)")}
    if not columns or "extraction_key" in columns:
        return
    conn.executescript(
        """
        ALTER TABLE claim_extractions RENAME TO claim_extractions_legacy;
        CREATE TABLE claim_extractions (
            extraction_key TEXT NOT NULL,
            occurrence_id  INTEGER REFERENCES article_occurrences(occurrence_id),
            article_id     TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            story_id       INTEGER,
            content_hash   TEXT NOT NULL,
            claims_count   INTEGER NOT NULL,
            extractor_model TEXT,
            validation_version TEXT,
            extracted_at   TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (extraction_key, prompt_version)
        );
        INSERT INTO claim_extractions (
            extraction_key, occurrence_id, article_id, prompt_version,
            story_id, content_hash, claims_count, extracted_at
        )
        SELECT
            'article:' || article_id, NULL, article_id, prompt_version,
            story_id, content_hash, claims_count, extracted_at
        FROM claim_extractions_legacy;
        DROP TABLE claim_extractions_legacy;
        """
    )
