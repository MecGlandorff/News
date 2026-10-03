"""Replay frozen source batches against independent agent labels, without retries."""

import argparse
import hashlib
import json
import math
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

from evals.historical import compare, write
from news import codex, pipeline
from news.domain import canonical, validate_input
from news.pipeline import run


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preflight(prepared: Path, labels: Path) -> tuple[dict, dict, list, dict]:
    manifest, label_document = read(prepared / "manifest.json"), read(labels)
    if not isinstance(manifest, dict) or not isinstance(label_document, dict):
        raise ValueError("manifest and labels must be objects")
    batches = manifest.get("batches")
    if not isinstance(batches, list) or not batches:
        raise ValueError("prepared manifest needs nonempty batches")
    snapshots, positions, names = [], {}, set()
    hashes = {"manifest.json": sha256(prepared / "manifest.json")}
    for index, batch in enumerate(batches):
        name = batch.get("file") if isinstance(batch, dict) else None
        if not isinstance(name, str) or Path(name).name != name or name in names:
            raise ValueError("batch filenames must be unique basenames")
        path = prepared / name
        if path.resolve().parent != prepared.resolve():
            raise ValueError("batch files must stay inside prepared directory")
        snapshot = validate_input(read(path))
        if batch.get("day") != snapshot["day"] or batch.get("articles") != len(
            snapshot["articles"]
        ):
            raise ValueError("batch metadata disagrees with snapshot")
        if snapshots and snapshot["day"] < snapshots[-1]["day"]:
            raise ValueError("batches must be chronological")
        for article in snapshot["articles"]:
            key = (snapshot["day"], article["id"])
            if key in positions:
                raise ValueError("duplicate article ID within a capture day")
            positions[key] = index
        snapshots.append(snapshot)
        names.add(name)
        hashes[name] = sha256(path)
    cases = label_document.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("labels need a nonempty cases list")
    seen = set()
    for case in cases:
        fields = (
            "case_id",
            "layer",
            "today_date",
            "today_article_id",
            "candidate_date",
            "candidate_article_id",
            "review_note",
        )
        if not isinstance(case, dict) or any(
            not isinstance(case.get(k), str) or not case[k].strip() for k in fields
        ):
            raise ValueError("label fields must be nonempty strings")
        aliases = case.get("candidate_article_ids", [])
        if not isinstance(aliases, list) or any(not isinstance(x, str) or not x for x in aliases):
            raise ValueError("candidate aliases must be string IDs")
        if type(case.get("expected_accepted")) is not bool or case["case_id"] in seen:
            raise ValueError("labels need unique case IDs and boolean expected_accepted")
        same_day = case["today_date"] == case["candidate_date"]
        if (
            case["layer"] != ("same_day" if same_day else "story")
            or case["candidate_date"] > case["today_date"]
        ):
            raise ValueError("label layer or chronological direction is invalid")
        keys = [
            (case["today_date"], case["today_article_id"]),
            *[
                (case["candidate_date"], value)
                for value in [case["candidate_article_id"], *aliases]
            ],
        ]
        if len(set(keys)) != len(keys) or any(key not in positions for key in keys):
            raise ValueError("label references an unknown or repeated article")
        seen.add(case["case_id"])
    declared = label_document.get("input_hashes", {})
    expected = dict(declared.get("prepared_files", declared))
    if "prepared_manifest_sha256" in declared:
        expected["manifest.json"] = declared["prepared_manifest_sha256"]
    for name, expected_hash in expected.items():
        if hashes.get(Path(name).name) != expected_hash:
            raise ValueError(f"labels were frozen against different input: {name}")
    return manifest, label_document, snapshots, hashes


