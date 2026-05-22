import json
import sqlite3
from datetime import date, timedelta

from src import observability
from src.config import DEFAULT_LOOKBACK_DAYS


def ensure_column(conn, table, column, definition):
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def backfill_story_arcs(conn):
    """Give legacy flat story rows a one-story compatibility arc."""
    rows = conn.execute("""
        SELECT story_id, canonical_label, theme, first_seen, last_seen
        FROM stories
        WHERE arc_id IS NULL
        ORDER BY story_id
    """).fetchall()
    for row in rows:
        cur = conn.execute(
            """
            INSERT INTO story_arcs (canonical_label, theme, first_seen, last_seen)
            VALUES (?, ?, ?, ?)
            """,
            (
                row["canonical_label"],
                row["theme"],
                row["first_seen"],
                row["last_seen"],
            ),
        )
        conn.execute(
            "UPDATE stories SET arc_id = ?, parent_story_id = NULL WHERE story_id = ?",
            (cur.lastrowid, row["story_id"]),
        )


def get_db(db_path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS story_arcs (
            arc_id          INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_label TEXT NOT NULL,
            theme           TEXT,
            first_seen      DATE NOT NULL,
            last_seen       DATE NOT NULL
        );
        CREATE TABLE IF NOT EXISTS stories (
            story_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            arc_id          INTEGER REFERENCES story_arcs(arc_id),
            parent_story_id INTEGER REFERENCES stories(story_id),
            canonical_label TEXT NOT NULL,
            theme           TEXT,
            first_seen      DATE NOT NULL,
            last_seen       DATE NOT NULL
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
        CREATE TABLE IF NOT EXISTS story_developments (
            development_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            story_id            INTEGER NOT NULL,
            observation_id      INTEGER,
            date                DATE NOT NULL,
            development_label   TEXT NOT NULL,
            development_status  TEXT NOT NULL,
            source_count        INTEGER,
            article_count       INTEGER,
            importance_avg      REAL,
            parent_relationship TEXT,
            parent_confidence   TEXT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (story_id, date, development_label)
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
        CREATE TABLE IF NOT EXISTS story_match_decisions (
            decision_id          INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id               INTEGER,
            run_date             TEXT NOT NULL,
            today_label          TEXT NOT NULL,
            candidate_label      TEXT NOT NULL,
            candidate_story_id   INTEGER,
            accepted             INTEGER NOT NULL,
            same_event           INTEGER NOT NULL,
            relationship         TEXT NOT NULL,
            confidence           TEXT,
            article_dates        TEXT,
            candidate_last_seen  TEXT,
            continuity_evidence  TEXT,
            reject_reason        TEXT,
            verifier_model       TEXT,
            prompt_version       TEXT NOT NULL,
            created_at           TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_story_match_decisions_run_id
            ON story_match_decisions (run_id);
        CREATE INDEX IF NOT EXISTS idx_story_match_decisions_run_date
            ON story_match_decisions (run_date);
        CREATE INDEX IF NOT EXISTS idx_story_developments_story_date
            ON story_developments (story_id, date);
        CREATE INDEX IF NOT EXISTS idx_story_developments_date
            ON story_developments (date);
        CREATE INDEX IF NOT EXISTS idx_story_arcs_last_seen
            ON story_arcs (last_seen);
    """)
    ensure_column(conn, "stories", "arc_id", "INTEGER REFERENCES story_arcs(arc_id)")
    ensure_column(conn, "stories", "parent_story_id", "INTEGER REFERENCES stories(story_id)")
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_stories_arc_id
            ON stories (arc_id);
        CREATE INDEX IF NOT EXISTS idx_stories_parent_story_id
            ON stories (parent_story_id);
    """)
    ensure_column(conn, "articles", "description", "TEXT")
    ensure_column(conn, "articles", "source_id", "INTEGER REFERENCES sources(source_id)")
    backfill_story_arcs(conn)
    conn.commit()
    return conn


def get_recent_stories(conn, today, lookback_days=DEFAULT_LOOKBACK_DAYS):
    start = str(date.fromisoformat(str(today)) - timedelta(days=lookback_days))
    rows = conn.execute("""
        SELECT s.story_id, s.canonical_label, s.first_seen,
               MAX(sd.date) AS last_daily,
               COUNT(DISTINCT sd.date) AS active_days
        FROM stories s
        JOIN story_daily sd ON s.story_id = sd.story_id
        WHERE sd.date >= ? AND sd.date < ?
        GROUP BY s.story_id, s.canonical_label, s.first_seen
        ORDER BY last_daily DESC, s.story_id DESC
    """, (start, today)).fetchall()
    recent = {}
    for row in rows:
        recent.setdefault(row["canonical_label"], row["story_id"])
    return recent


def get_recent_story_options(conn, today, lookback_days=DEFAULT_LOOKBACK_DAYS):
    """Return recent stories with compact memory for cross-day matching."""
    start = str(date.fromisoformat(str(today)) - timedelta(days=lookback_days))
    rows = conn.execute("""
        SELECT s.story_id, s.canonical_label, s.first_seen,
               s.arc_id, s.parent_story_id,
               a.canonical_label AS arc_label,
               p.canonical_label AS parent_label,
               MAX(sd.date) AS last_daily,
               COUNT(DISTINCT sd.date) AS active_days
        FROM stories s
        JOIN story_daily sd ON s.story_id = sd.story_id
        LEFT JOIN story_arcs a ON a.arc_id = s.arc_id
        LEFT JOIN stories p ON p.story_id = s.parent_story_id
        WHERE sd.date >= ? AND sd.date < ?
        GROUP BY s.story_id, s.canonical_label, s.first_seen,
                 s.arc_id, s.parent_story_id, a.canonical_label, p.canonical_label
        ORDER BY last_daily DESC, s.story_id DESC
    """, (start, today)).fetchall()

    recent = {}
    for row in rows:
        label = row["canonical_label"]
        if label in recent:
            continue
        context = get_previous_story_context(conn, row["story_id"], today)
        recent[label] = {
            "story_id": row["story_id"],
            "canonical_label": label,
            "arc_id": row["arc_id"],
            "arc_label": row["arc_label"] or label,
            "parent_story_id": row["parent_story_id"],
            "parent_label": row["parent_label"] or "",
            "first_seen": row["first_seen"],
            "last_seen": row["last_daily"],
            "active_days": row["active_days"],
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
            "recent_developments": context.get("recent_developments", [])[:5],
        }
    return recent


def get_recent_arc_options(conn, today, lookback_days=DEFAULT_LOOKBACK_DAYS):
    """Return recent arcs with compact child-story memory for arc assignment."""
    start = str(date.fromisoformat(str(today)) - timedelta(days=lookback_days))
    rows = conn.execute("""
        SELECT a.arc_id, a.canonical_label, a.theme, a.first_seen,
               MAX(sd.date) AS last_daily,
               COUNT(DISTINCT sd.date) AS active_days
        FROM story_arcs a
        JOIN stories s ON s.arc_id = a.arc_id
        JOIN story_daily sd ON sd.story_id = s.story_id
        WHERE sd.date >= ? AND sd.date < ?
        GROUP BY a.arc_id, a.canonical_label, a.theme, a.first_seen
        ORDER BY last_daily DESC, a.arc_id DESC
    """, (start, today)).fetchall()

    recent = {}
    for row in rows:
        story_rows = conn.execute("""
            SELECT s.story_id, s.canonical_label, s.parent_story_id,
                   p.canonical_label AS parent_label,
                   MAX(sd.date) AS last_daily
            FROM stories s
            JOIN story_daily sd ON sd.story_id = s.story_id
            LEFT JOIN stories p ON p.story_id = s.parent_story_id
            WHERE s.arc_id = ?
              AND sd.date >= ?
              AND sd.date < ?
            GROUP BY s.story_id, s.canonical_label, s.parent_story_id, p.canonical_label
            ORDER BY last_daily DESC, s.story_id DESC
            LIMIT 6
        """, (row["arc_id"], start, today)).fetchall()
        stories = []
        for story in story_rows:
            context = get_previous_story_context(conn, story["story_id"], today)
            stories.append({
                "story_id": story["story_id"],
                "canonical_label": story["canonical_label"],
                "parent_story_id": story["parent_story_id"],
                "parent_label": story["parent_label"] or "",
                "last_seen": story["last_daily"],
                "summary": context.get("summary", ""),
                "delta_summary": context.get("delta_summary", ""),
            })
        recent[row["arc_id"]] = {
            "arc_id": row["arc_id"],
            "canonical_label": row["canonical_label"],
            "theme": row["theme"],
            "first_seen": row["first_seen"],
            "last_seen": row["last_daily"],
            "active_days": row["active_days"],
            "recent_stories": stories,
        }
    return recent


def create_story_arc(conn, canonical_label, theme, first_seen, last_seen):
    cur = conn.execute(
        """
        INSERT INTO story_arcs (canonical_label, theme, first_seen, last_seen)
        VALUES (?, ?, ?, ?)
        """,
        (canonical_label, theme, first_seen, last_seen),
    )
    return cur.lastrowid


def get_story_hierarchy(conn, story_id):
    row = conn.execute("""
        SELECT s.story_id, s.arc_id, s.parent_story_id,
               a.canonical_label AS arc_label,
               p.canonical_label AS parent_label
        FROM stories s
        LEFT JOIN story_arcs a ON a.arc_id = s.arc_id
        LEFT JOIN stories p ON p.story_id = s.parent_story_id
        WHERE s.story_id = ?
    """, (story_id,)).fetchone()
    if not row:
        return {
            "arc_id": None,
            "arc_label": "",
            "parent_story_id": None,
            "parent_label": "",
        }
    return {
        "arc_id": row["arc_id"],
        "arc_label": row["arc_label"] or "",
        "parent_story_id": row["parent_story_id"],
        "parent_label": row["parent_label"] or "",
    }


def get_previous_story_context(conn, story_id, today, article_limit=3):
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
    development_rows = conn.execute("""
        SELECT date, development_label, development_status
        FROM story_developments
        WHERE story_id = ?
          AND date < ?
        ORDER BY date DESC, development_id DESC
        LIMIT 5
    """, (story_id, today)).fetchall()
    if development_rows:
        context["recent_developments"] = [
            {
                "date": row["date"],
                "label": row["development_label"],
                "status": row["development_status"],
            }
            for row in development_rows
        ]
    return context


def save_observation_memory(db_path, memories):
    """Persist compact story memory generated during briefing creation."""
    updates = [
        memory for memory in memories
        if memory.get("observation_id")
        and ((memory.get("summary") or "").strip() or (memory.get("delta_summary") or "").strip())
    ]
    if not updates:
        return

    conn = get_db(db_path)
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


def find_story_by_label(conn, canonical_label, today, lookback_days=DEFAULT_LOOKBACK_DAYS):
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


def get_yesterday_stories(conn, today):
    yesterday = str(date.fromisoformat(str(today)) - timedelta(days=1))
    rows = conn.execute("""
        SELECT s.story_id, s.canonical_label
        FROM stories s
        JOIN story_daily sd ON s.story_id = sd.story_id
        WHERE sd.date = ?
    """, (yesterday,)).fetchall()
    return {r["canonical_label"]: r["story_id"] for r in rows}


def reset_tracking_date(conn, today):
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
    conn.execute("DELETE FROM story_developments WHERE date = ?", (today,))
    conn.execute("DELETE FROM story_observations WHERE date = ?", (today,))
    conn.execute("DELETE FROM story_daily WHERE date = ?", (today,))


def sync_story_dates(conn):
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
    conn.execute("""
        DELETE FROM story_arcs
        WHERE arc_id NOT IN (
            SELECT DISTINCT arc_id
            FROM stories
            WHERE arc_id IS NOT NULL
        )
    """)
    conn.execute("""
        UPDATE story_arcs
        SET first_seen = (
                SELECT MIN(stories.first_seen)
                FROM stories
                WHERE stories.arc_id = story_arcs.arc_id
            ),
            last_seen = (
                SELECT MAX(stories.last_seen)
                FROM stories
                WHERE stories.arc_id = story_arcs.arc_id
            )
        WHERE arc_id IN (
            SELECT DISTINCT arc_id
            FROM stories
            WHERE arc_id IS NOT NULL
        )
    """)


def source_id_for_name(conn, source_name):
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


def save_story_match_decisions(conn, decisions, run_date, verifier_model, prompt_version):
    if not decisions:
        return
    run_id = observability.current_run_id()
    for decision in decisions:
        conn.execute(
            """
            INSERT INTO story_match_decisions (
                run_id, run_date, today_label, candidate_label, candidate_story_id,
                accepted, same_event, relationship, confidence, article_dates,
                candidate_last_seen, continuity_evidence, reject_reason,
                verifier_model, prompt_version
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                run_date,
                decision["today_label"],
                decision["candidate_label"],
                decision.get("candidate_story_id"),
                1 if decision.get("accepted") else 0,
                1 if decision.get("same_event") else 0,
                decision.get("relationship", "uncertain"),
                decision.get("confidence", "low"),
                json.dumps(decision.get("article_dates", []), ensure_ascii=False),
                decision.get("candidate_last_seen", ""),
                json.dumps(decision.get("continuity_evidence", []), ensure_ascii=False),
                decision.get("reject_reason", ""),
                decision.get("verifier_model", verifier_model),
                decision.get("prompt_version", prompt_version),
            ),
        )


def trend(story_id, today_count, conn, today):
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
    if delta > 1:
        return "up"
    if delta < -1:
        return "down"
    return "steady"
