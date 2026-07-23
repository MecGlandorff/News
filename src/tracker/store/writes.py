from __future__ import annotations

import json

from src import observability
from src.tracker.store.schema import get_db


def create_story_arc(conn, canonical_label, theme, first_seen, last_seen):
    cur = conn.execute(
        """
        INSERT INTO story_arcs (canonical_label, theme, first_seen, last_seen)
        VALUES (?, ?, ?, ?)
        """,
        (canonical_label, theme, first_seen, last_seen),
    )
    return cur.lastrowid


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
        UPDATE stories
        SET parent_story_id = NULL
        WHERE parent_story_id IN (
            SELECT story_id
            FROM stories
            WHERE story_id NOT IN (SELECT DISTINCT story_id FROM story_daily)
        )
    """)
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
                verifier_model, prompt_version, decision_route,
                candidate_signals, conflicts, ambiguity_reason, reasoning_effort
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                decision.get("decision_route", "legacy"),
                json.dumps(decision.get("candidate_signals", {}), ensure_ascii=False),
                json.dumps(decision.get("conflicts", []), ensure_ascii=False),
                decision.get("ambiguity_reason", ""),
                decision.get("reasoning_effort", ""),
            ),
        )


def save_same_day_match_decisions(
    conn,
    decisions,
    run_date,
    matching_model,
    prompt_version,
):
    if not decisions:
        return
    run_id = observability.current_run_id()
    for decision in decisions:
        left_id, right_id = sorted(
            (
                int(decision["left_occurrence_id"]),
                int(decision["right_occurrence_id"]),
            )
        )
        conn.execute(
            """
            INSERT INTO same_day_match_decisions (
                run_id, run_date, left_occurrence_id, right_occurrence_id,
                candidate_signals, accepted, relationship, confidence,
                continuity_evidence, conflicts, reject_reason, decision_route,
                ambiguity_reason, matching_model, reasoning_effort, prompt_version
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (
                run_id, run_date, left_occurrence_id, right_occurrence_id
            ) DO UPDATE SET
                candidate_signals = excluded.candidate_signals,
                accepted = excluded.accepted,
                relationship = excluded.relationship,
                confidence = excluded.confidence,
                continuity_evidence = excluded.continuity_evidence,
                conflicts = excluded.conflicts,
                reject_reason = excluded.reject_reason,
                decision_route = excluded.decision_route,
                ambiguity_reason = excluded.ambiguity_reason,
                matching_model = excluded.matching_model,
                reasoning_effort = excluded.reasoning_effort,
                prompt_version = excluded.prompt_version,
                created_at = CURRENT_TIMESTAMP
            """,
            (
                run_id,
                run_date,
                left_id,
                right_id,
                json.dumps(decision.get("candidate_signals", {}), ensure_ascii=False),
                1 if decision.get("accepted") else 0,
                decision.get("relationship", "uncertain"),
                decision.get("confidence", "low"),
                json.dumps(decision.get("continuity_evidence", []), ensure_ascii=False),
                json.dumps(decision.get("conflicts", []), ensure_ascii=False),
                decision.get("reject_reason", ""),
                decision.get("decision_route", "legacy"),
                decision.get("ambiguity_reason", ""),
                decision.get("matching_model", matching_model),
                decision.get("reasoning_effort", ""),
                decision.get("prompt_version", prompt_version),
            ),
        )


def save_story_arc_decisions(conn, decisions, run_date, assignment_model, prompt_version, story_ids=None):
    if not decisions:
        return
    run_id = observability.current_run_id()
    story_ids = story_ids or {}
    for decision in decisions:
        conn.execute(
            """
            INSERT INTO story_arc_decisions (
                run_id, run_date, today_label, candidates, arc_id,
                parent_story_id, story_id, accepted, relationship, confidence,
                continuity_evidence, reject_reason, assignment_model, prompt_version,
                decision_route, candidate_signals, conflicts, ambiguity_reason,
                reasoning_effort, proposed_arc_id, proposed_parent_story_id,
                previous_arc_label, proposed_arc_label, final_arc_label
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                run_date,
                decision["today_label"],
                json.dumps(decision.get("candidates", []), ensure_ascii=False),
                decision.get("proposed_arc_id"),
                decision.get("proposed_parent_story_id"),
                story_ids.get(decision["today_label"]),
                1 if decision.get("accepted") else 0,
                decision.get("relationship", "uncertain"),
                decision.get("confidence", "low"),
                json.dumps(decision.get("continuity_evidence", []), ensure_ascii=False),
                decision.get("reject_reason", ""),
                decision.get("verifier_model", assignment_model),
                decision.get("prompt_version", prompt_version),
                decision.get("decision_route", "legacy"),
                json.dumps(decision.get("candidate_signals", {}), ensure_ascii=False),
                json.dumps(decision.get("conflicts", []), ensure_ascii=False),
                decision.get("ambiguity_reason", ""),
                decision.get("reasoning_effort", ""),
                decision.get("proposed_arc_id"),
                decision.get("proposed_parent_story_id"),
                decision.get("previous_arc_label", ""),
                decision.get("proposed_arc_label", ""),
                decision.get("final_arc_label", ""),
            ),
        )
