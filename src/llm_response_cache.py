import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace


DB_PATH = Path("data/stories.db")


def _get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
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


def _canonical_json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def cache_metadata(*, purpose, model, messages, prompt_version=None, response_format=None, kwargs=None):
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


def get_cached_response(metadata):
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
            """,
            (
                metadata["purpose"],
                metadata["model"],
                metadata["prompt_version"],
                metadata["request_hash"],
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


def save_response(metadata, response_content):
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
                    response_content = excluded.response_content
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


def response_from_content(content):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
            )
        ],
        usage=None,
    )
