import json


AUDIT_SCORE_THRESHOLD = 450.0
AUDIT_SOURCE_THRESHOLD = 6
AUDIT_IMPORTANCE_THRESHOLD = 3.0
AUDIT_REVIEW_RELATIONSHIPS = {
    "same_story_arc",
    "direct_follow_up",
    "adjacent_topic",
    "broader_context",
}


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
    from src.briefing import selection as briefing_selection

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

    from src.briefing import selection as briefing_selection

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
