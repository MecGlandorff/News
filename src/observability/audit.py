from src.observability.audit_queries import (
    _arc_attachments_review,
    _high_signal_new_parent_arcs,
    _high_signal_not_displayed,
    _new_parent_arcs_with_candidates,
    _rejected_arc_decisions,
    _rejected_related_matches,
    _run_cli_args,
    _top_developments_from_args,
)
from src.observability.database import get_db as _get_db
from src.observability.runs import get_run_report_data


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
