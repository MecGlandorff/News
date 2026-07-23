from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from src import llm_response_cache, observability
from src.pricing import estimate_llm_cost_eur
from src.tracker import store as tracker_store
from src.tracker import track


DEFAULT_SOURCE_DB = Path("data/stories.db")
DEFAULT_REVIEW_DATASET = (
    Path(__file__).parent
    / "datasets"
    / "matching_reconstruction_review_2026-07-21_22.jsonl"
)
MATCHING_CACHE_PURPOSES = (
    "match-sameday-evidence",
    "match-crossday-evidence",
    "match-arc-evidence",
)


class ReconstructionError(RuntimeError):
    """Raised before an unsafe or incomplete reconstruction can be used."""


def _iso_date(value: str, *, field: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ReconstructionError(f"{field} must use YYYY-MM-DD format") from exc


def _readonly_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _quick_check(connection: sqlite3.Connection, *, label: str) -> None:
    result = connection.execute("PRAGMA quick_check").fetchone()
    if result is None or result[0] != "ok":
        value = result[0] if result else "no result"
        raise ReconstructionError(f"{label} failed SQLite quick_check: {value}")


def snapshot_manifest(
    source_db: Path,
    start_date: str,
    end_date: str | None = None,
) -> dict[str, Any]:
    start = _iso_date(start_date, field="start_date")
    end = _iso_date(end_date, field="end_date") if end_date else None
    if end is not None and end < start:
        raise ReconstructionError("end_date must not be before start_date")
    if not source_db.is_file():
        raise ReconstructionError(f"Source database does not exist: {source_db}")

    connection = _readonly_connection(source_db)
    try:
        _quick_check(connection, label="Source database")
        parameters: list[object] = [start]
        end_clause = ""
        if end is not None:
            end_clause = "AND o.editorial_date <= ?"
            parameters.append(end)
        rows = connection.execute(
            f"""
            SELECT o.editorial_date, COUNT(DISTINCT o.article_id) AS article_count
            FROM article_occurrences o
            JOIN occurrence_classifications c
              ON c.occurrence_id = o.occurrence_id
            WHERE o.editorial_date >= ?
              {end_clause}
            GROUP BY o.editorial_date
            ORDER BY o.editorial_date
            """,
            parameters,
        ).fetchall()
    finally:
        connection.close()
    if not rows:
        raise ReconstructionError("No classified occurrence snapshots match the date range")
    return {
        "source_db": source_db.name,
        "start_date": start,
        "end_date": end or str(rows[-1]["editorial_date"]),
        "dates": [
            {
                "date": str(row["editorial_date"]),
                "article_count": int(row["article_count"]),
            }
            for row in rows
        ],
        "article_count": sum(int(row["article_count"]) for row in rows),
    }


def archive_database(source_db: Path, archive_path: Path) -> None:
    if source_db.resolve() == archive_path.resolve():
        raise ReconstructionError("Archive path must differ from the source database")
    if archive_path.exists():
        raise ReconstructionError(f"Archive path already exists: {archive_path}")
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    source = _readonly_connection(source_db)
    destination = sqlite3.connect(archive_path)
    try:
        _quick_check(source, label="Source database")
        source.backup(destination)
        _quick_check(destination, label="Archived database")
    finally:
        destination.close()
        source.close()


def _snapshot_articles(
    archive_path: Path,
    start_date: str,
    end_date: str,
) -> dict[str, list[dict[str, object]]]:
    connection = _readonly_connection(archive_path)
    try:
        rows = connection.execute(
            """
            WITH latest AS (
                SELECT o.article_id, o.editorial_date,
                       MAX(o.occurrence_id) AS occurrence_id
                FROM article_occurrences o
                JOIN occurrence_classifications c
                  ON c.occurrence_id = o.occurrence_id
                WHERE o.editorial_date >= ?
                  AND o.editorial_date <= ?
                GROUP BY o.article_id, o.editorial_date
            )
            SELECT o.article_id, o.editorial_date, o.source, o.language,
                   o.title, o.description, o.body_text, o.url, o.published_at,
                   c.theme, c.story_label, c.importance
            FROM latest l
            JOIN article_occurrences o ON o.occurrence_id = l.occurrence_id
            JOIN occurrence_classifications c
              ON c.occurrence_id = o.occurrence_id
            ORDER BY o.editorial_date, o.occurrence_id
            """,
            (start_date, end_date),
        ).fetchall()
    finally:
        connection.close()

    by_date: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        editorial_date = str(row["editorial_date"])
        by_date[editorial_date].append(
            {
                "id": str(row["article_id"]),
                "source": str(row["source"]),
                "language": str(row["language"] or ""),
                "title": str(row["title"]),
                "description": str(row["description"] or ""),
                "text": str(row["body_text"] or ""),
                "url": str(row["url"]),
                "published_at": str(row["published_at"] or ""),
                "theme": str(row["theme"]),
                "story_label": str(row["story_label"]),
                "importance": int(row["importance"]),
            }
        )
    return dict(by_date)


def _purge_reconstructed_range(output_db: Path, start_date: str) -> None:
    connection = tracker_store.get_db(output_db)
    try:
        with connection:
            connection.execute(
                """
                DELETE FROM article_story_links
                WHERE observation_id IN (
                    SELECT observation_id
                    FROM story_observations
                    WHERE date >= ?
                )
                """,
                (start_date,),
            )
            connection.execute("DELETE FROM articles WHERE date >= ?", (start_date,))
            connection.execute(
                "DELETE FROM story_developments WHERE date >= ?",
                (start_date,),
            )
            connection.execute(
                "DELETE FROM story_observations WHERE date >= ?",
                (start_date,),
            )
            connection.execute(
                "DELETE FROM story_daily WHERE date >= ?",
                (start_date,),
            )
            connection.execute(
                """
                DELETE FROM occurrence_assignments
                WHERE occurrence_id IN (
                    SELECT occurrence_id
                    FROM article_occurrences
                    WHERE editorial_date >= ?
                )
                """,
                (start_date,),
            )
            for table in (
                "same_day_match_decisions",
                "story_match_decisions",
                "story_arc_decisions",
            ):
                connection.execute(
                    f"DELETE FROM {table} WHERE run_date >= ?",
                    (start_date,),
                )
            has_cache = connection.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'table' AND name = 'llm_response_cache'
                """
            ).fetchone()
            if has_cache:
                connection.execute(
                    """
                    DELETE FROM llm_response_cache
                    WHERE purpose IN (?, ?, ?)
                    """,
                    MATCHING_CACHE_PURPOSES,
                )
            tracker_store.sync_story_dates(connection)
    finally:
        connection.close()


def _run_cost(output_db: Path, run_ids: list[int]) -> dict[str, object]:
    connection = sqlite3.connect(output_db)
    connection.row_factory = sqlite3.Row
    placeholders = ", ".join("?" for _ in run_ids)
    try:
        rows = connection.execute(
            f"""
            SELECT purpose, model, COUNT(*) AS calls,
                   COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                   COALESCE(SUM(latency_ms), 0) AS latency_ms
            FROM llm_calls
            WHERE run_id IN ({placeholders})
            GROUP BY purpose, model
            ORDER BY purpose, model
            """,
            run_ids,
        ).fetchall()
    finally:
        connection.close()

    total_cost = 0.0
    unpriced_models = set()
    purposes = []
    for row in rows:
        cost = estimate_llm_cost_eur(
            str(row["model"]),
            int(row["prompt_tokens"]),
            int(row["completion_tokens"]),
        )
        if cost is None:
            unpriced_models.add(str(row["model"]))
        else:
            total_cost += cost
        purposes.append(
            {
                "purpose": str(row["purpose"]),
                "model": str(row["model"]),
                "calls": int(row["calls"]),
                "prompt_tokens": int(row["prompt_tokens"]),
                "completion_tokens": int(row["completion_tokens"]),
                "latency_ms": int(row["latency_ms"]),
                "cost_eur": cost,
            }
        )
    return {
        "cost_eur": None if unpriced_models else total_cost,
        "priced_cost_eur": total_cost,
        "unpriced_models": sorted(unpriced_models),
        "by_purpose": purposes,
    }


def reconstruct_effort(
    archive_path: Path,
    output_db: Path,
    articles_by_date: dict[str, list[dict[str, object]]],
    *,
    start_date: str,
    effort: str,
    client_factory=None,
) -> dict[str, Any]:
    if effort not in {"none", "low"}:
        raise ReconstructionError("effort must be 'none' or 'low'")
    if output_db.exists():
        raise ReconstructionError(f"Reconstruction output already exists: {output_db}")
    shutil.copy2(archive_path, output_db)
    _purge_reconstructed_range(output_db, start_date)

    previous_cache_db = llm_response_cache.DB_PATH
    run_ids_by_date: dict[str, int] = {}
    try:
        llm_response_cache.DB_PATH = output_db
        for editorial_date, articles in sorted(articles_by_date.items()):
            run_id = observability.start_run(
                {
                    "mode": "matching-reconstruction",
                    "reasoning_effort": effort,
                    "article_count": len(articles),
                },
                run_date=editorial_date,
                db_path=output_db,
            )
            if run_id is None:
                raise ReconstructionError("Could not create reconstruction run")
            run_id = int(run_id)
            run_ids_by_date[editorial_date] = run_id
            observability.set_current_run_id(run_id, db_path=output_db)
            try:
                tracked = track(
                    articles,
                    today=editorial_date,
                    db_path=output_db,
                    data_dir=output_db.parent / f"daily-{effort}",
                    client_factory=client_factory,
                    matching_reasoning_effort=effort,
                )
                observability.update_run_totals(
                    run_id,
                    db_path=output_db,
                    articles_returned=len(articles),
                    stories_touched=len(
                        {int(item["story_id"]) for item in tracked}
                    ),
                )
                observability.finish_run(run_id, db_path=output_db)
            except Exception as exc:
                observability.finish_run(
                    run_id,
                    status="error",
                    error_message=str(exc),
                    db_path=output_db,
                )
                raise
            finally:
                observability.clear_current_run_id()
    finally:
        llm_response_cache.DB_PATH = previous_cache_db
        observability.clear_current_run_id()

    connection = sqlite3.connect(output_db)
    try:
        quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        connection.close()
    if quick_check != "ok" or foreign_keys:
        raise ReconstructionError(
            "Reconstruction database failed integrity verification"
        )
    run_ids = list(run_ids_by_date.values())
    return {
        "effort": effort,
        "output_db": output_db.name,
        "run_ids_by_date": run_ids_by_date,
        "cost": _run_cost(output_db, run_ids),
        "integrity": {
            "quick_check": quick_check,
            "foreign_key_violations": len(foreign_keys),
        },
    }


def load_review_cases(path: Path) -> list[dict[str, object]]:
    cases = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            raw = json.loads(stripped)
            if not isinstance(raw, dict):
                raise ReconstructionError(f"{path}:{line_number} must be an object")
            required = {
                "case_id",
                "layer",
                "today_date",
                "today_article_id",
                "candidate_date",
                "candidate_article_id",
                "expected_accepted",
            }
            if not required <= raw.keys():
                missing = ", ".join(sorted(required - raw.keys()))
                raise ReconstructionError(
                    f"{path}:{line_number} missing fields: {missing}"
                )
            if raw["layer"] not in {"same_day", "story", "arc"}:
                raise ReconstructionError(
                    f"{path}:{line_number} has invalid layer"
                )
            if not isinstance(raw["expected_accepted"], bool):
                raise ReconstructionError(
                    f"{path}:{line_number} expected_accepted must be boolean"
                )
            candidate_article_ids = raw.get("candidate_article_ids", [])
            if (
                not isinstance(candidate_article_ids, list)
                or not all(
                    isinstance(article_id, str) and article_id
                    for article_id in candidate_article_ids
                )
            ):
                raise ReconstructionError(
                    f"{path}:{line_number} candidate_article_ids must be "
                    "an array of non-empty strings"
                )
            cases.append(raw)
    return cases


def _assignment(
    connection: sqlite3.Connection,
    article_id: str,
    editorial_date: str,
) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT o.occurrence_id, a.story_id, a.arc_id, a.development_label
        FROM article_occurrences o
        JOIN occurrence_assignments a ON a.occurrence_id = o.occurrence_id
        WHERE o.article_id = ?
          AND o.editorial_date = ?
        ORDER BY o.occurrence_id DESC
        LIMIT 1
        """,
        (article_id, editorial_date),
    ).fetchone()
    if row is None:
        raise ReconstructionError(
            f"No reconstructed assignment for {editorial_date}/{article_id}"
        )
    return row