def score(cases, assignments, observations, positions, attempted):
    rows = compare(assignments, cases)
    for case, row in zip(cases, rows, strict=True):
        current = (case["today_date"], case["today_article_id"])
        candidates = [
            (case["candidate_date"], value)
            for value in [case["candidate_article_id"], *case.get("candidate_article_ids", [])]
        ]
        row["status"] = (
            "unprocessed"
            if any(key not in attempted for key in [current, *candidates])
            else "unavailable"
            if row["missing_assignment"]
            else "scored"
        )
        row["candidate_context"] = []
        for candidate in candidates:
            observer, target = (
                (candidate, current)
                if positions[candidate] > positions[current]
                else (current, candidate)
            )
            payload = observations.get(observer)
            event_id = assignments.get(target)
            same_batch = bool(
                payload
                and payload["day"] == target[0]
                and any(a["id"] == target[1] for a in payload["articles"])
            )
            memory = payload.get("memory", []) if payload else []
            event_present = event_id is not None and any(e["id"] == event_id for e in memory)
            source_present = same_batch or any(
                q["article_id"] == target[1]
                for event in memory
                if event["id"] == event_id
                for q in [*event.get("evidence", []), *event.get("history", [])]
            )
            presence = (
                "unprocessed"
                if payload is None
                else "same_batch"
                if same_batch
                else "past_event_memory"
                if event_present
                else "omitted"
            )
            row["candidate_context"].append(
                {
                    "observed_at": {"day": observer[0], "article_id": observer[1]},
                    "target": {"day": target[0], "article_id": target[1]},
                    "presence": presence,
                    "event_id_present": event_present,
                    "source_article_id_present": source_present,
                }
            )
    return rows


def summarize(rows, calls):
    usage = {}
    for call in calls:
        for key, value in (call.get("usage") or {}).items():
            if type(value) is int and value >= 0:
                usage[key] = usage.get(key, 0) + value
    return {
        "correct_pairs": sum(row["correct"] for row in rows),
        "incorrect_merges": sum(
            row["accepted"] is True and not row["expected_accepted"] for row in rows
        ),
        "missed_positive_connections": sum(
            row["accepted"] is False and row["expected_accepted"] for row in rows
        ),
        "unavailable_pairs": sum(row["status"] == "unavailable" for row in rows),
        "unprocessed_pairs": sum(row["status"] == "unprocessed" for row in rows),
        "calls": len(calls),
        "calls_with_usage": sum(call.get("usage") is not None for call in calls),
        "reported_usage": usage,
    }


