import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from src import story_matching
from src.config import ARC_ASSIGNMENT_MODEL, STORY_MATCH_VERIFIER_MODEL


MODE = "static_reviewed_replay"
DEFAULT_STORY_DATASET = Path(__file__).parent / "datasets" / "story_match_cases.jsonl"
DEFAULT_ARC_DATASET = Path(__file__).parent / "datasets" / "arc_assignment_cases.jsonl"
DEFAULT_REPORT_DIR = Path(__file__).parent / "reports"


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _report_stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _ratio(numerator, denominator):
    if denominator == 0:
        return None
    return numerator / denominator


def _percent(value):
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def _git_output(*args):
    try:
        completed = subprocess.run(
            ["git", *args],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _git_sha():
    return _git_output("rev-parse", "--short", "HEAD")


def _working_tree_state():
    status = _git_output("status", "--short")
    if status is None:
        return "unknown"
    return "dirty" if status else "clean"


def _case_id(case, index):
    return str(case.get("case_id") or f"case-{index + 1}")


def _require_string(case, field, path, line_no):
    value = case.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path}:{line_no} missing required string field {field}")


def _validate_decision(case, field, path, line_no):
    decision = case.get(field)
    if not isinstance(decision, dict):
        raise ValueError(f"{path}:{line_no} missing {field} object")
    if not isinstance(decision.get("accepted"), bool):
        raise ValueError(f"{path}:{line_no} {field}.accepted must be boolean")
    relationship = decision.get("relationship")
    if relationship is not None and not isinstance(relationship, str):
        raise ValueError(f"{path}:{line_no} {field}.relationship must be a string")
    confidence = decision.get("confidence")
    if confidence is not None and not isinstance(confidence, str):
        raise ValueError(f"{path}:{line_no} {field}.confidence must be a string")


def _validate_case(case, case_type, path, line_no):
    if not isinstance(case, dict):
        raise ValueError(f"{path}:{line_no} must be a JSON object")
    if case.get("case_type") not in (None, case_type):
        raise ValueError(f"{path}:{line_no} case_type must be {case_type}")
    _require_string(case, "case_id", path, line_no)
    _require_string(case, "today_label", path, line_no)
    if case_type == "story_match":
        _require_string(case, "candidate_label", path, line_no)
    elif case_type == "arc_assignment":
        _require_string(case, "candidate_arc_label", path, line_no)
    else:
        raise ValueError(f"Unknown case type: {case_type}")
    _validate_decision(case, "observed_decision", path, line_no)
    _validate_decision(case, "expected_decision", path, line_no)
    replay_input = case.get("replay_input")
    if replay_input is not None and not isinstance(replay_input, dict):
        raise ValueError(f"{path}:{line_no} replay_input must be an object when present")


def load_cases(path, case_type):
    path = Path(path)
    cases = []
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            case = json.loads(stripped)
            _validate_case(case, case_type, path, line_no)
            case = dict(case)
            case["case_type"] = case_type
            cases.append(case)
    return cases


def _story_outcome(observed, expected):
    if observed and expected:
        return "correct_match"
    if not observed and not expected:
        return "correct_new"
    if observed and not expected:
        return "false_merge"
    return "false_split"


def _arc_outcome(observed, expected):
    if observed and expected:
        return "correct_attachment"
    if not observed and not expected:
        return "correct_new_arc"
    if observed and not expected:
        return "false_arc"
    return "missed_arc"


def evaluate_case(case, index=0):
    case_type = case["case_type"]
    observed = case["observed_decision"]["accepted"]
    expected = case["expected_decision"]["accepted"]
    if case_type == "story_match":
        candidate = case["candidate_label"]
        outcome = _story_outcome(observed, expected)
    else:
        candidate = case["candidate_arc_label"]
        outcome = _arc_outcome(observed, expected)

    observed_decision = case["observed_decision"]
    expected_decision = case["expected_decision"]
    return {
        "case_id": _case_id(case, index),
        "case_type": case_type,
        "source": case.get("source", ""),
        "review_status": case.get("review_status", ""),
        "run_date": case.get("run_date", ""),
        "today_label": case["today_label"],
        "candidate": candidate,
        "observed_accepted": observed,
        "expected_accepted": expected,
        "outcome": outcome,
        "observed_relationship": observed_decision.get("relationship", ""),
        "observed_confidence": observed_decision.get("confidence", ""),
        "expected_relationship": expected_decision.get("relationship", ""),
        "review_note": case.get("review_note", ""),
    }


def _summarize_story(results):
    observed_matches = sum(1 for result in results if result["observed_accepted"])
    expected_matches = sum(1 for result in results if result["expected_accepted"])
    correct = sum(1 for result in results if result["outcome"].startswith("correct_"))
    false_merges = sum(1 for result in results if result["outcome"] == "false_merge")
    false_splits = sum(1 for result in results if result["outcome"] == "false_split")
    return {
        "cases": len(results),
        "observed_matches": observed_matches,
        "expected_matches": expected_matches,
        "correct": correct,
        "false_merges": false_merges,
        "false_splits": false_splits,
        "accuracy": _ratio(correct, len(results)),
        "false_merge_rate": _ratio(false_merges, observed_matches),
        "false_split_rate": _ratio(false_splits, expected_matches),
    }


