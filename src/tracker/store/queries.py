from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from src.config import DEFAULT_LOOKBACK_DAYS
from src.tracker import matching as story_matching
from src.tracker.store.schema import is_blocked_memory_label


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
        if is_blocked_memory_label(row["canonical_label"]):
            continue
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
        if is_blocked_memory_label(label):
            continue
        if is_blocked_memory_label(row["arc_label"]):
            continue
        if is_blocked_memory_label(row["parent_label"]):
            continue
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
        if is_blocked_memory_label(row["canonical_label"]):
            continue
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
            if is_blocked_memory_label(story["canonical_label"]):
                continue
            if is_blocked_memory_label(story["parent_label"]):
                continue
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
        if not stories:
            continue
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


def find_story_by_label(
    conn: sqlite3.Connection,
    canonical_label: str,
    today: str,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> int | None:
    """Find a story to reuse for an exact canonical-label match.

    Same-day rows are always reusable so reruns stay idempotent. Rows from
    earlier days are only reused when the label is specific enough that
    exact equality implies the same real-world event; generic incident
    labels recur across unrelated events (ADR 0008).
    """
    if is_blocked_memory_label(canonical_label):
        return None
    start = str(date.fromisoformat(str(today)) - timedelta(days=lookback_days))
    row = conn.execute("""
        SELECT story_id, first_seen
        FROM stories
        WHERE canonical_label = ?
          AND last_seen >= ?
          AND first_seen <= ?
        ORDER BY last_seen DESC, story_id DESC
        LIMIT 1
    """, (canonical_label, start, today)).fetchone()
    if row is None:
        return None
    if row["first_seen"] != str(today) and not story_matching.exact_label_reuse_allowed(canonical_label):
        return None
    return row["story_id"]


def get_yesterday_stories(conn, today):
    yesterday = str(date.fromisoformat(str(today)) - timedelta(days=1))
    rows = conn.execute("""
        SELECT s.story_id, s.canonical_label
        FROM stories s
        JOIN story_daily sd ON s.story_id = sd.story_id
        WHERE sd.date = ?
    """, (yesterday,)).fetchall()
    return {
        r["canonical_label"]: r["story_id"]
        for r in rows
        if not is_blocked_memory_label(r["canonical_label"])
    }


def get_story_arc_decisions(conn, run_date=None, run_id=None):
    query = """
        SELECT decision_id, run_id, run_date, today_label, candidates, arc_id,
               parent_story_id, story_id, accepted, relationship, confidence,
               continuity_evidence, reject_reason, assignment_model, prompt_version
        FROM story_arc_decisions
    """
    clauses = []
    params = []
    if run_date is not None:
        clauses.append("run_date = ?")
        params.append(str(run_date))
    if run_id is not None:
        clauses.append("run_id = ?")
        params.append(run_id)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY decision_id"
    return [dict(row) for row in conn.execute(query, params).fetchall()]


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
