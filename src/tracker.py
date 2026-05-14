import json
from datetime import date
from pathlib import Path
from src.config import DEFAULT_LOOKBACK_DAYS, STORY_MATCH_VERIFIER_MODEL, TRACKER_MODEL
from src.llm import get_openai_client
from src import observability, story_matching, tracker_store

DB_PATH  = Path("data/stories.db")
DATA_DIR = Path("data/daily")

CONSOLIDATE_PROMPT = story_matching.CONSOLIDATE_PROMPT
MATCH_PROMPT = story_matching.MATCH_PROMPT
LABEL_STOPWORDS = story_matching.LABEL_STOPWORDS
GENERIC_EVENT_TOKENS = story_matching.GENERIC_EVENT_TOKENS
CANDIDATES_PER_LABEL = story_matching.CANDIDATES_PER_LABEL
SUMMARY_CHAR_LIMIT = story_matching.SUMMARY_CHAR_LIMIT
DELTA_CHAR_LIMIT = story_matching.DELTA_CHAR_LIMIT
TITLE_CHAR_LIMIT = story_matching.TITLE_CHAR_LIMIT
VERIFY_PROMPT_VERSION = story_matching.VERIFY_PROMPT_VERSION


def _get_db():
    return tracker_store.get_db(DB_PATH)


def _get_recent_stories(conn, today, lookback_days=DEFAULT_LOOKBACK_DAYS):
    return tracker_store.get_recent_stories(conn, today, lookback_days)


def _get_recent_story_options(conn, today, lookback_days=DEFAULT_LOOKBACK_DAYS):
    return tracker_store.get_recent_story_options(conn, today, lookback_days)


def _get_previous_story_context(conn, story_id, today, article_limit=3):
    return tracker_store.get_previous_story_context(conn, story_id, today, article_limit)


def save_observation_memory(memories):
    return tracker_store.save_observation_memory(DB_PATH, memories)


def _find_story_by_label(conn, canonical_label, today, lookback_days=DEFAULT_LOOKBACK_DAYS):
    return tracker_store.find_story_by_label(conn, canonical_label, today, lookback_days)


def _get_yesterday_stories(conn, today):
    return tracker_store.get_yesterday_stories(conn, today)


def _reset_tracking_date(conn, today):
    return tracker_store.reset_tracking_date(conn, today)


def _sync_story_dates(conn):
    return tracker_store.sync_story_dates(conn)


def _source_id_for_name(conn, source_name):
    return tracker_store.source_id_for_name(conn, source_name)


def _save_story_match_decisions(conn, decisions, run_date):
    return tracker_store.save_story_match_decisions(
        conn,
        decisions,
        run_date,
        STORY_MATCH_VERIFIER_MODEL,
        VERIFY_PROMPT_VERSION,
    )


def _record_story_match_verification_totals(decisions):
    if not decisions:
        return
    observability.update_run_totals(
        story_match_verifications=len(decisions),
        story_match_accepts=sum(1 for decision in decisions if decision.get("accepted")),
        story_match_rejections=sum(1 for decision in decisions if not decision.get("accepted")),
    )


def _fetch_article_text_for_match(url):
    from src.scraper import fetch_article_text
    return fetch_article_text(url)


def _ensure_match_article_text(story_groups, labels):
    for label in labels:
        for article in story_groups.get(label, []):
            if (article.get("text") or "").strip():
                continue
            url = article.get("url")
            if not url:
                continue
            try:
                article["text"] = _fetch_article_text_for_match(url)
            except Exception:
                article["text"] = article.get("text") or ""


def _label_tokens(label):
    return story_matching.label_tokens(label)


def _truncate_text(value, limit):
    return story_matching.truncate_text(value, limit)


def _days_since(value, today):
    return story_matching.days_since(value, today, DEFAULT_LOOKBACK_DAYS)


def _distinctive_label_tokens(label):
    return story_matching.distinctive_label_tokens(label)


def _is_generic_event_label(label):
    return story_matching.is_generic_event_label(label)


def _labels_can_refer_to_same_story(left, right):
    return story_matching.labels_can_refer_to_same_story(left, right)


def _compatible_label_clusters(labels):
    return story_matching.compatible_label_clusters(labels)


def _canonical_for_cluster(canonical, cluster, split_group):
    return story_matching.canonical_for_cluster(canonical, cluster, split_group)


def _consolidate_today(story_groups):
    return story_matching.consolidate_today(
        story_groups,
        get_client=get_openai_client,
        model=TRACKER_MODEL,
    )


def _recent_story_value_label(label, value):
    return story_matching.recent_story_value_label(label, value)


def _recent_story_text(label, value):
    return story_matching.recent_story_text(label, value)


def _candidate_score(today_label, candidate_label, candidate, today=None):
    return story_matching.candidate_score(
        today_label,
        candidate_label,
        candidate,
        today=today,
        default_days=DEFAULT_LOOKBACK_DAYS,
    )


def _compact_story_option(label, value):
    return story_matching.compact_story_option(label, value)


def _candidate_cases_for_prompt(today_labels, recent_stories, today=None, limit=CANDIDATES_PER_LABEL):
    return story_matching.candidate_cases_for_prompt(
        today_labels,
        recent_stories,
        today=today,
        limit=limit,
        default_days=DEFAULT_LOOKBACK_DAYS,
    )


def _match_labels(today_labels, recent_stories, today=None):
    return story_matching.match_labels(
        today_labels,
        recent_stories,
        get_client=get_openai_client,
        model=TRACKER_MODEL,
        today=today,
        default_days=DEFAULT_LOOKBACK_DAYS,
    )


