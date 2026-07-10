from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Mapping
from typing import Any

from src import observability
from src.config import CLASSIFIER_MODEL
from src.classifier import CLASSIFIER_PROMPT_VERSION


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create append-only evidence rows and derived replay projections.

    Raw occurrence rows are append-only. Classification and assignment rows
    are separate because they are derived interpretations of that evidence.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS article_occurrences (
            occurrence_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id      TEXT NOT NULL,
            editorial_date  DATE NOT NULL,
            source_id       INTEGER REFERENCES sources(source_id),
            source          TEXT NOT NULL,
            language        TEXT,
            title           TEXT NOT NULL,
            description     TEXT,
            body_text       TEXT,
            url             TEXT NOT NULL,
            published_at    TEXT,
            content_hash    TEXT NOT NULL,
            retrieval_status TEXT NOT NULL,
            captured_run_id INTEGER,
            captured_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (article_id, editorial_date, content_hash)
        );
        CREATE TABLE IF NOT EXISTS occurrence_classifications (
            occurrence_id   INTEGER PRIMARY KEY REFERENCES article_occurrences(occurrence_id),
            theme           TEXT NOT NULL,
            story_label     TEXT NOT NULL,
            importance      INTEGER NOT NULL,
            classifier_model TEXT NOT NULL,
            prompt_version  TEXT NOT NULL,
            classified_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS occurrence_assignments (
            occurrence_id       INTEGER PRIMARY KEY REFERENCES article_occurrences(occurrence_id),
            theme               TEXT NOT NULL,
            story_label         TEXT NOT NULL,
            importance          INTEGER NOT NULL,
            story_id            INTEGER NOT NULL,
            arc_id              INTEGER,
            parent_story_id     INTEGER,
            canonical_label     TEXT NOT NULL,
            arc_label           TEXT,
            parent_label        TEXT,
            development_label   TEXT NOT NULL,
            development_status  TEXT NOT NULL,
            parent_relationship TEXT,
            parent_confidence   TEXT,
            assigned_run_id     INTEGER,
            assigned_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS occurrence_assignment_history (
            occurrence_id       INTEGER NOT NULL REFERENCES article_occurrences(occurrence_id),
            run_id              INTEGER NOT NULL,
            theme               TEXT NOT NULL,
            story_label         TEXT NOT NULL,
            importance          INTEGER NOT NULL,
            story_id            INTEGER NOT NULL,
            arc_id              INTEGER,
            parent_story_id     INTEGER,
            canonical_label     TEXT NOT NULL,
            arc_label           TEXT,
            parent_label        TEXT,
            development_label   TEXT NOT NULL,
            development_status  TEXT NOT NULL,
            parent_relationship TEXT,
            parent_confidence   TEXT,
            assigned_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (occurrence_id, run_id)
        );
        CREATE INDEX IF NOT EXISTS idx_occurrences_editorial_date
            ON article_occurrences (editorial_date, occurrence_id);
        CREATE INDEX IF NOT EXISTS idx_occurrences_article_date
            ON article_occurrences (article_id, editorial_date);
        CREATE INDEX IF NOT EXISTS idx_occurrence_assignments_story
            ON occurrence_assignments (story_id);
        CREATE INDEX IF NOT EXISTS idx_occurrence_assignment_history_run
            ON occurrence_assignment_history (run_id, story_id);
        """
    )
    _ensure_column(conn, "occurrence_assignments", "theme", "TEXT")
    _ensure_column(conn, "occurrence_assignments", "story_label", "TEXT")
    _ensure_column(conn, "occurrence_assignments", "importance", "INTEGER")
    _ensure_column(conn, "occurrence_assignment_history", "theme", "TEXT")
    _ensure_column(conn, "occurrence_assignment_history", "story_label", "TEXT")
    _ensure_column(conn, "occurrence_assignment_history", "importance", "INTEGER")


def _ensure_column(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _content_hash(article: Mapping[str, Any]) -> str:
    raw = {
        "article_id": str(article.get("id", "")),
        "source": str(article.get("source", "")),
        "language": str(article.get("language", "")),
        "title": str(article.get("title", "")),
        "description": str(article.get("description", "")),
        "body_text": str(article.get("text", "")),
        "url": str(article.get("url", "")),
        "published_at": str(article.get("published_at", "")),
    }
    serialized = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def record_occurrences(
    conn: sqlite3.Connection,
    articles: Iterable[Mapping[str, Any]],
    editorial_date: str,
) -> dict[str, int]:
    """Persist raw snapshots and their current classification interpretation."""
    occurrence_ids: dict[str, int] = {}
    run_id = observability.current_run_id()
    for article in articles:
        article_id = str(article["id"])
        content_hash = _content_hash(article)
        source_id = _source_id_for_name(conn, str(article.get("source", "")))
        body_text = str(article.get("text", ""))
        conn.execute(
            """
            INSERT OR IGNORE INTO article_occurrences (
                article_id, editorial_date, source_id, source, language, title,
                description, body_text, url, published_at, content_hash,
                retrieval_status, captured_run_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                article_id,
                editorial_date,
                source_id,
                str(article.get("source", "")),
                str(article.get("language", "")),
                str(article.get("title", "")),
                str(article.get("description", "")),
                body_text,
                str(article.get("url", "")),
                str(article.get("published_at", "")),
                content_hash,
                "full_text" if body_text.strip() else "rss_only",
                run_id,
            ),
        )
        row = conn.execute(
            """
            SELECT occurrence_id
            FROM article_occurrences
            WHERE article_id = ? AND editorial_date = ? AND content_hash = ?
            """,
            (article_id, editorial_date, content_hash),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"Could not persist occurrence for article {article_id}")
        occurrence_id = int(row["occurrence_id"])
        occurrence_ids[article_id] = occurrence_id
        conn.execute(
            """
            INSERT INTO occurrence_classifications (
                occurrence_id, theme, story_label, importance,
                classifier_model, prompt_version
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(occurrence_id) DO UPDATE SET
                theme = excluded.theme,
                story_label = excluded.story_label,
                importance = excluded.importance,
                classifier_model = excluded.classifier_model,
                prompt_version = excluded.prompt_version,
                classified_at = CURRENT_TIMESTAMP
            """,
            (
                occurrence_id,
                str(article["theme"]),
                str(article["story_label"]),
                int(article["importance"]),
                CLASSIFIER_MODEL,
                CLASSIFIER_PROMPT_VERSION,
            ),
        )
    return occurrence_ids


def save_assignments(conn: sqlite3.Connection, tracked: Iterable[Mapping[str, Any]]) -> None:
    run_id = observability.current_run_id()
    for article in tracked:
        occurrence_id = article.get("occurrence_id")
        if occurrence_id is None:
            continue
        conn.execute(
            """
            INSERT INTO occurrence_assignments (
                occurrence_id, theme, story_label, importance,
                story_id, arc_id, parent_story_id,
                canonical_label, arc_label, parent_label, development_label,
                development_status, parent_relationship, parent_confidence,
                assigned_run_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(occurrence_id) DO UPDATE SET
                theme = excluded.theme,
                story_label = excluded.story_label,
                importance = excluded.importance,
                story_id = excluded.story_id,
                arc_id = excluded.arc_id,
                parent_story_id = excluded.parent_story_id,
                canonical_label = excluded.canonical_label,
                arc_label = excluded.arc_label,
                parent_label = excluded.parent_label,
                development_label = excluded.development_label,
                development_status = excluded.development_status,
                parent_relationship = excluded.parent_relationship,
                parent_confidence = excluded.parent_confidence,
                assigned_run_id = excluded.assigned_run_id,
                assigned_at = CURRENT_TIMESTAMP
            """,
            (
                int(occurrence_id),
                str(article.get("theme", "")),
                str(article.get("story_label", "")),
                int(article.get("importance", 0)),
                int(article["story_id"]),
                article.get("arc_id"),
                article.get("parent_story_id"),
                str(article.get("canonical_label", "")),
                str(article.get("arc_label", "")),
                str(article.get("parent_label", "")),
                str(article.get("development_label", "")),
                str(article.get("development_status", "")),
                str(article.get("parent_relationship", "")),
                str(article.get("parent_confidence", "")),
                run_id,
            ),
        )
        if run_id is not None:
            conn.execute(
                """
                INSERT INTO occurrence_assignment_history (
                    occurrence_id, run_id, theme, story_label, importance,
                    story_id, arc_id, parent_story_id,
                    canonical_label, arc_label, parent_label, development_label,
                    development_status, parent_relationship, parent_confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(occurrence_id, run_id) DO UPDATE SET
                    theme = excluded.theme,
                    story_label = excluded.story_label,
                    importance = excluded.importance,
                    story_id = excluded.story_id,
                    arc_id = excluded.arc_id,
                    parent_story_id = excluded.parent_story_id,
                    canonical_label = excluded.canonical_label,
                    arc_label = excluded.arc_label,
                    parent_label = excluded.parent_label,
                    development_label = excluded.development_label,
                    development_status = excluded.development_status,
                    parent_relationship = excluded.parent_relationship,
                    parent_confidence = excluded.parent_confidence,
                    assigned_at = CURRENT_TIMESTAMP
                """,
                (
                    int(occurrence_id),
                    int(run_id),
                    str(article.get("theme", "")),
                    str(article.get("story_label", "")),
                    int(article.get("importance", 0)),
                    int(article["story_id"]),
                    article.get("arc_id"),
                    article.get("parent_story_id"),
                    str(article.get("canonical_label", "")),
                    str(article.get("arc_label", "")),
                    str(article.get("parent_label", "")),
                    str(article.get("development_label", "")),
                    str(article.get("development_status", "")),
                    str(article.get("parent_relationship", "")),
                    str(article.get("parent_confidence", "")),
                ),
            )


def clear_assignments_for_date(conn: sqlite3.Connection, editorial_date: str) -> None:
    """Remove the mutable assignment projection before a same-day rebuild.

    Raw occurrences and run-scoped assignment history remain append-only. This
    only prevents occurrences omitted by a later successful rerun from being
    treated as part of the current derived state or replay input.
    """
    conn.execute(
        """
        DELETE FROM occurrence_assignments
        WHERE occurrence_id IN (
            SELECT occurrence_id
            FROM article_occurrences
            WHERE editorial_date = ?
        )
        """,
        (editorial_date,),
    )


def backfill_legacy_articles(conn: sqlite3.Connection) -> None:
    """Capture pre-occurrence article rows once, without inventing body text."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            migration_key TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    key = "2026-07-11-backfill-article-occurrences-v1"
    if conn.execute(
        "SELECT 1 FROM schema_migrations WHERE migration_key = ?", (key,)
    ).fetchone():
        return

    rows = conn.execute(
        """
        SELECT ar.rowid AS legacy_rowid, ar.id, ar.story_id, ar.date,
               ar.source_id, ar.source, ar.title, ar.description, ar.url,
               ar.published_at, ar.importance,
               s.canonical_label, s.theme, s.arc_id, s.parent_story_id,
               sa.canonical_label AS arc_label,
               p.canonical_label AS parent_label
        FROM articles ar
        LEFT JOIN stories s ON s.story_id = ar.story_id
        LEFT JOIN story_arcs sa ON sa.arc_id = s.arc_id
        LEFT JOIN stories p ON p.story_id = s.parent_story_id
        WHERE ar.date IS NOT NULL
        ORDER BY ar.rowid
        """
    ).fetchall()
    for row in rows:
        content_hash = hashlib.sha256(
            f"legacy:{row['legacy_rowid']}:{row['id']}:{row['date']}".encode("utf-8")
        ).hexdigest()
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO article_occurrences (
                article_id, editorial_date, source_id, source, language, title,
                description, body_text, url, published_at, content_hash,
                retrieval_status, captured_run_id
            )
            VALUES (?, ?, ?, ?, '', ?, ?, '', ?, ?, ?, 'legacy_metadata_only', NULL)
            """,
            (
                str(row["id"]),
                str(row["date"]),
                row["source_id"],
                str(row["source"] or ""),
                str(row["title"] or ""),
                str(row["description"] or ""),
                str(row["url"] or ""),
                str(row["published_at"] or ""),
                content_hash,
            ),
        )
        occurrence_id = cursor.lastrowid
        if not occurrence_id:
            occurrence = conn.execute(
                """
                SELECT occurrence_id FROM article_occurrences
                WHERE article_id = ? AND editorial_date = ? AND content_hash = ?
                """,
                (str(row["id"]), str(row["date"]), content_hash),
            ).fetchone()
            occurrence_id = occurrence["occurrence_id"]
        canonical_label = str(row["canonical_label"] or "Legacy story")
        conn.execute(
            """
            INSERT OR IGNORE INTO occurrence_classifications (
                occurrence_id, theme, story_label, importance,
                classifier_model, prompt_version
            ) VALUES (?, ?, ?, ?, 'legacy', 'legacy')
            """,
            (
                occurrence_id,
                str(row["theme"] or "Unknown"),
                canonical_label,
                int(row["importance"] or 0),
            ),
        )
        if row["story_id"] is not None:
            conn.execute(
                """
                INSERT OR IGNORE INTO occurrence_assignments (
                    occurrence_id, theme, story_label, importance,
                    story_id, arc_id, parent_story_id,
                    canonical_label, arc_label, parent_label, development_label,
                    development_status, parent_relationship, parent_confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'legacy', '', '')
                """,
                (
                    occurrence_id,
                    str(row["theme"] or "Unknown"),
                    canonical_label,
                    int(row["importance"] or 0),
                    row["story_id"],
                    row["arc_id"],
                    row["parent_story_id"],
                    canonical_label,
                    str(row["arc_label"] or canonical_label),
                    str(row["parent_label"] or ""),
                    canonical_label,
                ),
            )
            conn.execute(
                "UPDATE articles SET occurrence_id = ? WHERE rowid = ?",
                (occurrence_id, row["legacy_rowid"]),
            )

    conn.execute("INSERT INTO schema_migrations (migration_key) VALUES (?)", (key,))


def _source_id_for_name(conn: sqlite3.Connection, source_name: str) -> int | None:
    if not source_name:
        return None
    has_sources = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'sources'"
    ).fetchone()
    if not has_sources:
        return None
    row = conn.execute(
        "SELECT source_id FROM sources WHERE name = ?", (source_name,)
    ).fetchone()
    return int(row["source_id"]) if row else None
