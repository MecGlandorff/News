import json
import sqlite3
import subprocess
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

from src import pricing


DB_PATH = Path("data/stories.db")
RUN_ARTIFACTS_DIR = Path("run_artifacts")
AUDIT_SCORE_THRESHOLD = 450.0
AUDIT_SOURCE_THRESHOLD = 6
AUDIT_IMPORTANCE_THRESHOLD = 3.0
AUDIT_REVIEW_RELATIONSHIPS = {
    "same_story_arc",
    "direct_follow_up",
    "adjacent_topic",
    "broader_context",
}

_CURRENT_RUN_ID = ContextVar("current_run_id", default=None)
_LAST_LLM_CALL_ID = ContextVar("last_llm_call_id", default=None)

RUN_TOTAL_COLUMNS = {
    "articles_returned",
    "claims_saved",
    "stories_touched",
    "llm_cache_hits",
    "classification_cache_hits",
    "claim_cache_hits",
    "verifier_cache_hits",
    "matching_cache_hits",
    "briefing_cache_hits",
    "other_cache_hits",
    "story_match_verifications",
    "story_match_accepts",
    "story_match_rejections",
    "story_developments_saved",
    "story_parent_attachments",
    "story_arc_assignments",
    "story_arc_attachments",
    "story_new_arcs",
    "story_new_parent_arcs",
    "story_unmatched_new_stories",
    "duplicate_url_skips",
    "feed_fetch_failures",
    "feed_items_outside_date_skipped",
    "feed_items_missing_timestamp_skipped",
    "feed_items_unparseable_timestamp_skipped",
    "feed_items_missing_timestamp_included",
    "feed_items_unparseable_timestamp_included",
    "article_text_fetch_successes",
    "article_text_fetch_failures",
    "claim_articles_extracted",
    "claim_articles_cached",
    "claim_invalid_dropped",
    "claim_extraction_failures",
    "claim_zero_results",
    "claim_derivable_accepts",
    "claim_verifier_calls",
    "claim_verifier_accepts",
    "claim_verifier_rejects",
    "claim_content_truncations",
}


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
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
            story_developments_saved INTEGER DEFAULT 0,
            story_parent_attachments INTEGER DEFAULT 0,
            story_arc_assignments INTEGER DEFAULT 0,
            story_arc_attachments INTEGER DEFAULT 0,
            story_new_arcs INTEGER DEFAULT 0,
            story_new_parent_arcs INTEGER DEFAULT 0,
            story_unmatched_new_stories INTEGER DEFAULT 0,
            duplicate_url_skips INTEGER DEFAULT 0,
            feed_fetch_failures INTEGER DEFAULT 0,
            feed_items_outside_date_skipped INTEGER DEFAULT 0,
            feed_items_missing_timestamp_skipped INTEGER DEFAULT 0,
            feed_items_unparseable_timestamp_skipped INTEGER DEFAULT 0,
            feed_items_missing_timestamp_included INTEGER DEFAULT 0,
            feed_items_unparseable_timestamp_included INTEGER DEFAULT 0,
            article_text_fetch_successes INTEGER DEFAULT 0,
            article_text_fetch_failures INTEGER DEFAULT 0,
            claim_articles_extracted INTEGER DEFAULT 0,
            claim_articles_cached INTEGER DEFAULT 0,
            claim_invalid_dropped INTEGER DEFAULT 0,
            claim_extraction_failures INTEGER DEFAULT 0,
            claim_zero_results INTEGER DEFAULT 0,
            claim_derivable_accepts INTEGER DEFAULT 0,
            claim_verifier_calls INTEGER DEFAULT 0,
            claim_verifier_accepts INTEGER DEFAULT 0,
            claim_verifier_rejects INTEGER DEFAULT 0,
            claim_content_truncations INTEGER DEFAULT 0,
            llm_calls_count     INTEGER DEFAULT 0,
            llm_errors_count    INTEGER DEFAULT 0,
            llm_cache_hits      INTEGER DEFAULT 0,
            classification_cache_hits INTEGER DEFAULT 0,
            claim_cache_hits    INTEGER DEFAULT 0,
            verifier_cache_hits INTEGER DEFAULT 0,
            matching_cache_hits INTEGER DEFAULT 0,
            briefing_cache_hits INTEGER DEFAULT 0,
            other_cache_hits    INTEGER DEFAULT 0,
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
    _ensure_column(conn, "runs", "story_developments_saved", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "story_parent_attachments", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "story_arc_assignments", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "story_arc_attachments", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "story_new_arcs", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "story_new_parent_arcs", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "story_unmatched_new_stories", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "duplicate_url_skips", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "feed_fetch_failures", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "feed_items_outside_date_skipped", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "feed_items_missing_timestamp_skipped", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "feed_items_unparseable_timestamp_skipped", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "feed_items_missing_timestamp_included", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "feed_items_unparseable_timestamp_included", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "article_text_fetch_successes", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "article_text_fetch_failures", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "claim_articles_extracted", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "claim_articles_cached", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "claim_invalid_dropped", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "claim_extraction_failures", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "claim_zero_results", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "claim_derivable_accepts", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "claim_verifier_calls", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "claim_verifier_accepts", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "claim_verifier_rejects", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "claim_content_truncations", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "llm_errors_count", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "classification_cache_hits", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "claim_cache_hits", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "verifier_cache_hits", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "matching_cache_hits", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "briefing_cache_hits", "INTEGER DEFAULT 0")
    _ensure_column(conn, "runs", "other_cache_hits", "INTEGER DEFAULT 0")


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