def _verify_story_matches(label_map, recent_stories, story_groups, today=None):
    return story_matching.verify_story_matches(
        label_map,
        recent_stories,
        story_groups,
        get_client=get_openai_client,
        model=STORY_MATCH_VERIFIER_MODEL,
        today=today,
    )


def _trend(story_id, today_count, conn, today):
    return tracker_store.trend(story_id, today_count, conn, today)


def track(classified, today=None, lookback_days=DEFAULT_LOOKBACK_DAYS, verify_story_matches=True):
    if not classified:
        return []

    today = today or str(date.today())
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Save full articles to daily JSON
    daily_path = DATA_DIR / today
    daily_path.mkdir(exist_ok=True)
    (daily_path / "articles.json").write_text(
        json.dumps(classified, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Group today's articles by story_label, then consolidate within-day duplicates
    from collections import defaultdict
    raw_groups = defaultdict(list)
    for a in classified:
        raw_groups[a["story_label"]].append(a)
    story_groups = _consolidate_today(raw_groups)

    conn = _get_db()
    try:
        recent_story_options = _get_recent_story_options(conn, today, lookback_days)
        recent_stories = {
            label: option["story_id"]
            for label, option in recent_story_options.items()
        }
    finally:
        conn.close()

    # Match today's labels to recent canonical labels outside the write transaction.
    label_map = _match_labels(set(story_groups.keys()), recent_story_options, today=today)
    match_decisions = []
    if verify_story_matches:
        candidate_labels = {
            label
            for label, canonical in label_map.items()
            if canonical != "NEW" and canonical in recent_story_options
        }
        _ensure_match_article_text(story_groups, candidate_labels)
        label_map, match_decisions = _verify_story_matches(
            label_map,
            recent_story_options,
            story_groups,
            today=today,
        )

    conn = _get_db()
    try:
        with conn:
            _save_story_match_decisions(conn, match_decisions, today)
            _reset_tracking_date(conn, today)

            # Upsert stories and story_daily
            tracked = []
            for story_label, articles in story_groups.items():
                canonical = label_map.get(story_label, "NEW")

                if canonical == "NEW" or canonical not in recent_stories:
                    # New story
                    story_id = _find_story_by_label(conn, story_label, today, lookback_days)
                    if story_id:
                        conn.execute(
                            "UPDATE stories SET last_seen = ? WHERE story_id = ?",
                            (today, story_id)
                        )
                    else:
                        cur = conn.execute(
                            "INSERT INTO stories (canonical_label, theme, first_seen, last_seen) VALUES (?, ?, ?, ?)",
                            (story_label, articles[0]["theme"], today, today)
                        )
                        story_id = cur.lastrowid
                else:
                    story_id = recent_stories[canonical]
                    canonical = canonical  # keep canonical label
                    conn.execute(
                        "UPDATE stories SET last_seen = ? WHERE story_id = ?",
                        (today, story_id)
                    )

                previous_context = _get_previous_story_context(conn, story_id, today)
                source_count   = len(set(a["source"] for a in articles))
                importance_avg = sum(a["importance"] for a in articles) / len(articles)
                trend          = _trend(story_id, source_count, conn, today)

                conn.execute(
                    """
                    INSERT OR REPLACE INTO story_daily (story_id, date, source_count, importance_avg, labels_seen)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (story_id, today, source_count, importance_avg, json.dumps([story_label]))
                )

                conn.execute("""
                    INSERT INTO story_observations (
                        story_id, date, label_seen, source_count, article_count, importance_avg
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(story_id, date) DO UPDATE SET
                        label_seen = excluded.label_seen,
                        source_count = excluded.source_count,
                        article_count = excluded.article_count,
                        importance_avg = excluded.importance_avg,
                        created_at = CURRENT_TIMESTAMP
                """, (story_id, today, story_label, source_count, len(articles), importance_avg))
                observation_id = conn.execute(
                    "SELECT observation_id FROM story_observations WHERE story_id = ? AND date = ?",
                    (story_id, today)
                ).fetchone()["observation_id"]

                conn.execute(
                    "DELETE FROM articles WHERE story_id = ? AND date = ?",
                    (story_id, today)
                )
                conn.execute(
                    "DELETE FROM article_story_links WHERE story_id = ? AND observation_id = ?",
                    (story_id, observation_id)
                )
                for a in articles:
                    source_id = _source_id_for_name(conn, a.get("source"))
                    conn.execute("""
                        INSERT INTO articles (
                            id, story_id, date, source_id, source, title, description, url, published_at, importance
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        a["id"],
                        story_id,
                        today,
                        source_id,
                        a["source"],
                        a["title"],
                        a.get("description", ""),
                        a["url"],
                        a["published_at"],
                        a["importance"],
                    ))
                    conn.execute("""
                        INSERT OR REPLACE INTO article_story_links (article_id, story_id, observation_id, relevance)
                        VALUES (?, ?, ?, ?)
                    """, (str(a["id"]), story_id, observation_id, 1.0))
                    tracked.append({
                        **a,
                        "source_id": source_id,
                        "story_id": story_id,
                        "observation_id": observation_id,
                        "canonical_label": canonical if canonical != "NEW" else story_label,
                        "trend": trend,
                        "previous_context": previous_context,
                    })

            _sync_story_dates(conn)
    finally:
        conn.close()

    _record_story_match_verification_totals(match_decisions)
    print(f"Tracked {len(story_groups)} stories ({sum(1 for v in label_map.values() if v == 'NEW')} new)")
    return tracked