def _observed_review_decision(
    connection: sqlite3.Connection,
    case: dict[str, object],
    run_ids_by_date: dict[str, int],
) -> tuple[bool, str, str]:
    today_date = str(case["today_date"])
    candidate_date = str(case["candidate_date"])
    today = _assignment(
        connection,
        str(case["today_article_id"]),
        today_date,
    )
    candidate_aliases = case.get("candidate_article_ids")
    aliases = candidate_aliases if isinstance(candidate_aliases, list) else []
    candidate_article_ids = list(
        dict.fromkeys(
            [
                str(case["candidate_article_id"]),
                *[str(article_id) for article_id in aliases],
            ]
        )
    )
    candidates = [
        _assignment(connection, article_id, candidate_date)
        for article_id in candidate_article_ids
    ]
    run_id = run_ids_by_date.get(today_date)
    if run_id is None:
        raise ReconstructionError(f"No reconstruction run exists for {today_date}")

    rows = []
    for candidate in candidates:
        if case["layer"] == "same_day":
            left_id, right_id = sorted(
                (int(today["occurrence_id"]), int(candidate["occurrence_id"]))
            )
            row = connection.execute(
                """
                SELECT accepted, relationship, decision_route
                FROM same_day_match_decisions
                WHERE run_id = ?
                  AND left_occurrence_id = ?
                  AND right_occurrence_id = ?
                ORDER BY decision_id DESC
                LIMIT 1
                """,
                (run_id, left_id, right_id),
            ).fetchone()
        elif case["layer"] == "story":
            row = connection.execute(
                """
                SELECT accepted, relationship, decision_route
                FROM story_match_decisions
                WHERE run_id = ?
                  AND today_label = ?
                  AND candidate_story_id = ?
                ORDER BY decision_id DESC
                LIMIT 1
                """,
                (
                    run_id,
                    str(today["development_label"]),
                    int(candidate["story_id"]),
                ),
            ).fetchone()
        else:
            row = connection.execute(
                """
                SELECT accepted, relationship, decision_route
                FROM story_arc_decisions
                WHERE run_id = ?
                  AND today_label = ?
                  AND proposed_arc_id = ?
                ORDER BY decision_id DESC
                LIMIT 1
                """,
                (
                    run_id,
                    str(today["development_label"]),
                    int(candidate["arc_id"]),
                ),
            ).fetchone()
        if row is not None:
            rows.append(row)

    if not rows:
        return False, "not_retrieved", "not_retrieved"
    row = next((item for item in rows if bool(item["accepted"])), rows[0])
    return bool(row["accepted"]), str(row["relationship"]), str(row["decision_route"])