def _table_exists(conn, table):
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table,),
    ).fetchone()
    return row is not None


def _run_cli_args(conn, run_id):
    row = conn.execute(
        "SELECT cli_args FROM runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if not row:
        return {}
    try:
        value = json.loads(row["cli_args"] or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _top_developments_from_args(cli_args):
    try:
        return int(cli_args.get("top_developments") or 3)
    except (TypeError, ValueError):
        return 3


def _use_assignment_history(conn, run_id):
    # Once the run-scoped table exists, an empty result means this run tracked
    # no occurrences. Falling back to date-scoped projections would leak rows
    # from another rerun of the same editorial date into this run's report.
    return run_id is not None and _table_exists(conn, "occurrence_assignment_history")


def _tracked_articles_for_audit(conn, run_date, run_id=None):
    if _use_assignment_history(conn, run_id):
        rows = conn.execute(
            """
            SELECT o.article_id AS id, o.source_id, o.source, o.title, o.url,
                   o.published_at, COALESCE(h.importance, c.importance) AS importance,
                   o.description, h.story_id, h.canonical_label,
                   COALESCE(h.theme, c.theme) AS theme,
                   COALESCE(h.story_label, c.story_label) AS story_label,
                   h.development_status
            FROM occurrence_assignment_history h
            JOIN article_occurrences o ON o.occurrence_id = h.occurrence_id
            JOIN occurrence_classifications c ON c.occurrence_id = h.occurrence_id
            WHERE h.run_id = ?
            ORDER BY o.occurrence_id
            """,
            (run_id,),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "source_id": row["source_id"],
                "source": row["source"],
                "title": row["title"] or "Untitled",
                "description": row["description"] or "",
                "url": row["url"],
                "published_at": row["published_at"],
                "importance": int(row["importance"] or 0),
                "story_id": row["story_id"],
                "canonical_label": row["canonical_label"],
                "story_label": row["story_label"],
                "theme": row["theme"] or "Other",
                "trend": (
                    "new"
                    if row["development_status"] in {"new_parent", "new_child"}
                    else "steady"
                ),
            }
            for row in rows
        ]
    required = {"articles", "stories"}
    if not all(_table_exists(conn, table) for table in required):
        return []

    has_classifications = _table_exists(conn, "article_classifications")
    classification_theme = "c.theme" if has_classifications else "NULL"
    classification_label = "c.story_label" if has_classifications else "NULL"
    classification_join = (
        "LEFT JOIN article_classifications c ON c.article_id = a.id"
        if has_classifications else ""
    )
    rows = conn.execute(
        f"""
        SELECT a.id, a.source, a.title, a.url, a.published_at,
               a.importance, a.description, a.story_id,
               s.canonical_label, s.theme AS story_theme, s.first_seen,
               {classification_theme} AS classification_theme,
               {classification_label} AS classification_label
        FROM articles a
        JOIN stories s ON s.story_id = a.story_id
        {classification_join}
        WHERE a.date = ?
        """,
        (run_date,),
    ).fetchall()

    tracked = []
    for row in rows:
        label = row["classification_label"] or row["canonical_label"]
        theme = row["classification_theme"] or row["story_theme"] or "Other"
        tracked.append({
            "id": row["id"],
            "source": row["source"],
            "title": row["title"] or "Untitled",
            "description": row["description"] or "",
            "url": row["url"],
            "published_at": row["published_at"],
            "importance": int(row["importance"] or 0),
            "story_id": row["story_id"],
            "canonical_label": row["canonical_label"],
            "story_label": label,
            "theme": theme,
            "trend": "new" if row["first_seen"] == run_date else "steady",
        })
    return tracked


def _audit_story_item(story, score_value):
    from src import briefing_selection

    return {
        "story_id": story.get("story_id"),
        "label": story["canonical_label"],
        "theme": story["theme"],
        "source_count": story["source_count"],
        "importance_avg": round(float(story["importance_avg"] or 0), 2),
        "score": round(float(score_value or 0), 1),
        "selection_score": round(float(briefing_selection.selection_score(story) or 0), 1),
        "selection_penalty": round(float(briefing_selection.selection_penalty(story) or 0), 1),
        "penalty_reasons": briefing_selection.penalty_reasons(story),
    }


def _high_signal_not_displayed(conn, run_date, top_developments, limit, run_id=None):
    tracked = _tracked_articles_for_audit(conn, run_date, run_id=run_id)
    if not tracked:
        return []

    from src import briefing_selection

    selected = briefing_selection.select_story_sections(tracked, n=top_developments)
    displayed = {
        story["canonical_label"]
        for story in selected.get("display_stories", [])
    }
    candidates = []
    for story in selected.get("stories", []):
        score_value = briefing_selection.score(story)
        is_high_score = score_value >= AUDIT_SCORE_THRESHOLD
        is_broad_pickup = (
            story["source_count"] >= AUDIT_SOURCE_THRESHOLD
            and story["importance_avg"] >= AUDIT_IMPORTANCE_THRESHOLD
        )
        if story["canonical_label"] not in displayed and (is_high_score or is_broad_pickup):
            candidates.append(_audit_story_item(story, score_value))
    return candidates[:limit]


def _high_signal_new_parent_arcs(conn, run_date, limit, run_id=None):
    if _use_assignment_history(conn, run_id):
        rows = conn.execute(
            """
            SELECT h.story_id, h.canonical_label,
                   COALESCE(h.theme, c.theme) AS theme,
                   h.development_label,
                   COUNT(DISTINCT COALESCE(CAST(o.source_id AS TEXT), lower(o.source)))
                       AS source_count,
                   COUNT(*) AS article_count,
                   AVG(COALESCE(h.importance, c.importance)) AS importance_avg,
                   ((AVG(COALESCE(h.importance, c.importance)) * 100.0) +
                    (COUNT(DISTINCT COALESCE(CAST(o.source_id AS TEXT), lower(o.source))) * 12.0))
                       AS score
            FROM occurrence_assignment_history h
            JOIN article_occurrences o ON o.occurrence_id = h.occurrence_id
            JOIN occurrence_classifications c ON c.occurrence_id = h.occurrence_id
            WHERE h.run_id = ? AND h.development_status = 'new_parent'
            GROUP BY h.story_id, h.canonical_label,
                     COALESCE(h.theme, c.theme), h.development_label
            HAVING score >= ? OR (source_count >= ? AND importance_avg >= ?)
            ORDER BY score DESC, source_count DESC, h.development_label
            LIMIT ?
            """,
            (
                run_id,
                AUDIT_SCORE_THRESHOLD,
                AUDIT_SOURCE_THRESHOLD,
                AUDIT_IMPORTANCE_THRESHOLD,
                limit,
            ),
        ).fetchall()
        return [
            {
                "story_id": row["story_id"],
                "label": row["canonical_label"],
                "development_label": row["development_label"],
                "theme": row["theme"] or "Other",
                "source_count": int(row["source_count"] or 0),
                "article_count": int(row["article_count"] or 0),
                "importance_avg": round(float(row["importance_avg"] or 0), 2),
                "score": round(float(row["score"] or 0), 1),
            }
            for row in rows
        ]
    if not all(_table_exists(conn, table) for table in {"story_developments", "stories"}):
        return []
    rows = conn.execute(
        """
        SELECT d.story_id, s.canonical_label, s.theme, d.development_label,
               d.source_count, d.article_count, d.importance_avg,
               ((COALESCE(d.importance_avg, 0) * 100.0) + (COALESCE(d.source_count, 0) * 12.0)) AS score
        FROM story_developments d
        JOIN stories s ON s.story_id = d.story_id
        WHERE d.date = ? AND d.development_status = 'new_parent'
          AND (
              ((COALESCE(d.importance_avg, 0) * 100.0) + (COALESCE(d.source_count, 0) * 12.0)) >= ?
              OR (COALESCE(d.source_count, 0) >= ? AND COALESCE(d.importance_avg, 0) >= ?)
          )
        ORDER BY score DESC, d.source_count DESC, d.development_label
        LIMIT ?
        """,
        (
            run_date,
            AUDIT_SCORE_THRESHOLD,
            AUDIT_SOURCE_THRESHOLD,
            AUDIT_IMPORTANCE_THRESHOLD,
            limit,
        ),
    ).fetchall()
    return [
        {
            "story_id": row["story_id"],
            "label": row["canonical_label"],
            "development_label": row["development_label"],
            "theme": row["theme"] or "Other",
            "source_count": int(row["source_count"] or 0),
            "article_count": int(row["article_count"] or 0),
            "importance_avg": round(float(row["importance_avg"] or 0), 2),
            "score": round(float(row["score"] or 0), 1),
        }
        for row in rows
    ]


def _new_parent_arcs_with_candidates(conn, run_date, limit, run_id=None):
    if _use_assignment_history(conn, run_id):
        if not _table_exists(conn, "story_match_decisions"):
            return []
        placeholders = ", ".join("?" for _ in AUDIT_REVIEW_RELATIONSHIPS)
        rows = conn.execute(
            f"""
            WITH parents AS (
                SELECT h.story_id, h.development_label,
                       COUNT(DISTINCT COALESCE(
                           CAST(o.source_id AS TEXT), lower(o.source)
                       )) AS source_count,
                       AVG(COALESCE(h.importance, c.importance)) AS importance_avg
                FROM occurrence_assignment_history h
                JOIN article_occurrences o ON o.occurrence_id = h.occurrence_id
                JOIN occurrence_classifications c ON c.occurrence_id = h.occurrence_id
                WHERE h.run_id = ? AND h.development_status = 'new_parent'
                GROUP BY h.story_id, h.development_label
            )
            SELECT p.story_id, p.development_label, p.source_count,
                   p.importance_avg, m.candidate_label, m.relationship,
                   m.confidence, m.reject_reason
            FROM parents p
            JOIN story_match_decisions m
              ON m.run_id = ?
             AND lower(m.today_label) = lower(p.development_label)
            WHERE m.accepted = 0
              AND lower(COALESCE(m.relationship, '')) IN ({placeholders})
              AND lower(COALESCE(m.confidence, '')) IN ('medium', 'high')
            ORDER BY
              CASE lower(COALESCE(m.confidence, ''))
                WHEN 'high' THEN 0
                WHEN 'medium' THEN 1
                ELSE 2
              END,
              p.source_count DESC,
              p.importance_avg DESC,
              p.development_label
            LIMIT ?
            """,
            [run_id, run_id, *sorted(AUDIT_REVIEW_RELATIONSHIPS), limit],
        ).fetchall()
        return [
            {
                "story_id": row["story_id"],
                "label": row["development_label"],
                "candidate_label": row["candidate_label"],
                "relationship": row["relationship"],
                "confidence": row["confidence"],
                "source_count": int(row["source_count"] or 0),
                "importance_avg": round(float(row["importance_avg"] or 0), 2),
                "reject_reason": row["reject_reason"] or "",
            }
            for row in rows
        ]

    if not all(
        _table_exists(conn, table)
        for table in {"story_developments", "story_match_decisions"}
    ):
        return []
    placeholders = ", ".join("?" for _ in AUDIT_REVIEW_RELATIONSHIPS)
    rows = conn.execute(
        f"""
        SELECT d.story_id, d.development_label, d.source_count,
               d.importance_avg, m.candidate_label, m.relationship,
               m.confidence, m.reject_reason
        FROM story_developments d
        JOIN story_match_decisions m
          ON m.run_date = d.date
         AND lower(m.today_label) = lower(d.development_label)
        WHERE d.date = ?
          AND (? IS NULL OR m.run_id = ?)
          AND d.development_status = 'new_parent'
          AND m.accepted = 0
          AND lower(COALESCE(m.relationship, '')) IN ({placeholders})
          AND lower(COALESCE(m.confidence, '')) IN ('medium', 'high')
        ORDER BY
          CASE lower(COALESCE(m.confidence, ''))
            WHEN 'high' THEN 0
            WHEN 'medium' THEN 1
            ELSE 2
          END,
          d.source_count DESC,
          d.importance_avg DESC,
          d.development_label
        LIMIT ?
        """,
        [run_date, run_id, run_id, *sorted(AUDIT_REVIEW_RELATIONSHIPS), limit],
    ).fetchall()
    return [
        {
            "story_id": row["story_id"],
            "label": row["development_label"],
            "candidate_label": row["candidate_label"],
            "relationship": row["relationship"],
            "confidence": row["confidence"],
            "source_count": int(row["source_count"] or 0),
            "importance_avg": round(float(row["importance_avg"] or 0), 2),
            "reject_reason": row["reject_reason"] or "",
        }
        for row in rows
    ]


def _rejected_related_matches(conn, run_date, limit, run_id=None):
    if not _table_exists(conn, "story_match_decisions"):
        return []
    placeholders = ", ".join("?" for _ in AUDIT_REVIEW_RELATIONSHIPS)
    rows = conn.execute(
        f"""
        SELECT today_label, candidate_label, relationship, confidence,
               reject_reason, continuity_evidence
        FROM story_match_decisions
        WHERE ((? IS NOT NULL AND run_id = ?) OR (? IS NULL AND run_date = ?))
          AND accepted = 0
          AND lower(COALESCE(relationship, '')) IN ({placeholders})
          AND lower(COALESCE(confidence, '')) IN ('medium', 'high')
        ORDER BY
          CASE lower(COALESCE(confidence, ''))
            WHEN 'high' THEN 0
            WHEN 'medium' THEN 1
            ELSE 2
          END,
          today_label,
          candidate_label
        LIMIT ?
        """,
        [run_id, run_id, run_id, run_date, *sorted(AUDIT_REVIEW_RELATIONSHIPS), limit],
    ).fetchall()
    return [
        {
            "today_label": row["today_label"],
            "candidate_label": row["candidate_label"],
            "relationship": row["relationship"],
            "confidence": row["confidence"],
            "reject_reason": row["reject_reason"] or "",
            "continuity_evidence": row["continuity_evidence"] or "",
        }
        for row in rows
    ]


def _arc_attachments_review(conn, run_date, limit, run_id=None):
    required = {"story_arc_decisions", "story_arcs", "stories"}
    if not all(_table_exists(conn, table) for table in required):
        return []
    rows = conn.execute(
        """
        SELECT d.today_label, d.arc_id, d.candidates, d.relationship,
               d.confidence, a.canonical_label AS arc_label,
               (SELECT COUNT(*) FROM stories s WHERE s.arc_id = d.arc_id) AS arc_child_count
        FROM story_arc_decisions d
        LEFT JOIN story_arcs a ON a.arc_id = d.arc_id
        WHERE ((? IS NOT NULL AND d.run_id = ?) OR (? IS NULL AND d.run_date = ?))
          AND d.accepted = 1
        ORDER BY arc_child_count DESC, d.today_label
        LIMIT ?
        """,
        (run_id, run_id, run_id, run_date, limit),
    ).fetchall()
    items = []
    for row in rows:
        chosen_score = None
        try:
            for candidate in json.loads(row["candidates"] or "[]"):
                if candidate.get("arc_id") == row["arc_id"]:
                    chosen_score = candidate.get("score")
                    break
        except (TypeError, ValueError):
            chosen_score = None
        items.append({
            "today_label": row["today_label"],
            "arc_id": row["arc_id"],
            "arc_label": row["arc_label"] or "",
            "relationship": row["relationship"],
            "confidence": row["confidence"],
            "chosen_score": chosen_score,
            "arc_child_count": int(row["arc_child_count"] or 0),
        })
    return items


def _rejected_arc_decisions(conn, run_date, limit, run_id=None):
    required = {"story_arc_decisions", "story_arcs"}
    if not all(_table_exists(conn, table) for table in required):
        return []
    rows = conn.execute(
        """
        SELECT d.today_label, d.arc_id, d.relationship, d.confidence,
               d.reject_reason, d.continuity_evidence,
               a.canonical_label AS proposed_arc_label
        FROM story_arc_decisions d
        LEFT JOIN story_arcs a ON a.arc_id = d.arc_id
        WHERE ((? IS NOT NULL AND d.run_id = ?) OR (? IS NULL AND d.run_date = ?))
          AND d.accepted = 0
          AND lower(COALESCE(d.confidence, '')) IN ('medium', 'high')
        ORDER BY
          CASE lower(COALESCE(d.confidence, ''))
            WHEN 'high' THEN 0
            WHEN 'medium' THEN 1
            ELSE 2
          END,
          d.today_label
        LIMIT ?
        """,
        (run_id, run_id, run_id, run_date, limit),
    ).fetchall()
    return [
        {
            "today_label": row["today_label"],
            "arc_id": row["arc_id"],
            "proposed_arc_label": row["proposed_arc_label"] or "",
            "relationship": row["relationship"],
            "confidence": row["confidence"],
            "reject_reason": row["reject_reason"] or "",
            "continuity_evidence": row["continuity_evidence"] or "",
        }
        for row in rows
    ]


def novelty_audit(run_id, limit=5):
    row = get_run_report_data(run_id)
    if row is None or not row["run_date"]:
        return {
            "run_date": None,
            "new_parent_ratio": None,
            "high_signal_not_displayed": [],
            "high_signal_new_parent_arcs": [],
            "new_parent_arcs_with_candidates": [],
            "rejected_related_matches": [],
            "arc_attachments_review": [],
            "rejected_arc_decisions": [],
        }

    conn = _get_db()
    try:
        cli_args = _run_cli_args(conn, run_id)
        top_developments = _top_developments_from_args(cli_args)
        developments = int(row["story_developments_saved"] or 0)
        new_parent_arcs = int(row["story_new_parent_arcs"] or 0)
        ratio = None
        if developments:
            ratio = new_parent_arcs / developments
        return {
            "run_date": row["run_date"],
            "new_parent_ratio": ratio,
            "new_parent_arcs": new_parent_arcs,
            "developments": developments,
            "high_signal_not_displayed": _high_signal_not_displayed(
                conn,
                row["run_date"],
                top_developments,
                limit,
                run_id=run_id,
            ),
            "high_signal_new_parent_arcs": _high_signal_new_parent_arcs(
                conn,
                row["run_date"],
                limit,
                run_id=run_id,
            ),
            "new_parent_arcs_with_candidates": _new_parent_arcs_with_candidates(
                conn,
                row["run_date"],
                limit,
                run_id=run_id,
            ),
            "rejected_related_matches": _rejected_related_matches(
                conn,
                row["run_date"],
                limit,
                run_id=run_id,
            ),
            "arc_attachments_review": _arc_attachments_review(
                conn,
                row["run_date"],
                limit,
                run_id=run_id,
            ),
            "rejected_arc_decisions": _rejected_arc_decisions(
                conn,
                row["run_date"],
                limit,
                run_id=run_id,
            ),
        }
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


def _audit_ratio_line(audit):
    ratio = audit.get("new_parent_ratio")
    if ratio is None:
        return "New parent ratio:      n/a"
    return (
        "New parent ratio:      "
        f"{audit.get('new_parent_arcs', 0)}/{audit.get('developments', 0)} "
        f"({ratio * 100:.1f}%)"
    )


def _audit_story_line(item):
    penalty = ""
    if item.get("selection_penalty"):
        reasons = ", ".join(item.get("penalty_reasons") or ["selection penalty"])
        penalty = (
            f", adjusted {item['selection_score']:.1f}, "
            f"penalty {item['selection_penalty']:.1f} ({reasons})"
        )
    return (
        f"    - {item['label']} "
        f"({item['theme']}, score {item['score']:.1f}, "
        f"{item['source_count']} sources, importance {item['importance_avg']:.1f}"
        f"{penalty})"
    )


def _audit_new_parent_line(item):
    development = item.get("development_label") or item["label"]
    label = item["label"]
    if development != label:
        label = f"{label} / {development}"
    return (
        f"    - {label} "
        f"({item['theme']}, score {item['score']:.1f}, "
        f"{item['source_count']} sources, {item['article_count']} articles, "
        f"importance {item['importance_avg']:.1f})"
    )


def _audit_candidate_line(item):
    return (
        f"    - {item['label']} -> {item['candidate_label']} "
        f"({item['relationship']}, {item['confidence']})"
    )


def _audit_rejected_line(item):
    return (
        f"    - {item['today_label']} -> {item['candidate_label']} "
        f"({item['relationship']}, {item['confidence']})"
    )


def _audit_arc_attachment_line(item):
    score = "score n/a" if item.get("chosen_score") is None else f"score {item['chosen_score']}"
    arc = item["arc_label"] or f"arc {item['arc_id']}"
    return (
        f"    - {item['today_label']} -> {arc} "
        f"({item['relationship']}, {item['confidence']}, {score}, "
        f"{item['arc_child_count']} stories in arc)"
    )


def _audit_arc_rejected_line(item):
    if item["proposed_arc_label"]:
        target = item["proposed_arc_label"]
    elif item["arc_id"] is not None:
        target = f"arc {item['arc_id']}"
    else:
        target = "NEW_ARC"
    return (
        f"    - {item['today_label']} -> {target} "
        f"({item['relationship']}, {item['confidence']})"
    )


def novelty_audit_lines(run_id, limit=5):
    audit = novelty_audit(run_id, limit=limit)
    sections = [
        ("High-signal not displayed", audit["high_signal_not_displayed"], _audit_story_line),
        ("High-signal new parent arcs", audit["high_signal_new_parent_arcs"], _audit_new_parent_line),
        ("New parent arcs with prior candidates", audit["new_parent_arcs_with_candidates"], _audit_candidate_line),
        ("Rejected related matches", audit["rejected_related_matches"], _audit_rejected_line),
        ("Arc attachments to review", audit["arc_attachments_review"], _audit_arc_attachment_line),
        ("Rejected arc decisions", audit["rejected_arc_decisions"], _audit_arc_rejected_line),
    ]

    lines = ["Novelty audit:", _audit_ratio_line(audit)]
    for title, items, formatter in sections:
        lines.append(f"{title}: {len(items)}")
        for item in items:
            lines.append(formatter(item))
    return lines


def pipeline_report(run_id):
    row = get_run_report_data(run_id)
    if row is None:
        return f"Run #{run_id} not found."

    seconds = (row["total_latency_ms"] or 0) / 1000
    cost = llm_cost_summary(run_id)
    undated_included = (
        (row["feed_items_missing_timestamp_included"] or 0)
        + (row["feed_items_unparseable_timestamp_included"] or 0)
    )
    undated_skipped = (
        (row["feed_items_missing_timestamp_skipped"] or 0)
        + (row["feed_items_unparseable_timestamp_skipped"] or 0)
    )
    lines = [
        f"Run #{row['run_id']} ({row['run_date'] or 'unknown date'}, {row['status']}, {seconds:.1f}s)",
        f"Articles returned:      {row['articles_returned'] or 0}",
        f"Duplicate URLs skipped: {row['duplicate_url_skips'] or 0}",
        f"Feed fetch failures:    {row['feed_fetch_failures'] or 0}",
        f"Outside date skipped:   {row['feed_items_outside_date_skipped'] or 0}",
        (
            "Undated included:      "
            f"{undated_included} "
            f"({row['feed_items_missing_timestamp_included'] or 0} missing, "
            f"{row['feed_items_unparseable_timestamp_included'] or 0} unparseable)"
        ),
        (
            "Undated skipped:       "
            f"{undated_skipped} "
            f"({row['feed_items_missing_timestamp_skipped'] or 0} missing, "
            f"{row['feed_items_unparseable_timestamp_skipped'] or 0} unparseable)"
        ),
        f"Article text fetched:   {row['article_text_fetch_successes'] or 0}",
        f"Article text failures:  {row['article_text_fetch_failures'] or 0}",
        f"Claims saved:           {row['claims_saved'] or 0}",
        f"Claims extracted:       {row['claim_articles_extracted'] or 0}",
        f"Claims cached:          {row['claim_articles_cached'] or 0}",
        f"Claims invalid:         {row['claim_invalid_dropped'] or 0}",
        f"Claim failures:         {row['claim_extraction_failures'] or 0}",
        f"Zero-claim results:     {row['claim_zero_results'] or 0}",
        f"Claim cheap accepts:    {row['claim_derivable_accepts'] or 0}",
        f"Claim verifier calls:   {row['claim_verifier_calls'] or 0}",
        f"Claim verifier accepts: {row['claim_verifier_accepts'] or 0}",
        f"Claim verifier rejects: {row['claim_verifier_rejects'] or 0}",
        f"Claim input truncation:  {row['claim_content_truncations'] or 0}",
        f"Stories touched:        {row['stories_touched'] or 0}",
        f"Developments saved:     {row['story_developments_saved'] or 0}",
        f"Parent attachments:     {row['story_parent_attachments'] or 0}",
        f"Arc assignments:        {row['story_arc_assignments'] or 0}",
        f"Arc attachments:        {row['story_arc_attachments'] or 0}",
        f"New arcs:               {row['story_new_arcs'] or 0}",
        f"New parent arcs:        {row['story_new_parent_arcs'] or 0}",
        f"Unmatched new stories:  {row['story_unmatched_new_stories'] or 0}",
        f"Story match checks:     {row['story_match_verifications'] or 0}",
        f"Story match accepted:   {row['story_match_accepts'] or 0}",
        f"Story match rejected:   {row['story_match_rejections'] or 0}",
        f"LLM calls:              {row['llm_calls_count'] or 0}",
        f"LLM errors:             {row['llm_errors_count'] or 0}",
        f"LLM cache hits:         {row['llm_cache_hits'] or 0}",
        f"  classification:       {row['classification_cache_hits'] or 0}",
        f"  claims:               {row['claim_cache_hits'] or 0}",
        f"  verifier:             {row['verifier_cache_hits'] or 0}",
        f"  matching:             {row['matching_cache_hits'] or 0}",
        f"  briefing:             {row['briefing_cache_hits'] or 0}",
        f"  other:                {row['other_cache_hits'] or 0}",
        f"Schema failures:        {row['schema_failures'] or 0}",
        f"Application retries:    {row['retry_count'] or 0}",
        "SDK retries:            not exposed by client",
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
    lines.extend(novelty_audit_lines(run_id))
    if row["error_message"]:
        lines.append(f"Error:                  {row['error_message']}")
    return "\n".join(lines)


def _markdown_number(value):
    return f"{int(value or 0):,}"


def _markdown_cost(value):
    return pricing.format_eur(value)


def _markdown_audit_story(item):
    reasons = ", ".join(item.get("penalty_reasons") or [])
    return (
        f"| {item['label']} | {item['theme']} | "
        f"{item['source_count']} | {item['importance_avg']:.1f} | "
        f"{item['score']:.1f} | {item.get('selection_score', item['score']):.1f} | "
        f"{item.get('selection_penalty', 0):.1f} | {reasons} |"
    )


def _markdown_audit_new_parent(item):
    development = item.get("development_label") or item["label"]
    return (
        f"| {item['label']} | {development} | {item['theme']} | "
        f"{item['source_count']} | {item['article_count']} | "
        f"{item['importance_avg']:.1f} | {item['score']:.1f} |"
    )


def _markdown_audit_candidate(item):
    return (
        f"| {item['label']} | {item['candidate_label']} | "
        f"{item['relationship']} | {item['confidence']} | "
        f"{item['source_count']} | {item['importance_avg']:.1f} |"
    )


def _markdown_audit_rejected(item):
    return (
        f"| {item['today_label']} | {item['candidate_label']} | "
        f"{item['relationship']} | {item['confidence']} |"
    )


def _markdown_audit_arc_attachment(item):
    score = "n/a" if item.get("chosen_score") is None else f"{item['chosen_score']}"
    return (
        f"| {item['today_label']} | {item['arc_label'] or item['arc_id']} | "
        f"{item['relationship']} | {item['confidence']} | "
        f"{score} | {item['arc_child_count']} |"
    )


def _markdown_audit_arc_rejected(item):
    if item["proposed_arc_label"]:
        target = item["proposed_arc_label"]
    elif item["arc_id"] is not None:
        target = f"arc {item['arc_id']}"
    else:
        target = "NEW_ARC"
    return (
        f"| {item['today_label']} | {target} | "
        f"{item['relationship']} | {item['confidence']} |"
    )


def _run_artifact_name(row):
    run_date = row["run_date"] or "unknown-date"
    return f"run_{run_date}_{row['run_id']}.md"


def run_report_markdown(run_id):
    row = get_run_report_data(run_id)
    if row is None:
        return f"# Run Report\n\nRun #{run_id} was not found.\n"

    seconds = (row["total_latency_ms"] or 0) / 1000
    cost = llm_cost_summary(run_id)
    undated_included = (
        (row["feed_items_missing_timestamp_included"] or 0)
        + (row["feed_items_unparseable_timestamp_included"] or 0)
    )
    undated_skipped = (
        (row["feed_items_missing_timestamp_skipped"] or 0)
        + (row["feed_items_unparseable_timestamp_skipped"] or 0)
    )
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
        f"| Feed items outside date skipped | {_markdown_number(row['feed_items_outside_date_skipped'])} |",
        f"| Undated feed items included | {_markdown_number(undated_included)} |",
        f"| Undated feed items skipped | {_markdown_number(undated_skipped)} |",
        f"| Missing-timestamp feed items included | {_markdown_number(row['feed_items_missing_timestamp_included'])} |",
        f"| Unparseable-timestamp feed items included | {_markdown_number(row['feed_items_unparseable_timestamp_included'])} |",
        f"| Missing-timestamp feed items skipped | {_markdown_number(row['feed_items_missing_timestamp_skipped'])} |",
        f"| Unparseable-timestamp feed items skipped | {_markdown_number(row['feed_items_unparseable_timestamp_skipped'])} |",
        f"| Article text fetched | {_markdown_number(row['article_text_fetch_successes'])} |",
        f"| Article text failures | {_markdown_number(row['article_text_fetch_failures'])} |",
        f"| Claims saved | {_markdown_number(row['claims_saved'])} |",
        f"| Claims extracted | {_markdown_number(row['claim_articles_extracted'])} |",
        f"| Claims cached | {_markdown_number(row['claim_articles_cached'])} |",
        f"| Claims invalid | {_markdown_number(row['claim_invalid_dropped'])} |",
        f"| Claim failures | {_markdown_number(row['claim_extraction_failures'])} |",
        f"| Zero-claim results | {_markdown_number(row['claim_zero_results'])} |",
        f"| Claim cheap accepts | {_markdown_number(row['claim_derivable_accepts'])} |",
        f"| Claim verifier calls | {_markdown_number(row['claim_verifier_calls'])} |",
        f"| Claim verifier accepts | {_markdown_number(row['claim_verifier_accepts'])} |",
        f"| Claim verifier rejects | {_markdown_number(row['claim_verifier_rejects'])} |",
        f"| Claim input truncations | {_markdown_number(row['claim_content_truncations'])} |",
        f"| Stories touched | {_markdown_number(row['stories_touched'])} |",
        f"| Developments saved | {_markdown_number(row['story_developments_saved'])} |",
        f"| Parent attachments | {_markdown_number(row['story_parent_attachments'])} |",
        f"| Arc assignments | {_markdown_number(row['story_arc_assignments'])} |",
        f"| Arc attachments | {_markdown_number(row['story_arc_attachments'])} |",
        f"| New arcs | {_markdown_number(row['story_new_arcs'])} |",
        f"| New parent arcs | {_markdown_number(row['story_new_parent_arcs'])} |",
        f"| Unmatched new stories | {_markdown_number(row['story_unmatched_new_stories'])} |",
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
        f"| Classification cache hits | {_markdown_number(row['classification_cache_hits'])} |",
        f"| Claim cache hits | {_markdown_number(row['claim_cache_hits'])} |",
        f"| Verifier cache hits | {_markdown_number(row['verifier_cache_hits'])} |",
        f"| Matching cache hits | {_markdown_number(row['matching_cache_hits'])} |",
        f"| Briefing cache hits | {_markdown_number(row['briefing_cache_hits'])} |",
        f"| Other cache hits | {_markdown_number(row['other_cache_hits'])} |",
        f"| Schema failures | {_markdown_number(row['schema_failures'])} |",
        f"| Application retries | {_markdown_number(row['retry_count'])} |",
        "| SDK retries | not exposed by client |",
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

    audit = novelty_audit(run_id)
    ratio = audit.get("new_parent_ratio")
    ratio_text = "n/a" if ratio is None else f"{ratio * 100:.1f}%"
    lines.extend([
        "",
        "## Novelty Audit",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| New parent arcs | {_markdown_number(audit.get('new_parent_arcs'))} |",
        f"| Developments | {_markdown_number(audit.get('developments'))} |",
        f"| New parent ratio | {ratio_text} |",
        "",
        "### High-Signal Not Displayed",
        "",
        "| Story | Theme | Sources | Importance | Base Score | Selection Score | Penalty | Penalty Reason |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ])
    if audit["high_signal_not_displayed"]:
        lines.extend(_markdown_audit_story(item) for item in audit["high_signal_not_displayed"])
    else:
        lines.append("| None |  | 0 | 0.0 | 0.0 | 0.0 | 0.0 |  |")

    lines.extend([
        "",
        "### High-Signal New Parent Arcs",
        "",
        "| Parent | Development | Theme | Sources | Articles | Importance | Score |",
        "|---|---|---|---:|---:|---:|---:|",
    ])
    if audit["high_signal_new_parent_arcs"]:
        lines.extend(_markdown_audit_new_parent(item) for item in audit["high_signal_new_parent_arcs"])
    else:
        lines.append("| None |  |  | 0 | 0 | 0.0 | 0.0 |")

    lines.extend([
        "",
        "### New Parent Arcs With Prior Candidates",
        "",
        "| New Parent | Prior Candidate | Relationship | Confidence | Sources | Importance |",
        "|---|---|---|---|---:|---:|",
    ])
    if audit["new_parent_arcs_with_candidates"]:
        lines.extend(_markdown_audit_candidate(item) for item in audit["new_parent_arcs_with_candidates"])
    else:
        lines.append("| None |  |  |  | 0 | 0.0 |")

    lines.extend([
        "",
        "### Rejected Related Matches",
        "",
        "| Today Label | Candidate | Relationship | Confidence |",
        "|---|---|---|---|",
    ])
    if audit["rejected_related_matches"]:
        lines.extend(_markdown_audit_rejected(item) for item in audit["rejected_related_matches"])
    else:
        lines.append("| None |  |  |  |")

    lines.extend([
        "",
        "### Arc Attachments To Review",
        "",
        "| Today Label | Arc | Relationship | Confidence | Chosen Score | Stories In Arc |",
        "|---|---|---|---|---:|---:|",
    ])
    if audit["arc_attachments_review"]:
        lines.extend(_markdown_audit_arc_attachment(item) for item in audit["arc_attachments_review"])
    else:
        lines.append("| None |  |  |  | 0 | 0 |")

    lines.extend([
        "",
        "### Rejected Arc Decisions",
        "",
        "| Today Label | Proposed Arc | Relationship | Confidence |",
        "|---|---|---|---|",
    ])
    if audit["rejected_arc_decisions"]:
        lines.extend(_markdown_audit_arc_rejected(item) for item in audit["rejected_arc_decisions"])
    else:
        lines.append("| None |  |  |  |")

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
