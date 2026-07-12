import json
import subprocess
from datetime import datetime, timezone

from src.observability.database import get_db as _get_db
from src.observability.schema import RUN_TOTAL_COLUMNS
from src.observability.state import current_run_id


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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
    except (OSError, subprocess.SubprocessError):
        return None
    sha = result.stdout.strip()
    return sha or None


def start_run(cli_args, run_date=None):
    conn = _get_db()
    try:
        with conn:
            conn.execute(
                """
                UPDATE runs
                SET status = 'abandoned',
                    finished_at = ?,
                    error_message = COALESCE(
                        error_message,
                        'Process ended before the run was finalized.'
                    )
                WHERE status = 'running' AND finished_at IS NULL
                """,
                (_utc_now(),),
            )
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


def increment_run_totals(run_id=None, **totals):
    run_id = current_run_id() if run_id is None else run_id
    if run_id is None:
        return

    fields = {
        key: int(value)
        for key, value in totals.items()
        if key in RUN_TOTAL_COLUMNS and value is not None and int(value) != 0
    }
    if not fields:
        return

    assignments = ", ".join(f"{key} = COALESCE({key}, 0) + ?" for key in fields)
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


def increment_cache_hits(count=1, run_id=None, *, layer="other", purpose=None):
    run_id = current_run_id() if run_id is None else run_id
    if run_id is None or count <= 0:
        return
    column = _cache_hit_column(layer, purpose)
    conn = _get_db()
    try:
        with conn:
            conn.execute(
                """
                UPDATE runs
                SET llm_cache_hits = COALESCE(llm_cache_hits, 0) + ?,
                    {column} = COALESCE({column}, 0) + ?
                WHERE run_id = ?
                """.format(column=column),
                (int(count), int(count), run_id),
            )
    finally:
        conn.close()


def _cache_hit_column(layer, purpose):
    if layer == "classification":
        return "classification_cache_hits"
    if layer == "claims":
        return "claim_cache_hits"
    if layer == "exact":
        if purpose == "claim_verifier":
            return "verifier_cache_hits"
        if purpose == "brief":
            return "briefing_cache_hits"
        if purpose in {
            "match-sameday",
            "match-crossday",
            "match-verify",
            "match-arc",
            "story-match-verify",
            "arc-assignment",
        }:
            return "matching_cache_hits"
    return "other_cache_hits"


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
                   story_developments_saved, story_parent_attachments,
                   story_arc_assignments, story_arc_attachments,
                   story_new_arcs,
                   story_new_parent_arcs, story_unmatched_new_stories,
                   duplicate_url_skips, feed_fetch_failures,
                   feed_items_outside_date_skipped,
                   feed_items_missing_timestamp_skipped,
                   feed_items_unparseable_timestamp_skipped,
                   feed_items_missing_timestamp_included,
                   feed_items_unparseable_timestamp_included,
                   article_text_fetch_successes, article_text_fetch_failures,
                   claim_articles_extracted, claim_articles_cached,
                   claim_invalid_dropped, claim_extraction_failures,
                   claim_zero_results,
                   claim_derivable_accepts, claim_verifier_calls,
                   claim_verifier_accepts, claim_verifier_rejects,
                   claim_content_truncations,
                   llm_calls_count, llm_cache_hits,
                   classification_cache_hits, claim_cache_hits,
                   verifier_cache_hits, matching_cache_hits,
                   briefing_cache_hits, other_cache_hits,
                   llm_errors_count, schema_failures, retry_count, prompt_tokens,
                   completion_tokens, error_message
            FROM runs
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
    finally:
        conn.close()