def score_review_cases(
    output_db: Path,
    cases: list[dict[str, object]],
    run_ids_by_date: dict[str, int],
) -> dict[str, object]:
    connection = sqlite3.connect(output_db)
    connection.row_factory = sqlite3.Row
    results = []
    try:
        for case in cases:
            observed, relationship, route = _observed_review_decision(
                connection,
                case,
                run_ids_by_date,
            )
            expected = bool(case["expected_accepted"])
            if observed and expected:
                outcome = "correct_accept"
            elif not observed and not expected:
                outcome = "correct_reject"
            elif observed:
                outcome = "corrupting_accept"
            else:
                outcome = "missed_positive"
            results.append(
                {
                    "case_id": str(case["case_id"]),
                    "layer": str(case["layer"]),
                    "expected_accepted": expected,
                    "observed_accepted": observed,
                    "outcome": outcome,
                    "relationship": relationship,
                    "route": route,
                    "review_note": str(case.get("review_note", "")),
                }
            )
    finally:
        connection.close()

    positives = sum(1 for result in results if result["expected_accepted"])
    accepted_positives = sum(
        1
        for result in results
        if result["expected_accepted"] and result["observed_accepted"]
    )
    corrupting = sum(
        1 for result in results if result["outcome"] == "corrupting_accept"
    )
    return {
        "cases": len(results),
        "expected_positives": positives,
        "accepted_positives": accepted_positives,
        "clear_positive_recall": (
            accepted_positives / positives if positives else None
        ),
        "corrupting_accepts": corrupting,
        "zero_corrupting_accepts": corrupting == 0,
        "results": results,
    }