def evaluate(
    prepared: Path, labels: Path, output: Path, *, repeats=1, max_calls=20, timeout=180
) -> dict:
    if (
        type(repeats) is not int
        or not 1 <= repeats <= 20
        or type(max_calls) is not int
        or max_calls < 1
    ):
        raise ValueError("invalid repeat or call budget")
    if not math.isfinite(timeout) or not 1 <= timeout <= 1800:
        raise ValueError("timeout must be finite and between 1 and 1800 seconds")
    if output.exists():
        raise ValueError("output directory already exists; choose a fresh destination")
    manifest, label_document, snapshots, hashes = preflight(prepared, labels)
    if len(snapshots) * repeats > max_calls:
        raise ValueError("replay plan exceeds max_calls")
    output.mkdir(parents=True)
    root = Path(__file__).resolve().parents[1]
    paths = [
        *root.glob("news/*.py"),
        *root.glob("news/tasks/*"),
        Path(__file__),
        root / "evals/historical.py",
        root / "pyproject.toml",
    ]
    runtime = {
        "model": codex.MODEL,
        "reasoning_effort": codex.REASONING_EFFORT,
        "strategy": "single",
        "timeout_per_call": timeout,
        "repeats": repeats,
        "max_calls": max_calls,
        "planned_calls": len(snapshots) * repeats,
        "memory_days": pipeline.MEMORY_DAYS,
        "max_request_chars": pipeline.MAX_REQUEST_CHARS,
        "python": platform.python_version(),
        "codex_overrides": codex.CONFIG,
    }
    write(
        output / "manifest.json",
        {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "runtime": runtime,
            "source_snapshots": manifest.get("sources", manifest.get("source_days", [])),
            "source_files": {str(p.relative_to(root)): sha256(p) for p in sorted(paths)},
            "prepared_files": hashes,
            "labels_sha256": sha256(labels),
        },
    )
    write(output / "labels.json", label_document)
    report = {
        "completed": False,
        "label_scope": "independent agent judgments, not human gold; selected pairs only",
        "context_scope": "Article-ID presence within the target event is not proof that the "
        "original occurrence, exact quote, or event-identifying anchor was retained.",
        "input_manifest": manifest,
        "replays": [],
    }
    write(output / "report.json", report)
    positions = {(s["day"], a["id"]): i for i, s in enumerate(snapshots) for a in s["articles"]}
    for repeat in range(1, repeats + 1):
        state, begun = output / f"replay-{repeat}", time.monotonic()
        assignments, observations, attempted, known_inputs, calls = {}, {}, set(), set(), []
        replay = {"repeat": repeat, "completed": False, "batches": [], "failures": []}
        report["replays"].append(replay)
        for batch, snapshot in zip(manifest["batches"], snapshots, strict=True):
            attempted.update((snapshot["day"], a["id"]) for a in snapshot["articles"])
            batch_started, interruption = time.monotonic(), None
            entry = {
                "file": batch["file"],
                "day": snapshot["day"],
                "error": None,
                "request_chars": None,
                "memory_event_count": None,
                "history_quote_count": None,
            }
            try:
                result, reused = run(snapshot, state, strategy="single", timeout=timeout)
                if reused:
                    raise RuntimeError("unexpected cached result in a fresh replay")
                entry["run_id"] = result["run_id"]
                for event in result["events"]:
                    for article_id in event["article_ids"]:
                        assignments[(snapshot["day"], article_id)] = event["id"]
            except BaseException as exc:
                entry["error"] = f"{type(exc).__name__}: {exc}"
                replay["failures"].append(dict(entry))
                if not isinstance(exc, Exception):
                    interruption = exc
            inputs = set(state.glob("runs/*/input.json")) - known_inputs
            known_inputs.update(inputs)
            entry["artifacts"] = [str(p.parent.relative_to(output)) for p in sorted(inputs)]
            for path in inputs:
                payload = read(path)
                entry.update(
                    request_chars=len(canonical(payload)),
                    memory_event_count=len(payload["memory"]),
                    history_quote_count=sum(len(e.get("history", [])) for e in payload["memory"]),
                )
                for article in payload["articles"]:
                    observations[(payload["day"], article["id"])] = payload
                calls.extend(read(p) for p in sorted(path.parent.glob("*/metadata.json")))
            entry["duration_seconds"] = round(time.monotonic() - batch_started, 3)
            replay["batches"].append(entry)
            replay["scored_cases"] = score(
                label_document["cases"], assignments, observations, positions, attempted
            )
            replay.update(
                summary=summarize(replay["scored_cases"], calls),
                calls=calls,
                duration_seconds=round(time.monotonic() - begun, 3),
                assigned_articles=len(assignments),
            )
            write(
                output / f"assignments-{repeat}.json",
                [
                    {"day": day, "article_id": aid, "event_id": event}
                    for (day, aid), event in sorted(assignments.items())
                ],
            )
            write(output / "report.json", report)
            print(
                f"Replay {repeat}/{repeats} {batch['file']}: {entry['error'] or 'accepted'}",
                flush=True,
            )
            if interruption:
                raise interruption
            if entry["error"]:
                break
        else:
            replay["completed"] = True
        write(output / "report.json", report)
    report["completed"] = all(replay["completed"] for replay in report["replays"])
    write(output / "report.json", report)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("prepared", "labels", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--max-calls", type=int, required=True)
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args(argv)
    try:
        report = evaluate(**vars(args))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f"replay: {exc}\n")
    return (
        0
        if report["completed"]
        and all(row["correct"] for replay in report["replays"] for row in replay["scored_cases"])
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
