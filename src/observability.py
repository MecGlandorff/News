import json
import sqlite3
import subprocess
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

from src import pricing


DB_PATH = Path("data/stories.db")
RUN_ARTIFACTS_DIR = Path("run_artifacts")

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
    "duplicate_url_skips",
    "feed_fetch_failures",
    "article_text_fetch_successes",
    "article_text_fetch_failures",
    "claim_articles_extracted",
    "claim_articles_cached",
    "claim_invalid_dropped",
    "claim_extraction_failures",
    "claim_zero_results",
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
            duplicate_url_skips INTEGER DEFAULT 0,
            feed_fetch_failures INTEGER DEFAULT 0,
            article_text_fetch_successes INTEGER DEFAULT 0,
            article_text_fetch_failures INTEGER DEFAULT 0,
            claim_articles_extracted INTEGER DEFAULT 0,
            claim_articles_cached INTEGER DEFAULT 0,
            claim_invalid_dropped INTEGER DEFAULT 0,
            claim_extraction_failures INTEGER DEFAULT 0,
            claim_zero_results INTEGER DEFAULT 0,
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
    _ensure_column(conn, "runs", "duplicate_url_skips", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "feed_fetch_failures", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "article_text_fetch_successes", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "article_text_fetch_failures", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "claim_articles_extracted", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "claim_articles_cached", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "claim_invalid_dropped", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "claim_extraction_failures", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "claim_zero_results", "INTEGER DEFAULT 0")
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
                   duplicate_url_skips, feed_fetch_failures,
                   article_text_fetch_successes, article_text_fetch_failures,
                   claim_articles_extracted, claim_articles_cached,
                   claim_invalid_dropped, claim_extraction_failures,
                   claim_zero_results,
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


def llm_cost_summary(run_id):
    conn = _get_db()
    try:
        rows = conn.execute(
            """
            SELECT purpose, model,
                   COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                   COUNT(*) AS calls,
                   COALESCE(SUM(latency_ms), 0) AS latency_ms
            FROM llm_calls
            WHERE run_id = ?
            GROUP BY purpose, model
            ORDER BY purpose, model
            """,
            (run_id,),
        ).fetchall()
    finally:
        conn.close()

    by_purpose = {}
    unpriced_models = set()
    total = 0.0
    for row in rows:
        cost = pricing.estimate_llm_cost_eur(
            row["model"],
            row["prompt_tokens"],
            row["completion_tokens"],
        )
        if cost is None:
            unpriced_models.add(row["model"])
        else:
            total += cost
        purpose = by_purpose.setdefault(row["purpose"], {
            "purpose": row["purpose"],
            "calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "latency_ms": 0,
            "cost_eur": 0.0,
            "unpriced_models": set(),
        })
        purpose["calls"] += row["calls"]
        purpose["prompt_tokens"] += row["prompt_tokens"]
        purpose["completion_tokens"] += row["completion_tokens"]
        purpose["latency_ms"] += row["latency_ms"]
        if cost is None:
            purpose["unpriced_models"].add(row["model"])
        else:
            purpose["cost_eur"] += cost

    return {
        "total_cost_eur": total if not unpriced_models else None,
        "priced_cost_eur": total,
        "unpriced_models": sorted(unpriced_models),
        "by_purpose": [
            {
                **value,
                "unpriced_models": sorted(value["unpriced_models"]),
            }
            for value in by_purpose.values()
        ],
    }