def _recommend_effort(efforts: list[dict[str, Any]]) -> dict[str, object]:
    by_name = {str(item["effort"]): item for item in efforts}
    none = by_name.get("none")
    low = by_name.get("low")
    if none is None or low is None:
        return {
            "status": "incomplete",
            "selected_effort": None,
            "reason": "Both none and low are required for the effort gate.",
        }
    none_review = none["review"]
    low_review = low["review"]
    none_passes = bool(none_review["zero_corrupting_accepts"])
    low_passes = bool(low_review["zero_corrupting_accepts"])
    none_cost = none["cost"]["cost_eur"]
    low_cost = low["cost"]["cost_eur"]
    cost_delta = (
        low_cost - none_cost
        if isinstance(none_cost, (int, float))
        and isinstance(low_cost, (int, float))
        else None
    )
    low_improves = (
        int(low_review["accepted_positives"])
        > int(none_review["accepted_positives"])
    )
    low_within_cost = cost_delta is not None and cost_delta <= 0.05

    if none_passes and not (low_passes and low_improves and low_within_cost):
        return {
            "status": "selected",
            "selected_effort": "none",
            "cost_delta_eur": cost_delta,
            "reason": (
                "none passes the zero-corruption gate; low did not both improve "
                "clear-positive recall and stay within EUR 0.05."
            ),
        }
    if low_passes and low_improves and low_within_cost:
        return {
            "status": "selected",
            "selected_effort": "low",
            "cost_delta_eur": cost_delta,
            "reason": (
                "low passes, improves clear-positive recall, and adds no more "
                "than EUR 0.05."
            ),
        }
    return {
        "status": "fix_needed",
        "selected_effort": None,
        "cost_delta_eur": cost_delta,
        "reason": "Neither effort satisfies the approved quality/cost selection rule.",
    }