def _summarize_arc(results):
    observed_attachments = sum(1 for result in results if result["observed_accepted"])
    expected_attachments = sum(1 for result in results if result["expected_accepted"])
    correct = sum(1 for result in results if result["outcome"].startswith("correct_"))
    false_arcs = sum(1 for result in results if result["outcome"] == "false_arc")
    missed_arcs = sum(1 for result in results if result["outcome"] == "missed_arc")
    return {
        "cases": len(results),
        "observed_attachments": observed_attachments,
        "expected_attachments": expected_attachments,
        "correct": correct,
        "false_arcs": false_arcs,
        "missed_arcs": missed_arcs,
        "accuracy": _ratio(correct, len(results)),
        "false_arc_rate": _ratio(false_arcs, observed_attachments),
        "missed_arc_rate": _ratio(missed_arcs, expected_attachments),
    }


def _failures(results, limit=8):
    failure_outcomes = {"false_merge", "false_split", "false_arc", "missed_arc"}
    return [
        {
            "case_id": result["case_id"],
            "outcome": result["outcome"],
            "today_label": result["today_label"],
            "candidate": result["candidate"],
            "observed_relationship": result["observed_relationship"],
            "observed_confidence": result["observed_confidence"],
            "review_note": result["review_note"],
        }
        for result in results
        if result["outcome"] in failure_outcomes
    ][:limit]


def run_eval(story_cases, arc_cases, *, story_dataset=None, arc_dataset=None):
    story_results = [
        evaluate_case(case, index=index)
        for index, case in enumerate(story_cases)
    ]
    arc_results = [
        evaluate_case(case, index=index)
        for index, case in enumerate(arc_cases)
    ]
    story_summary = _summarize_story(story_results)
    arc_summary = _summarize_arc(arc_results)
    return {
        "created_at": _utc_now(),
        "mode": MODE,
        "git_sha": _git_sha(),
        "working_tree": _working_tree_state(),
        "datasets": {
            "story_match": str(story_dataset) if story_dataset else None,
            "arc_assignment": str(arc_dataset) if arc_dataset else None,
        },
        "case_count": len(story_results) + len(arc_results),
        "models": {
            "story_match_verifier": STORY_MATCH_VERIFIER_MODEL,
            "arc_assignment": ARC_ASSIGNMENT_MODEL,
        },
        "prompt_versions": {
            "story_match_verifier": story_matching.VERIFY_PROMPT_VERSION,
            "arc_assignment": story_matching.ARC_ASSIGNMENT_PROMPT_VERSION,
        },
        "summary": {
            "story_match": story_summary,
            "arc_assignment": arc_summary,
            "headline": {
                "false_merge_rate": story_summary["false_merge_rate"],
                "false_split_rate": story_summary["false_split_rate"],
                "false_arc_rate": arc_summary["false_arc_rate"],
            },
        },
        "representative_failures": {
            "story_match": _failures(story_results),
            "arc_assignment": _failures(arc_results),
        },
        "results": {
            "story_match": story_results,
            "arc_assignment": arc_results,
        },
    }


def write_report(report, output_path=None):
    if output_path is None:
        output_path = DEFAULT_REPORT_DIR / f"story_match_{_report_stamp()}.json"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


def _metric_line(label, summary, metric_names):
    metrics = ", ".join(
        f"{name.replace('_', ' ')} {_percent(summary.get(name))}"
        for name in metric_names
    )
    return f"{label}: {summary['cases']} cases, {metrics}, accuracy {_percent(summary['accuracy'])}"


def format_summary(report):
    story = report["summary"]["story_match"]
    arc = report["summary"]["arc_assignment"]
    lines = [
        "Story matching eval",
        f"Mode: {report['mode']}",
        f"Story dataset: {report['datasets']['story_match'] or 'in-memory'}",
        f"Arc dataset: {report['datasets']['arc_assignment'] or 'in-memory'}",
        f"Cases: {report['case_count']}",
        _metric_line("story_match", story, ("false_merge_rate", "false_split_rate")),
        _metric_line("arc_assignment", arc, ("false_arc_rate", "missed_arc_rate")),
    ]
    failures = report.get("representative_failures", {})
    for section in ("story_match", "arc_assignment"):
        items = failures.get(section) or []
        if not items:
            continue
        lines.append(f"{section} failures:")
        for item in items[:5]:
            lines.append(
                "- "
                f"{item['case_id']} [{item['outcome']}]: "
                f"{item['today_label']} -> {item['candidate']} "
                f"(observed {item['observed_relationship'] or 'n/a'}/"
                f"{item['observed_confidence'] or 'n/a'})"
            )
    return "\n".join(lines)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Score reviewed story-match and arc-assignment decisions without LLM calls."
    )
    parser.add_argument("--story-dataset", type=Path, default=DEFAULT_STORY_DATASET)
    parser.add_argument("--arc-dataset", type=Path, default=DEFAULT_ARC_DATASET)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Print summary without writing a JSON report",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    story_cases = load_cases(args.story_dataset, "story_match")
    arc_cases = load_cases(args.arc_dataset, "arc_assignment")
    if args.limit is not None:
        story_cases = story_cases[:args.limit]
        arc_cases = arc_cases[:args.limit]
    report = run_eval(
        story_cases,
        arc_cases,
        story_dataset=args.story_dataset,
        arc_dataset=args.arc_dataset,
    )
    print(format_summary(report))
    if not args.no_write:
        output_path = write_report(report, args.output)
        print(f"Report written: {output_path}")
    return report


if __name__ == "__main__":
    main()