def pipeline_report(run_id):
    row = get_run_report_data(run_id)
    if row is None:
        return f"Run #{run_id} not found."

    seconds = (row["total_latency_ms"] or 0) / 1000
    cost = llm_cost_summary(run_id)
    lines = [
        f"Run #{row['run_id']} ({row['run_date'] or 'unknown date'}, {row['status']}, {seconds:.1f}s)",
        f"Articles returned:      {row['articles_returned'] or 0}",
        f"Duplicate URLs skipped: {row['duplicate_url_skips'] or 0}",
        f"Feed fetch failures:    {row['feed_fetch_failures'] or 0}",
        f"Article text fetched:   {row['article_text_fetch_successes'] or 0}",
        f"Article text failures:  {row['article_text_fetch_failures'] or 0}",
        f"Claims saved:           {row['claims_saved'] or 0}",
        f"Claims extracted:       {row['claim_articles_extracted'] or 0}",
        f"Claims cached:          {row['claim_articles_cached'] or 0}",
        f"Claims invalid:         {row['claim_invalid_dropped'] or 0}",
        f"Claim failures:         {row['claim_extraction_failures'] or 0}",
        f"Zero-claim results:     {row['claim_zero_results'] or 0}",
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
    if cost["unpriced_models"]:
        lines.append(
            "Estimated cost:         "
            f"{pricing.format_eur(cost['priced_cost_eur'])} priced; "
            f"unpriced models: {', '.join(cost['unpriced_models'])}"
        )
    else:
        lines.append(f"Estimated cost:         {pricing.format_eur(cost['total_cost_eur'])}")
    for item in cost["by_purpose"]:
        suffix = ""
        if item["unpriced_models"]:
            suffix = f" (unpriced: {', '.join(item['unpriced_models'])})"
        lines.append(
            f"  {item['purpose']}: "
            f"{item['calls']} calls, "
            f"tokens {item['prompt_tokens']}/{item['completion_tokens']}, "
            f"latency {(item['latency_ms'] or 0) / 1000:.1f}s, "
            f"{pricing.format_eur(item['cost_eur'])}{suffix}"
        )
    if row["error_message"]:
        lines.append(f"Error:                  {row['error_message']}")
    return "\n".join(lines)


def _markdown_number(value):
    return f"{int(value or 0):,}"


def _markdown_cost(value):
    return pricing.format_eur(value)


def _run_artifact_name(row):
    run_date = row["run_date"] or "unknown-date"
    return f"run_{run_date}.md"


def run_report_markdown(run_id):
    row = get_run_report_data(run_id)
    if row is None:
        return f"# Run Report\n\nRun #{run_id} was not found.\n"

    seconds = (row["total_latency_ms"] or 0) / 1000
    cost = llm_cost_summary(run_id)
    lines = [
        f"# Run Report: {row['run_date'] or 'unknown date'}",
        "",
        "| Field | Value |",
        "|---|---:|",
        f"| Run | #{row['run_id']} |",
        f"| Date | {row['run_date'] or 'unknown date'} |",
        f"| Status | {row['status']} |",
        f"| Duration | {seconds:.1f}s |",
        "",
        "## Pipeline Totals",
        "",
        "| Metric | Count |",
        "|---|---:|",
        f"| Articles returned | {_markdown_number(row['articles_returned'])} |",
        f"| Duplicate URLs skipped | {_markdown_number(row['duplicate_url_skips'])} |",
        f"| Feed fetch failures | {_markdown_number(row['feed_fetch_failures'])} |",
        f"| Article text fetched | {_markdown_number(row['article_text_fetch_successes'])} |",
        f"| Article text failures | {_markdown_number(row['article_text_fetch_failures'])} |",
        f"| Claims saved | {_markdown_number(row['claims_saved'])} |",
        f"| Claims extracted | {_markdown_number(row['claim_articles_extracted'])} |",
        f"| Claims cached | {_markdown_number(row['claim_articles_cached'])} |",
        f"| Claims invalid | {_markdown_number(row['claim_invalid_dropped'])} |",
        f"| Claim failures | {_markdown_number(row['claim_extraction_failures'])} |",
        f"| Zero-claim results | {_markdown_number(row['claim_zero_results'])} |",
        f"| Stories touched | {_markdown_number(row['stories_touched'])} |",
        f"| Story match checks | {_markdown_number(row['story_match_verifications'])} |",
        f"| Story match accepted | {_markdown_number(row['story_match_accepts'])} |",
        f"| Story match rejected | {_markdown_number(row['story_match_rejections'])} |",
        "",
        "## LLM Totals",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| LLM calls | {_markdown_number(row['llm_calls_count'])} |",
        f"| LLM errors | {_markdown_number(row['llm_errors_count'])} |",
        f"| LLM cache hits | {_markdown_number(row['llm_cache_hits'])} |",
        f"| Schema failures | {_markdown_number(row['schema_failures'])} |",
        f"| Retries | {_markdown_number(row['retry_count'])} |",
        f"| Prompt tokens | {_markdown_number(row['prompt_tokens'])} |",
        f"| Completion tokens | {_markdown_number(row['completion_tokens'])} |",
    ]
    if cost["unpriced_models"]:
        lines.append(
            "| Estimated cost | "
            f"{_markdown_cost(cost['priced_cost_eur'])} priced; "
            f"unpriced models: {', '.join(cost['unpriced_models'])} |"
        )
    else:
        lines.append(f"| Estimated cost | {_markdown_cost(cost['total_cost_eur'])} |")

    lines.extend([
        "",
        "## LLM Calls By Purpose",
        "",
        "| Purpose | Calls | Prompt Tokens | Completion Tokens | Latency | Estimated Cost |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for item in cost["by_purpose"]:
        suffix = ""
        if item["unpriced_models"]:
            suffix = f" (unpriced: {', '.join(item['unpriced_models'])})"
        lines.append(
            f"| {item['purpose']} | "
            f"{_markdown_number(item['calls'])} | "
            f"{_markdown_number(item['prompt_tokens'])} | "
            f"{_markdown_number(item['completion_tokens'])} | "
            f"{(item['latency_ms'] or 0) / 1000:.1f}s | "
            f"{_markdown_cost(item['cost_eur'])}{suffix} |"
        )
    if not cost["by_purpose"]:
        lines.append("| None | 0 | 0 | 0 | 0.0s | EUR 0.0000 |")

    if row["error_message"]:
        lines.extend([
            "",
            "## Error",
            "",
            str(row["error_message"]),
        ])

    return "\n".join(lines) + "\n"


def write_run_report_artifact(run_id, output_dir=None):
    row = get_run_report_data(run_id)
    if row is None:
        return None
    output_dir = RUN_ARTIFACTS_DIR if output_dir is None else Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / _run_artifact_name(row)
    output_path.write_text(run_report_markdown(run_id), encoding="utf-8")
    return output_path