def build_report(
    manifest: dict[str, Any],
    effort_results: list[dict[str, Any]],
    *,
    archive_path: Path,
    review_dataset: Path,
) -> dict[str, Any]:
    return {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "saved_occurrence_matching_reconstruction",
        "manifest": manifest,
        "archive": archive_path.name,
        "review_dataset": review_dataset.name,
        "efforts": effort_results,
        "recommendation": _recommend_effort(effort_results),
        "active_database_replaced": False,
    }


def _format_percent(value: object) -> str:
    if not isinstance(value, (int, float)):
        return "n/a"
    return f"{value * 100:.1f}%"


def format_markdown_report(report: dict[str, Any]) -> str:
    manifest = report["manifest"]
    recommendation = report["recommendation"]
    lines = [
        "# Phase 3 Matching Reconstruction",
        "",
        f"**Created:** {report['created_at']}",
        f"**Range:** {manifest['start_date']} through {manifest['end_date']}",
        f"**Snapshots:** {manifest['article_count']} articles across {len(manifest['dates'])} days",
        f"**Source archive:** `{report['archive']}`",
        f"**Review dataset:** `{report['review_dataset']}`",
        "**Active database replaced:** no",
        "",
        "## Effort Comparison",
        "",
        "| Effort | Reviewed cases | Corrupting accepts | Clear-positive recall | Matching cost |",
        "|---|---:|---:|---:|---:|",
    ]
    for effort in report["efforts"]:
        review = effort["review"]
        cost = effort["cost"]["cost_eur"]
        cost_text = "unavailable" if cost is None else f"EUR {cost:.4f}"
        lines.append(
            f"| {effort['effort']} | {review['cases']} | "
            f"{review['corrupting_accepts']} | "
            f"{_format_percent(review['clear_positive_recall'])} | {cost_text} |"
        )
    lines.extend(
        [
            "",
            "## Selection",
            "",
            f"**Status:** {recommendation['status']}",
            f"**Selected effort:** {recommendation.get('selected_effort') or 'none yet'}",
            "",
            str(recommendation["reason"]),
            "",
            "## Reviewed Failures",
            "",
        ]
    )
    failures = [
        result
        for effort in report["efforts"]
        for result in effort["review"]["results"]
        if result["outcome"] in {"corrupting_accept", "missed_positive"}
    ]
    if not failures:
        lines.append("No reviewed corrupting accepts or missed positives.")
    else:
        for failure in failures:
            lines.append(
                f"- `{failure['case_id']}` ({failure['layer']}, "
                f"{failure['outcome']}, route `{failure['route']}`)"
            )
    lines.extend(
        [
            "",
            "The reconstruction databases remain local. Replacing "
            "`data/stories.db` requires a separate explicit decision.",
            "",
        ]
    )
    return "\n".join(lines)


