import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from src.config import DEFAULT_LOOKBACK_DAYS, TRACKER_MODEL
from src.llm import get_openai_client, parse_json_object

DB_PATH  = Path("data/stories.db")
DATA_DIR = Path("data/daily")

CONSOLIDATE_PROMPT = """You are grouping today's news story labels that refer to the same ongoing story.

Given a list of story labels from today, identify groups that are clearly about the same event.
For each group, pick the best canonical label (clear, concise, in English).

Return a JSON object with key "groups": array of {canonical_label, labels} where labels is the list of today's labels that belong to this group.
Labels that stand alone still appear as a group of one."""

MATCH_PROMPT = """You are matching today's news story labels to yesterday's canonical story labels.

For each label in today's list, return either:
- The matching canonical label from yesterday (if it's the same ongoing story)
- "NEW" (if it's a genuinely new story)

Be generous with matching — slight wording differences for the same story should match.
Different stories (even similar topics) should not match.

Return a JSON object with key "matches": array of {today_label, canonical_label}.
canonical_label is either the exact string from yesterday's list or "NEW"."""


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
            novelty_score  REAL,
            created_at     TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (story_id, date)
        );
        CREATE TABLE IF NOT EXISTS articles (
            id             TEXT,
            story_id       INTEGER,
            date           DATE,
            source         TEXT,
            title          TEXT,
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
        ORDER BY last_daily DESC
    """, (start, today)).fetchall()
    return {r["canonical_label"]: r["story_id"] for r in rows}


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


def _consolidate_today(story_groups):
    """Merge story_labels that refer to the same event within today's batch."""
    labels = list(story_groups.keys())
    if len(labels) <= 1:
        return story_groups

    client = get_openai_client()
    response = client.chat.completions.create(
        model=TRACKER_MODEL,
        messages=[
            {"role": "system", "content": CONSOLIDATE_PROMPT},
            {"role": "user", "content": json.dumps(labels, ensure_ascii=False)},
        ],
        response_format={"type": "json_object"},
    )
    payload = parse_json_object(response)
    groups = payload.get("groups")
    if not isinstance(groups, list):
        raise ValueError('Model response must contain a "groups" list')

    from collections import defaultdict
    consolidated = defaultdict(list)
    grouped_labels = set()
    for g in groups:
        if not isinstance(g, dict):
            continue
        canonical = str(g.get("canonical_label") or "").strip()
        labels = g.get("labels", [])
        if not canonical or not isinstance(labels, list):
            continue
        for label in labels:
            if label in story_groups:
                grouped_labels.add(label)
                consolidated[canonical].extend(story_groups[label])

    for label, articles in story_groups.items():
        if label not in grouped_labels:
            consolidated[label].extend(articles)

    print(f"  Consolidated {len(story_groups)} labels → {len(consolidated)} stories", flush=True)
    return consolidated


def _match_labels(today_labels, yesterday_stories):
    if not yesterday_stories:
        return {label: "NEW" for label in today_labels}

    client = get_openai_client()
    response = client.chat.completions.create(
        model=TRACKER_MODEL,
        messages=[
            {"role": "system", "content": MATCH_PROMPT},
            {"role": "user", "content": json.dumps({
                "today":     list(today_labels),
                "yesterday": list(yesterday_stories.keys()),
            }, ensure_ascii=False)},
        ],
        response_format={"type": "json_object"},
    )
    payload = parse_json_object(response)
    matches = payload.get("matches")
    if not isinstance(matches, list):
        raise ValueError('Model response must contain a "matches" list')
    matched = {}
    valid_yesterday = set(yesterday_stories)
    for m in matches:
        if not isinstance(m, dict) or m.get("today_label") not in today_labels:
            continue
        canonical = m.get("canonical_label")
        matched[m["today_label"]] = canonical if canonical in valid_yesterday else "NEW"
    for label in today_labels:
        matched.setdefault(label, "NEW")
    return matched


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

    conn = _get_db()
    _reset_tracking_date(conn, today)

    # Group today's articles by story_label, then consolidate within-day duplicates
    from collections import defaultdict
    raw_groups = defaultdict(list)
    for a in classified:
        raw_groups[a["story_label"]].append(a)
    story_groups = _consolidate_today(raw_groups)

    # Match today's labels to recent canonical labels.
    recent_stories = _get_recent_stories(conn, today, lookback_days)
    label_map = _match_labels(set(story_groups.keys()), recent_stories)

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

        source_count   = len(set(a["source"] for a in articles))
        importance_avg = sum(a["importance"] for a in articles) / len(articles)
        trend          = _trend(story_id, source_count, conn, today)

        conn.execute("""
            INSERT OR REPLACE INTO story_daily (story_id, date, source_count, importance_avg, labels_seen)
            VALUES (?, ?, ?, ?, ?)
        """, (story_id, today, source_count, importance_avg, json.dumps([story_label])))

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
            conn.execute("""
                INSERT INTO articles (id, story_id, date, source, title, url, published_at, importance)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (a["id"], story_id, today, a["source"], a["title"], a["url"], a["published_at"], a["importance"]))
            conn.execute("""
                INSERT OR REPLACE INTO article_story_links (article_id, story_id, observation_id, relevance)
                VALUES (?, ?, ?, ?)
            """, (str(a["id"]), story_id, observation_id, 1.0))
            tracked.append({**a, "story_id": story_id, "canonical_label": canonical if canonical != "NEW" else story_label, "trend": trend})

    _sync_story_dates(conn)
    conn.commit()
    conn.close()

    print(f"Tracked {len(story_groups)} stories ({sum(1 for v in label_map.values() if v == 'NEW')} new)")
    return tracked
