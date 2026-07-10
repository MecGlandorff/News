from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from src import tracker_store


class ReplayError(RuntimeError):
    """Raised when stored snapshots cannot safely reconstruct derived state."""


@dataclass(frozen=True)
class ReplayResult:
    start_date: str
    end_date: str
    dates_rebuilt: int
    occurrences_rebuilt: int
    stories_rebuilt: int


def rebuild_from_date(db_path: Path, start_date: str) -> ReplayResult:
    """Rebuild tracking state from stored, network-independent snapshots."""
    try:
        normalized_start = date.fromisoformat(start_date).isoformat()
    except ValueError as exc:
        raise ReplayError("Replay date must use YYYY-MM-DD format") from exc

    conn = tracker_store.get_db(db_path)
    try:
        rows = _replay_rows(conn, normalized_start)
        if not rows or rows[0]["editorial_date"] != normalized_start:
            stored_for_start = conn.execute(
                """
                SELECT 1 FROM article_occurrences
                WHERE editorial_date = ? LIMIT 1
                """,
                (normalized_start,),
            ).fetchone()
            if stored_for_start:
                raise ReplayError(
                    "Replay requires current assignment snapshots for the start date"
                )
            raise ReplayError(f"No stored occurrences exist for {normalized_start}")
        missing = [
            int(row["occurrence_id"])
            for row in rows
            if row["story_label"] is None or row["story_id"] is None
        ]
        if missing:
            sample = ", ".join(str(value) for value in missing[:5])
            raise ReplayError(
                "Replay requires classification and assignment snapshots for every "
                f"occurrence; missing occurrence IDs: {sample}"
            )
        _validate_parent_snapshots(conn, rows, normalized_start)

        memories = _observation_memories(conn, normalized_start)
        with conn:
            _delete_derived_state(conn, normalized_start)
            tracker_store.sync_story_dates(conn)
            _rebuild_rows(conn, rows, memories)
            tracker_store.sync_story_dates(conn)
            violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise ReplayError(
                    f"Replay produced {len(violations)} foreign-key violation(s)"
                )

        dates = {str(row["editorial_date"]) for row in rows}
        stories = {int(row["story_id"]) for row in rows}
        return ReplayResult(
            start_date=normalized_start,
            end_date=max(dates),
            dates_rebuilt=len(dates),
            occurrences_rebuilt=len(rows),
            stories_rebuilt=len(stories),
        )
    finally:
        conn.close()


