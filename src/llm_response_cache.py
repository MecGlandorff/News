from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace


DB_PATH = Path("data/stories.db")
CACHE_MAX_AGE_DAYS = 30
CACHE_MAX_ENTRIES = 1000


def _get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS llm_response_cache (
            cache_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            purpose          TEXT NOT NULL,
            model            TEXT NOT NULL,
            prompt_version   TEXT NOT NULL,
            request_hash     TEXT NOT NULL,
            request_json     TEXT NOT NULL,
            response_content TEXT NOT NULL,
            hit_count        INTEGER NOT NULL DEFAULT 0,
            created_at       TEXT DEFAULT CURRENT_TIMESTAMP,
            last_used_at     TEXT,
            UNIQUE (purpose, model, prompt_version, request_hash)
        );
        CREATE INDEX IF NOT EXISTS idx_llm_response_cache_lookup
            ON llm_response_cache (purpose, model, prompt_version, request_hash);
    """)
    conn.commit()
    return conn


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def cache_metadata(
    *,
    purpose: str,
    model: str,
    messages: list[dict],
    prompt_version: str | None = None,
    response_format: dict | None = None,
    kwargs: dict | None = None,
) -> dict[str, str]:
    request = {
        "purpose": purpose,
        "model": model,
        "prompt_version": prompt_version or "",
        "messages": messages,
        "response_format": response_format,
        "kwargs": kwargs or {},
    }
    request_json = _canonical_json(request)
    return {
        "purpose": purpose,
        "model": model,
        "prompt_version": prompt_version or "",
        "request_hash": hashlib.sha256(request_json.encode("utf-8")).hexdigest(),
        "request_json": request_json,
    }


def get_cached_response(metadata: dict[str, str]) -> str | None:
    conn = _get_db()
    try:
        row = conn.execute(
            """
            SELECT response_content
            FROM llm_response_cache
            WHERE purpose = ?
              AND model = ?
              AND prompt_version = ?
              AND request_hash = ?
              AND created_at >= datetime('now', ?)
            """,
            (
                metadata["purpose"],
                metadata["model"],
                metadata["prompt_version"],
                metadata["request_hash"],
                f"-{CACHE_MAX_AGE_DAYS} days",
            ),
        ).fetchone()
        if row is None:
            return None
        with conn:
            conn.execute(
                """
                UPDATE llm_response_cache
                SET hit_count = hit_count + 1,
                    last_used_at = CURRENT_TIMESTAMP
                WHERE purpose = ?
                  AND model = ?
                  AND prompt_version = ?
                  AND request_hash = ?
                """,
                (
                    metadata["purpose"],
                    metadata["model"],
                    metadata["prompt_version"],
                    metadata["request_hash"],
                ),
            )
        return row["response_content"]
    finally:
        conn.close()


def save_response(metadata: dict[str, str], response_content: str) -> None:
    conn = _get_db()
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO llm_response_cache (
                    purpose, model, prompt_version, request_hash,
                    request_json, response_content
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(purpose, model, prompt_version, request_hash) DO UPDATE SET
                    request_json = excluded.request_json,
                    response_content = excluded.response_content,
                    hit_count = 0,
                    created_at = CURRENT_TIMESTAMP,
                    last_used_at = NULL
                """,
                (
                    metadata["purpose"],
                    metadata["model"],
                    metadata["prompt_version"],
                    metadata["request_hash"],
                    metadata["request_json"],
                    response_content,
                ),
            )
    finally:
        conn.close()


def prune_cache(
    *,
    max_age_days: int = CACHE_MAX_AGE_DAYS,
    max_entries: int = CACHE_MAX_ENTRIES,
) -> int:
    """Delete expired and least-recently-used exact responses."""
    if max_age_days < 1 or max_entries < 1:
        raise ValueError("Cache retention values must be positive")
    conn = _get_db()
    try:
        before = int(conn.execute("SELECT COUNT(*) FROM llm_response_cache").fetchone()[0])
        with conn:
            conn.execute(
                "DELETE FROM llm_response_cache WHERE created_at < datetime('now', ?)",
                (f"-{max_age_days} days",),
            )
            conn.execute(
                """
                DELETE FROM llm_response_cache
                WHERE cache_id NOT IN (
                    SELECT cache_id
                    FROM llm_response_cache
                    ORDER BY COALESCE(last_used_at, created_at) DESC, cache_id DESC
                    LIMIT ?
                )
                """,
                (max_entries,),
            )
        after = int(conn.execute("SELECT COUNT(*) FROM llm_response_cache").fetchone()[0])
        return before - after
    finally:
        conn.close()


def response_from_content(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
            )
        ],
        usage=None,
    )
