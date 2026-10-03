"""Bounded, repeatable live comparisons; ordinary pytest never invokes this."""

import argparse
import hashlib
import json
import math
import platform
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from evals.scoring import score_case
from news import codex
from news.domain import canonical, validate_input
from news.pipeline import analyze


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_cases(path: Path, selected: list[str] | None = None) -> list[dict]:
    cases = json.loads(path.read_text())
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases must be a nonempty JSON list")
    ids = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            raise ValueError("each case needs a string ID")
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", case["id"]) or case["id"] in ids:
            raise ValueError("case IDs must be unique, short, filesystem-safe names")
        ids.add(case["id"])
        payload = case["input"]
        validate_input({"day": payload["day"], "articles": payload["articles"]})
        known = {item["id"] for item in payload["articles"]}
        expected = case["expected"]
        members = [item for group in expected["groups"] for item in group]
        if set(members) != known or len(members) != len(known):
            raise ValueError("expected groups must cover every article exactly once")
        if set(expected["continuations"]) != known:
            raise ValueError("expected continuations must cover every article")
        memory = {event["id"] for event in payload["memory"]}
        if any(
            value is not None and value not in memory
            for value in expected["continuations"].values()
        ):
            raise ValueError("expected continuation refers to unknown memory")
        score_case(case, None)  # Validate complete gold labels before paid execution.
    if selected:
        if not set(selected) <= ids:
            raise ValueError("unknown selected case ID")
        cases = [case for case in cases if case["id"] in selected]
    return cases


def summarize(trials: list[dict]) -> dict:
    summary = {}
    for strategy in sorted({trial["strategy"] for trial in trials}):
        group = [trial for trial in trials if trial["strategy"] == strategy]
        scores = [trial["score"] for trial in group]
        tp = sum(score["pairwise_tp"] for score in scores)
        fp = sum(score["pairwise_fp"] for score in scores)
        fn = sum(score["pairwise_fn"] for score in scores)
        correct = sum(score["continuation_correct"] for score in scores)
        total = sum(score["continuation_total"] for score in scores)
        metadata = [call for trial in group for call in trial["calls"]]
        usage = [call["usage"] for call in metadata if call.get("usage") is not None]
        summary[strategy] = {
            "trials": len(group),
            "errors": sum(trial["error"] is not None for trial in group),
            "strict_passes": sum(score["strict_pass"] for score in scores),
            "exact_partitions": sum(score["exact_partition"] for score in scores),
            "mean_pairwise_f1": sum(score["pairwise_f1"] for score in scores) / len(scores),
            "pairwise_tp": tp,
            "pairwise_fp": fp,
            "pairwise_fn": fn,
            "continuation_accuracy": correct / total if total else 0,
            "evidence_quote_errors": sum(score["evidence_quote_errors"] for score in scores),
            "duration_seconds": sum(trial["duration_seconds"] for trial in group),
            "calls": len(metadata),
            "calls_with_usage": len(usage),
            "reported_usage": {
                key: sum(item.get(key, 0) for item in usage)
                for key in {key for item in usage for key in item}
            },
        }
    return summary


def run(
    cases: list[dict],
    strategies: list[str],
    output: Path,
    *,
    repeats: int = 2,
    max_calls: int = 96,
    max_seconds: float = 1800,
    timeout: float = 120,
) -> dict:
    if (
        not strategies
        or len(set(strategies)) != len(strategies)
        or not set(strategies) <= {"single", "staged"}
    ):
        raise ValueError("choose each of single/staged at most once")
    if not 1 <= repeats <= 20:
        raise ValueError("repeats must be between 1 and 20")
    if not all(math.isfinite(number) and number > 0 for number in (max_seconds, timeout)):
        raise ValueError("time limits must be positive finite numbers")
    planned = len(cases) * repeats * sum(1 if value == "single" else 2 for value in strategies)
    if not 1 <= planned <= max_calls:
        raise ValueError(f"experiment needs at most {planned} calls; max_calls is {max_calls}")
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    paths = [*root.glob("news/*.py"), *root.glob("news/tasks/*"), *root.glob("evals/*.py")]
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": codex.MODEL,
        "reasoning_effort": codex.REASONING_EFFORT,
        "python": platform.python_version(),
        "strategies": strategies,
        "repeats": repeats,
        "max_calls": max_calls,
        "max_seconds": max_seconds,
        "timeout_seconds": timeout,
        "planned_calls": planned,
        "cases_sha256": hashlib.sha256(canonical(cases).encode()).hexdigest(),
        "sources": {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths)
        },
    }
    try:
        version = subprocess.run(["codex", "--version"], text=True, capture_output=True, timeout=5)
        manifest["codex_version"] = version.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        manifest["codex_version"] = None
    write(output / "manifest.json", manifest)
    write(output / "cases.json", cases)
    started = time.monotonic()
    trials, completed = [], True
    for repeat in range(1, repeats + 1):
        for case in cases:
            for strategy in strategies:
                remaining = max_seconds - (time.monotonic() - started)
                calls_needed = 1 if strategy == "single" else 2
                if remaining < 1:
                    completed = False
                    break
                directory = output / f"{repeat:02d}-{case['id']}-{strategy}"
                directory.mkdir()
                begun = time.monotonic()
                error, response = None, None
                try:
                    response = analyze(
                        case["input"],
                        strategy,
                        directory,
                        timeout=min(timeout, remaining / calls_needed),
                    )
                    write(directory / "response.json", response)
                except (RuntimeError, ValueError, OSError) as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    terminal = "single" if strategy == "single" else "group"
                    try:
                        response = json.loads((directory / terminal / "final.json").read_text())
                        write(directory / "response.json", response)
                    except (OSError, ValueError):
                        pass
                calls = [
                    json.loads(path.read_text())
                    for path in sorted(directory.glob("*/metadata.json"))
                ]
                score = score_case(case, response)
                score["strict_pass"] = score["strict_pass"] and error is None
                trial = {
                    "case": case["id"],
                    "strategy": strategy,
                    "repeat": repeat,
                    "duration_seconds": round(time.monotonic() - begun, 3),
                    "error": error,
                    "score": score,
                    "calls": calls,
                }
                write(directory / "trial.json", trial)
                trials.append(trial)
                report = {"completed": False, "summary": summarize(trials), "trials": trials}
                write(output / "report.json", report)
                print(
                    f"{repeat}/{repeats} {strategy} {case['id']}: "
                    f"{'PASS' if trial['score']['strict_pass'] else 'FAIL'}"
                    f"{': ' + error if error else ''}",
                    flush=True,
                )
            if not completed:
                break
        if not completed:
            break
    report = {"completed": completed, "summary": summarize(trials), "trials": trials}
    write(output / "report.json", report)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path("evals/cases.json"))
    parser.add_argument("--case-id", action="append")
    parser.add_argument(
        "--strategy", nargs="+", choices=["single", "staged"], default=["single", "staged"]
    )
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--max-calls", type=int, default=96)
    parser.add_argument("--max-seconds", type=float, default=1800)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = run(
            load_cases(args.cases, args.case_id),
            args.strategy,
            args.output,
            repeats=args.repeats,
            max_calls=args.max_calls,
            max_seconds=args.max_seconds,
            timeout=args.timeout,
        )
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f"experiment: {exc}\n")
    print(json.dumps(result["summary"], indent=2))
    return (
        0
        if result["completed"]
        and all(row["strict_passes"] == row["trials"] for row in result["summary"].values())
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
