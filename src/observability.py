import json
import sqlite3
import subprocess
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path


DB_PATH = Path("data/stories.db")

_CURRENT_RUN_ID = ContextVar("current_run_id", default=None)
_LAST_LLM_CALL_ID = ContextVar("last_llm_call_id", default=None)

RUN_TOTAL_COLUMNS = {
    "articles_returned",
    "claims_saved",
    "stories_touched",
    "llm_cache_hits",
    "story_match_verifications",
    "story_match_accepts",
    "story_match_rejections",
}


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    _create_schema(conn)
    conn.commit()
    return conn


def _create_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
            run_id              INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at          TEXT NOT NULL,
            finished_at         TEXT,
            run_date            TEXT,
            cli_args            TEXT NOT NULL,
            git_sha             TEXT,
            articles_returned   INTEGER DEFAULT 0,
            claims_saved        INTEGER DEFAULT 0,
            stories_touched     INTEGER DEFAULT 0,
            story_match_verifications INTEGER DEFAULT 0,
            story_match_accepts INTEGER DEFAULT 0,
            story_match_rejections INTEGER DEFAULT 0,
            llm_calls_count     INTEGER DEFAULT 0,
            llm_errors_count    INTEGER DEFAULT 0,
            llm_cache_hits      INTEGER DEFAULT 0,
            schema_failures     INTEGER DEFAULT 0,
            retry_count         INTEGER DEFAULT 0,
            prompt_tokens       INTEGER DEFAULT 0,
            completion_tokens   INTEGER DEFAULT 0,
            total_latency_ms    INTEGER,
            status              TEXT NOT NULL,
            error_message       TEXT
        );
        CREATE TABLE IF NOT EXISTS llm_calls (
            call_id             INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id              INTEGER NOT NULL REFERENCES runs(run_id),
            model               TEXT NOT NULL,
            purpose             TEXT NOT NULL,
            prompt_version      TEXT,
            latency_ms          INTEGER,
            prompt_tokens       INTEGER,
            completion_tokens   INTEGER,
            schema_failure      INTEGER NOT NULL DEFAULT 0,
            retry_count         INTEGER NOT NULL DEFAULT 0,
            error_type          TEXT,
            error_message       TEXT,
            created_at          TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_llm_calls_run_id
            ON llm_calls (run_id);
    """)
    _ensure_column(conn, "runs", "articles_returned", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "claims_saved", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "story_match_verifications", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "story_match_accepts", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "story_match_rejections", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "llm_errors_count", "INTEGER DEFAULT 0")


def _ensure_column(conn, table, column, definition):
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _json_args(cli_args):
    if hasattr(cli_args, "__dict__"):
        value = vars(cli_args)
    elif isinstance(cli_args, dict):
        value = cli_args
    else:
        value = {"value": str(cli_args)}
    return json.dumps(value, sort_keys=True, default=str)


def _git_sha():
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except Exception:
        return None
    sha = result.stdout.strip()
    return sha or None


def start_run(cli_args, run_date=None):
    conn = _get_db()
    try:
        with conn:
            cur = conn.execute(
                """
                INSERT INTO runs (started_at, run_date, cli_args, git_sha, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (_utc_now(), run_date, _json_args(cli_args), _git_sha(), "running"),
            )
            return cur.lastrowid
    finally:
        conn.close()


def set_current_run_id(run_id):
    _CURRENT_RUN_ID.set(run_id)
    _LAST_LLM_CALL_ID.set(None)


def clear_current_run_id():
    _CURRENT_RUN_ID.set(None)
    _LAST_LLM_CALL_ID.set(None)


def current_run_id():
    return _CURRENT_RUN_ID.get()


def update_run_totals(run_id=None, **totals):
    run_id = current_run_id() if run_id is None else run_id
    if run_id is None:
        return

    fields = {
        key: int(value)
        for key, value in totals.items()
        if key in RUN_TOTAL_COLUMNS and value is not None
    }
    if not fields:
        return

    assignments = ", ".join(f"{key} = ?" for key in fields)
    params = list(fields.values()) + [run_id]
    conn = _get_db()
    try:
        with conn:
            conn.execute(
                f"UPDATE runs SET {assignments} WHERE run_id = ?",
                params,
            )
    finally:
        conn.close()


def increment_cache_hits(count=1, run_id=None):
    run_id = current_run_id() if run_id is None else run_id
    if run_id is None or count <= 0:
        return
    conn = _get_db()
    try:
        with conn:
            conn.execute(
                """
                UPDATE runs
                SET llm_cache_hits = COALESCE(llm_cache_hits, 0) + ?
                WHERE run_id = ?
                """,
                (int(count), run_id),
            )
    finally:
        conn.close()


def _usage_value(usage, name):
    if usage is None:
        return None
    if isinstance(usage, dict):
        return usage.get(name)
    return getattr(usage, name, None)


def record_llm_call(
    *,
    model,
    purpose,
    prompt_version=None,
    latency_ms=None,
    usage=None,
    schema_failure=False,
    retry_count=0,
    error_type=None,
    error_message=None,
    run_id=None,
):
    run_id = current_run_id() if run_id is None else run_id
    if run_id is None:
        return None

    prompt_tokens = _usage_value(usage, "prompt_tokens")
    completion_tokens = _usage_value(usage, "completion_tokens")
    conn = _get_db()
    try:
        with conn:
            cur = conn.execute(
                """
                INSERT INTO llm_calls (
                    run_id, model, purpose, prompt_version, latency_ms,
                    prompt_tokens, completion_tokens, schema_failure,
                    retry_count, error_type, error_message, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    model,
                    purpose,
                    prompt_version,
                    latency_ms,
                    prompt_tokens,
                    completion_tokens,
                    1 if schema_failure else 0,
                    retry_count,
                    error_type,
                    error_message,
                    _utc_now(),
                ),
            )
            call_id = cur.lastrowid
    finally:
        conn.close()

    _LAST_LLM_CALL_ID.set(call_id)
    return call_id


def mark_last_call_schema_failure(error_message=None):
    call_id = _LAST_LLM_CALL_ID.get()
    mark_call_schema_failure(call_id, error_message)


def mark_call_schema_failure(call_id, error_message=None):
    if call_id is None:
        return
    conn = _get_db()
    try:
        with conn:
            conn.execute(
                """
                UPDATE llm_calls
                SET schema_failure = 1,
                    error_type = COALESCE(error_type, ?),
                    error_message = COALESCE(error_message, ?)
                WHERE call_id = ?
                """,
                ("schema", error_message, call_id),
            )
    finally:
        conn.close()


def _run_started_at(conn, run_id):
    row = conn.execute(
        "SELECT started_at FROM runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    return row["started_at"] if row else None


def _latency_ms_since(started_at):
    if not started_at:
        return None
    try:
        started = datetime.fromisoformat(started_at)
    except ValueError:
        return None
    return int((datetime.now(timezone.utc) - started).total_seconds() * 1000)


def finish_run(run_id, status="ok", error_message=None):
    conn = _get_db()
    try:
        with conn:
            aggregate = conn.execute(
                """
                SELECT
                    COUNT(*) AS llm_calls_count,
                    COALESCE(SUM(schema_failure), 0) AS schema_failures,
                    COALESCE(SUM(CASE WHEN error_type IS NOT NULL THEN 1 ELSE 0 END), 0) AS llm_errors_count,
                    COALESCE(SUM(retry_count), 0) AS retry_count,
                    COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) AS completion_tokens
                FROM llm_calls
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            total_latency_ms = _latency_ms_since(_run_started_at(conn, run_id))
            conn.execute(
                """
                UPDATE runs
                SET finished_at = ?,
                    llm_calls_count = ?,
                    llm_errors_count = ?,
                    schema_failures = ?,
                    retry_count = ?,
                    prompt_tokens = ?,
                    completion_tokens = ?,
                    total_latency_ms = ?,
                    status = ?,
                    error_message = ?
                WHERE run_id = ?
                """,
                (
                    _utc_now(),
                    aggregate["llm_calls_count"],
                    aggregate["llm_errors_count"],
                    aggregate["schema_failures"],
                    aggregate["retry_count"],
                    aggregate["prompt_tokens"],
                    aggregate["completion_tokens"],
                    total_latency_ms,
                    status,
                    str(error_message) if error_message else None,
                    run_id,
                ),
            )
    finally:
        conn.close()


def get_run_report_data(run_id):
    conn = _get_db()
    try:
        return conn.execute(
            """
            SELECT run_id, run_date, status, total_latency_ms,
                   articles_returned, claims_saved,
                   stories_touched, story_match_verifications,
                   story_match_accepts, story_match_rejections,
                   llm_calls_count, llm_cache_hits,
                   llm_errors_count, schema_failures, retry_count, prompt_tokens,
                   completion_tokens, error_message
            FROM runs
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
    finally:
        conn.close()


def pipeline_report(run_id):
    row = get_run_report_data(run_id)
    if row is None:
        return f"Run #{run_id} not found."

    seconds = (row["total_latency_ms"] or 0) / 1000
    lines = [
        f"Run #{row['run_id']} ({row['run_date'] or 'unknown date'}, {row['status']}, {seconds:.1f}s)",
        f"Articles returned:      {row['articles_returned'] or 0}",
        f"Claims saved:           {row['claims_saved'] or 0}",
        f"Stories touched:        {row['stories_touched'] or 0}",
        f"Story match checks:     {row['story_match_verifications'] or 0}",
        f"Story match accepted:   {row['story_match_accepts'] or 0}",
        f"Story match rejected:   {row['story_match_rejections'] or 0}",
        f"LLM calls:              {row['llm_calls_count'] or 0}",
        f"LLM errors:             {row['llm_errors_count'] or 0}",
        f"LLM cache hits:         {row['llm_cache_hits'] or 0}",
        f"Schema failures:        {row['schema_failures'] or 0}",
        f"Retries:                {row['retry_count'] or 0}",
        (
            "Tokens:                 "
            f"prompt {row['prompt_tokens'] or 0} / completion {row['completion_tokens'] or 0}"
        ),
    ]
    if row["error_message"]:
        lines.append(f"Error:                  {row['error_message']}")
    return "\n".join(lines)