def run_reconstruction(
    *,
    source_db: Path,
    start_date: str,
    end_date: str | None,
    work_dir: Path,
    efforts: list[str],
    review_dataset: Path,
    sanitized_report: Path | None = None,
    client_factory=None,
) -> dict[str, Any]:
    if work_dir.exists():
        raise ReconstructionError(f"Work directory already exists: {work_dir}")
    manifest = snapshot_manifest(source_db, start_date, end_date)
    work_dir.mkdir(parents=True)
    archive_path = work_dir / "source-archive.db"
    archive_database(source_db, archive_path)
    articles_by_date = _snapshot_articles(
        archive_path,
        str(manifest["start_date"]),
        str(manifest["end_date"]),
    )
    cases = load_review_cases(review_dataset)
    results = []
    for effort in efforts:
        output_db = work_dir / f"reconstruction-{effort}.db"
        effort_result = reconstruct_effort(
            archive_path,
            output_db,
            articles_by_date,
            start_date=str(manifest["start_date"]),
            effort=effort,
            client_factory=client_factory,
        )
        effort_result["review"] = score_review_cases(
            output_db,
            cases,
            effort_result["run_ids_by_date"],
        )
        results.append(effort_result)
    report = build_report(
        manifest,
        results,
        archive_path=archive_path,
        review_dataset=review_dataset,
    )
    (work_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown = format_markdown_report(report)
    (work_dir / "report.md").write_text(markdown, encoding="utf-8")
    if sanitized_report is not None:
        sanitized_report.parent.mkdir(parents=True, exist_ok=True)
        sanitized_report.write_text(markdown, encoding="utf-8")
    return report


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Re-run saved occurrence snapshots through evidence-gated matching "
            "in isolated database copies."
        )
    )
    parser.add_argument("--source-db", type=Path, default=DEFAULT_SOURCE_DB)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date")
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument(
        "--effort",
        action="append",
        choices=("none", "low"),
        dest="efforts",
        help="Repeat to compare efforts; defaults to both none and low.",
    )
    parser.add_argument(
        "--review-dataset",
        type=Path,
        default=DEFAULT_REVIEW_DATASET,
    )
    parser.add_argument("--sanitized-report", type=Path)
    parser.add_argument(
        "--inspect-only",
        action="store_true",
        help="Validate and print the snapshot manifest without writing or calling APIs.",
    )
    parser.add_argument(
        "--confirm-api-cost",
        action="store_true",
        help="Required before reconstruction because matching makes OpenAI API calls.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    manifest = snapshot_manifest(
        args.source_db,
        args.start_date,
        args.end_date,
    )
    if args.inspect_only:
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return manifest
    if not args.confirm_api_cost:
        raise SystemExit(
            "Refusing to make matching API calls without --confirm-api-cost"
        )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    work_dir = (
        args.work_dir
        if args.work_dir is not None
        else Path("evals/local") / f"matching-reconstruction-{stamp}"
    )
    efforts = list(dict.fromkeys(args.efforts or ["none", "low"]))
    report = run_reconstruction(
        source_db=args.source_db,
        start_date=args.start_date,
        end_date=args.end_date,
        work_dir=work_dir,
        efforts=efforts,
        review_dataset=args.review_dataset,
        sanitized_report=args.sanitized_report,
    )
    print(format_markdown_report(report))
    print(f"Local reconstruction: {work_dir}")
    return report


if __name__ == "__main__":
    main()