def _replay_rows(conn: sqlite3.Connection, start_date: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        WITH latest AS (
            SELECT o.article_id, o.editorial_date,
                   MAX(o.occurrence_id) AS occurrence_id
            FROM article_occurrences o
            JOIN occurrence_assignments a ON a.occurrence_id = o.occurrence_id
            WHERE o.editorial_date >= ?
            GROUP BY o.article_id, o.editorial_date
        )
        SELECT o.occurrence_id, o.article_id, o.editorial_date, o.source_id,
               o.source, o.language, o.title, o.description, o.body_text,
               o.url, o.published_at, o.retrieval_status,
               COALESCE(a.theme, c.theme) AS theme,
               COALESCE(a.story_label, c.story_label) AS story_label,
               COALESCE(a.importance, c.importance) AS importance,
               a.story_id, a.arc_id, a.parent_story_id, a.canonical_label,
               a.arc_label, a.parent_label, a.development_label,
               a.development_status, a.parent_relationship,
               a.parent_confidence
        FROM latest l
        JOIN article_occurrences o ON o.occurrence_id = l.occurrence_id
        LEFT JOIN occurrence_classifications c ON c.occurrence_id = o.occurrence_id
        JOIN occurrence_assignments a ON a.occurrence_id = o.occurrence_id
        ORDER BY o.editorial_date, o.occurrence_id
        """,
        (start_date,),
    ).fetchall()


def _validate_parent_snapshots(
    conn: sqlite3.Connection,
    rows: list[sqlite3.Row],
    start_date: str,
) -> None:
    replay_story_ids = {int(row["story_id"]) for row in rows if row["story_id"] is not None}
    preserved_story_ids = {
        int(row["story_id"])
        for row in conn.execute(
            "SELECT DISTINCT story_id FROM story_daily WHERE date < ?", (start_date,)
        ).fetchall()
    }
    missing_parents = {
        int(row["parent_story_id"])
        for row in rows
        if row["parent_story_id"] is not None
        and int(row["parent_story_id"]) not in replay_story_ids | preserved_story_ids
    }
    if missing_parents:
        raise ReplayError(
            "Replay snapshots reference missing parent stories: "
            + ", ".join(str(value) for value in sorted(missing_parents))
        )


def _observation_memories(
    conn: sqlite3.Connection,
    start_date: str,
) -> dict[tuple[int, str], tuple[str | None, str | None]]:
    return {
        (int(row["story_id"]), str(row["date"])): (
            str(row["summary"]) if row["summary"] is not None else None,
            str(row["delta_summary"]) if row["delta_summary"] is not None else None,
        )
        for row in conn.execute(
            """
            SELECT story_id, date, summary, delta_summary
            FROM story_observations
            WHERE date >= ?
            """,
            (start_date,),
        ).fetchall()
    }


def _delete_derived_state(conn: sqlite3.Connection, start_date: str) -> None:
    conn.execute(
        """
        DELETE FROM article_story_links
        WHERE observation_id IN (
            SELECT observation_id FROM story_observations WHERE date >= ?
        )
        """,
        (start_date,),
    )
    conn.execute("DELETE FROM articles WHERE date >= ?", (start_date,))
    conn.execute("DELETE FROM story_developments WHERE date >= ?", (start_date,))
    conn.execute("DELETE FROM story_observations WHERE date >= ?", (start_date,))
    conn.execute("DELETE FROM story_daily WHERE date >= ?", (start_date,))


def _rebuild_rows(
    conn: sqlite3.Connection,
    rows: list[sqlite3.Row],
    memories: dict[tuple[int, str], tuple[str | None, str | None]],
) -> None:
    _ensure_arcs(conn, rows)
    _ensure_stories(conn, rows)

    rows_by_date_story: dict[tuple[str, int], list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        rows_by_date_story[(str(row["editorial_date"]), int(row["story_id"]))].append(row)

    for (editorial_date, story_id), story_rows in sorted(rows_by_date_story.items()):
        labels = list(dict.fromkeys(str(row["story_label"]) for row in story_rows))
        source_count = len({str(row["source"]) for row in story_rows})
        importance_avg = sum(int(row["importance"]) for row in story_rows) / len(story_rows)
        conn.execute(
            """
            INSERT INTO story_daily (
                story_id, date, source_count, importance_avg, labels_seen
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (story_id, editorial_date, source_count, importance_avg, _json(labels)),
        )
        summary, delta_summary = memories.get((story_id, editorial_date), (None, None))
        cursor = conn.execute(
            """
            INSERT INTO story_observations (
                story_id, date, label_seen, source_count, article_count,
                importance_avg, summary, delta_summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                story_id,
                editorial_date,
                labels[0] if len(labels) == 1 else _json(labels),
                source_count,
                len(story_rows),
                importance_avg,
                summary,
                delta_summary,
            ),
        )
        if cursor.lastrowid is None:
            raise ReplayError("Could not create replay observation")
        observation_id = int(cursor.lastrowid)
        _rebuild_developments_and_articles(
            conn,
            story_rows,
            story_id,
            editorial_date,
            observation_id,
        )


def _ensure_arcs(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> None:
    seen: set[int] = set()
    for row in rows:
        if row["arc_id"] is None:
            continue
        arc_id = int(row["arc_id"])
        if arc_id in seen:
            continue
        seen.add(arc_id)
        conn.execute(
            """
            INSERT OR IGNORE INTO story_arcs (
                arc_id, canonical_label, theme, first_seen, last_seen
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                arc_id,
                str(row["arc_label"] or row["canonical_label"]),
                str(row["theme"]),
                str(row["editorial_date"]),
                str(row["editorial_date"]),
            ),
        )


def _ensure_stories(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> None:
    first_by_story: dict[int, sqlite3.Row] = {}
    for row in rows:
        first_by_story.setdefault(int(row["story_id"]), row)
    for story_id, row in first_by_story.items():
        conn.execute(
            """
            INSERT OR IGNORE INTO stories (
                story_id, arc_id, parent_story_id, canonical_label,
                theme, first_seen, last_seen
            ) VALUES (?, ?, NULL, ?, ?, ?, ?)
            """,
            (
                story_id,
                row["arc_id"],
                str(row["canonical_label"]),
                str(row["theme"]),
                str(row["editorial_date"]),
                str(row["editorial_date"]),
            ),
        )
    for story_id, row in first_by_story.items():
        conn.execute(
            """
            UPDATE stories
            SET arc_id = ?, parent_story_id = ?, canonical_label = ?, theme = ?
            WHERE story_id = ?
            """,
            (
                row["arc_id"],
                row["parent_story_id"],
                str(row["canonical_label"]),
                str(row["theme"]),
                story_id,
            ),
        )


def _rebuild_developments_and_articles(
    conn: sqlite3.Connection,
    rows: list[sqlite3.Row],
    story_id: int,
    editorial_date: str,
    observation_id: int,
) -> None:
    developments: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        developments[str(row["development_label"])].append(row)

    for label, development_rows in developments.items():
        source_count = len({str(row["source"]) for row in development_rows})
        importance_avg = sum(int(row["importance"]) for row in development_rows) / len(
            development_rows
        )
        first = development_rows[0]
        conn.execute(
            """
            INSERT INTO story_developments (
                story_id, observation_id, date, development_label,
                development_status, source_count, article_count, importance_avg,
                parent_relationship, parent_confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                story_id,
                observation_id,
                editorial_date,
                label,
                str(first["development_status"]),
                source_count,
                len(development_rows),
                importance_avg,
                str(first["parent_relationship"] or ""),
                str(first["parent_confidence"] or ""),
            ),
        )
        for row in development_rows:
            conn.execute(
                """
                INSERT INTO articles (
                    id, occurrence_id, story_id, date, source_id, source, title,
                    description, url, published_at, importance
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(row["article_id"]),
                    int(row["occurrence_id"]),
                    story_id,
                    editorial_date,
                    row["source_id"],
                    str(row["source"]),
                    str(row["title"]),
                    str(row["description"] or ""),
                    str(row["url"]),
                    str(row["published_at"] or ""),
                    int(row["importance"]),
                ),
            )
            conn.execute(
                """
                INSERT INTO article_story_links (
                    article_id, occurrence_id, story_id, observation_id, relevance
                ) VALUES (?, ?, ?, ?, 1.0)
                """,
                (
                    str(row["article_id"]),
                    int(row["occurrence_id"]),
                    story_id,
                    observation_id,
                ),
            )


def _json(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)
