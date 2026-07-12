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
