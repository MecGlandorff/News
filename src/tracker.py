import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from src.config import DEFAULT_LOOKBACK_DAYS, TRACKER_MODEL
from src.llm import get_openai_client
from src import story_matching

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


def _ensure_column(conn, table, column, definition):
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS stories (
            story_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_label TEXT NOT NULL,
            theme          TEXT,
            first_seen     DATE NOT NULL,
            last_seen      DATE NOT NULL
        );
        CREATE TABLE IF NOT EXISTS story_daily (
            story_id       INTEGER NOT NULL,
            date           DATE NOT NULL,
            source_count   INTEGER,
            importance_avg REAL,
            labels_seen    TEXT,
            PRIMARY KEY (story_id, date)
        );
        CREATE TABLE IF NOT EXISTS story_observations (
            observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            story_id       INTEGER NOT NULL,
            date           DATE NOT NULL,
            label_seen     TEXT,
            source_count   INTEGER,
            article_count  INTEGER,
            importance_avg REAL,
            summary        TEXT,
            delta_summary  TEXT,
            created_at     TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (story_id, date)
        );
        CREATE TABLE IF NOT EXISTS articles (
            id             TEXT,
            story_id       INTEGER,
            date           DATE,
            source_id      INTEGER REFERENCES sources(source_id),
            source         TEXT,
            title          TEXT,
            description    TEXT,
            url            TEXT,
            published_at   TEXT,
            importance     INTEGER
        );
        CREATE TABLE IF NOT EXISTS article_story_links (
            article_id      TEXT NOT NULL,
            story_id        INTEGER NOT NULL,
            observation_id  INTEGER,
            relevance       REAL,
            PRIMARY KEY (article_id, story_id, observation_id)
        );
    """)
    _ensure_column(conn, "articles", "description", "TEXT")
    _ensure_column(conn, "articles", "source_id", "INTEGER REFERENCES sources(source_id)")
    conn.commit()
    return conn


def _get_recent_stories(conn, today, lookback_days=DEFAULT_LOOKBACK_DAYS):
    start = str(date.fromisoformat(str(today)) - timedelta(days=lookback_days))
    rows = conn.execute("""
        SELECT s.story_id, s.canonical_label, MAX(sd.date) AS last_daily
        FROM stories s
        JOIN story_daily sd ON s.story_id = sd.story_id
        WHERE sd.date >= ? AND sd.date < ?
        GROUP BY s.story_id, s.canonical_label
        ORDER BY last_daily DESC, s.story_id DESC
    """, (start, today)).fetchall()
    recent = {}
    for row in rows:
        recent.setdefault(row["canonical_label"], row["story_id"])
    return recent


def _get_recent_story_options(conn, today, lookback_days=DEFAULT_LOOKBACK_DAYS):
    """Return recent stories with compact memory for cross-day matching."""
    start = str(date.fromisoformat(str(today)) - timedelta(days=lookback_days))
    rows = conn.execute("""
        SELECT s.story_id, s.canonical_label, MAX(sd.date) AS last_daily
        FROM stories s
        JOIN story_daily sd ON s.story_id = sd.story_id
        WHERE sd.date >= ? AND sd.date < ?
        GROUP BY s.story_id, s.canonical_label
        ORDER BY last_daily DESC, s.story_id DESC
    """, (start, today)).fetchall()

    recent = {}
    for row in rows:
        label = row["canonical_label"]
        if label in recent:
            continue
        context = _get_previous_story_context(conn, row["story_id"], today)
        recent[label] = {
            "story_id": row["story_id"],
            "canonical_label": label,
            "last_seen": row["last_daily"],
            "summary": context.get("summary", ""),
            "delta_summary": context.get("delta_summary", ""),
            "recent_articles": [
                {
                    "date": article.get("date", ""),
                    "source": article.get("source", ""),
                    "title": article.get("title", ""),
                }
                for article in context.get("recent_articles", [])[:3]
            ],
        }
    return recent


def _get_previous_story_context(conn, story_id, today, article_limit=3):
    """Return compact historical context for a continuing story."""
    context = {}
    observation = conn.execute("""
        SELECT date, summary, delta_summary
        FROM story_observations
        WHERE story_id = ?
          AND date < ?
          AND (
              NULLIF(TRIM(COALESCE(summary, '')), '') IS NOT NULL
              OR NULLIF(TRIM(COALESCE(delta_summary, '')), '') IS NOT NULL
          )
        ORDER BY date DESC
        LIMIT 1
    """, (story_id, today)).fetchone()
    if observation:
        summary = (observation["summary"] or "").strip()
        delta_summary = (observation["delta_summary"] or "").strip()
        if summary or delta_summary:
            context["last_observed"] = observation["date"]
            if summary:
                context["summary"] = summary
            if delta_summary:
                context["delta_summary"] = delta_summary

    rows = conn.execute("""
        SELECT date, source, title, description, url, published_at
        FROM articles
        WHERE story_id = ?
          AND date < ?
        ORDER BY date DESC, published_at DESC
        LIMIT ?
    """, (story_id, today, article_limit)).fetchall()
    if rows:
        context["recent_articles"] = [
            {
                "date": r["date"],
                "source": r["source"],
                "title": r["title"],
                "description": r["description"] or "",
                "url": r["url"],
                "reported_at": r["published_at"] or "",
            }
            for r in rows
        ]
    return context


def save_observation_memory(memories):
    """Persist compact story memory generated during briefing creation."""
    updates = [
        memory for memory in memories
        if memory.get("observation_id")
        and ((memory.get("summary") or "").strip() or (memory.get("delta_summary") or "").strip())
    ]
    if not updates:
        return

    conn = _get_db()
    try:
        with conn:
            for memory in updates:
                conn.execute("""
                    UPDATE story_observations
                    SET summary = ?, delta_summary = ?
                    WHERE observation_id = ?
                """, (
                    (memory.get("summary") or "").strip(),
                    (memory.get("delta_summary") or "").strip(),
                    memory["observation_id"],
                ))
    finally:
        conn.close()


def _find_story_by_label(conn, canonical_label, today, lookback_days=DEFAULT_LOOKBACK_DAYS):
    start = str(date.fromisoformat(str(today)) - timedelta(days=lookback_days))
    row = conn.execute("""
        SELECT story_id
        FROM stories
        WHERE canonical_label = ?
          AND last_seen >= ?
          AND first_seen <= ?
        ORDER BY last_seen DESC
        LIMIT 1
    """, (canonical_label, start, today)).fetchone()
    return row["story_id"] if row else None


def _get_yesterday_stories(conn, today):
    yesterday = str(date.fromisoformat(str(today)) - timedelta(days=1))
    rows = conn.execute("""
        SELECT s.story_id, s.canonical_label
        FROM stories s
        JOIN story_daily sd ON s.story_id = sd.story_id
        WHERE sd.date = ?
    """, (yesterday,)).fetchall()
    return {r["canonical_label"]: r["story_id"] for r in rows}


def _reset_tracking_date(conn, today):
    """Remove derived tracking rows for one date before rebuilding it."""
    conn.execute("""
        DELETE FROM article_story_links
        WHERE observation_id IN (
            SELECT observation_id
            FROM story_observations
            WHERE date = ?
        )
    """, (today,))
    conn.execute("DELETE FROM articles WHERE date = ?", (today,))
    conn.execute("DELETE FROM story_observations WHERE date = ?", (today,))
    conn.execute("DELETE FROM story_daily WHERE date = ?", (today,))


def _sync_story_dates(conn):
    """Keep story date bounds aligned with the remaining daily rows."""
    conn.execute("""
        DELETE FROM stories
        WHERE story_id NOT IN (
            SELECT DISTINCT story_id
            FROM story_daily
        )
    """)
    conn.execute("""
        UPDATE stories
        SET first_seen = (
                SELECT MIN(date)
                FROM story_daily
                WHERE story_daily.story_id = stories.story_id
            ),
            last_seen = (
                SELECT MAX(date)
                FROM story_daily
                WHERE story_daily.story_id = stories.story_id
            )
        WHERE story_id IN (
            SELECT DISTINCT story_id
            FROM story_daily
        )
    """)


def _source_id_for_name(conn, source_name):
    """Return the seeded source id when source metadata is available."""
    if not source_name:
        return None
    has_sources = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'sources'"
    ).fetchone()
    if not has_sources:
        return None
    row = conn.execute(
        "SELECT source_id FROM sources WHERE name = ?",
        (source_name,),
    ).fetchone()
    return row["source_id"] if row else None


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


def _trend(story_id, today_count, conn, today):
    row = conn.execute(
        """
        SELECT source_count
        FROM story_daily
        WHERE story_id = ? AND date < ?
        ORDER BY date DESC
        LIMIT 1
        """,
        (story_id, today)
    ).fetchone()
    if not row:
        return "new"
    delta = today_count - row["source_count"]
    if delta > 1:   return "up"
    if delta < -1:  return "down"
    return "steady"


def track(classified, today=None, lookback_days=DEFAULT_LOOKBACK_DAYS):
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

    conn = _get_db()
    try:
        with conn:
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
                        "story_id": story_id,
                        "observation_id": observation_id,
                        "canonical_label": canonical if canonical != "NEW" else story_label,
                        "trend": trend,
                        "previous_context": previous_context,
                    })

            _sync_story_dates(conn)
    finally:
        conn.close()

    print(f"Tracked {len(story_groups)} stories ({sum(1 for v in label_map.values() if v == 'NEW')} new)")
    return tracked
