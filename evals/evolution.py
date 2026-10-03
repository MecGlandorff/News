"""Preserve chronological story replays for separately reviewed timeline judgments.

The rubric is never sent to the news model. This runner does not turn selected
semantic questions into an automatic overall-quality score.
"""

import argparse
import math
import platform
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from evals.historical import write
from evals.replay import read, sha256
from news import codex, pipeline
from news.domain import canonical, validate_input


def preflight(prepared: Path, rubric: Path, review: Path):
    manifest, criteria, cross_review = read(prepared / "manifest.json"), read(rubric), read(review)
    if not all(isinstance(item, dict) for item in (manifest, criteria, cross_review)):
        raise ValueError("manifest, rubric and review must be objects")
    if criteria.get("prepared_manifest_sha256") != sha256(prepared / "manifest.json"):
        raise ValueError("rubric does not match prepared manifest")
    reviewed_hashes = cross_review.get("original_hashes", {})
    if not isinstance(reviewed_hashes, dict) or not {
        sha256(rubric),
        sha256(prepared / "manifest.json"),
    } <= set(reviewed_hashes.values()):
        raise ValueError("independent review does not bind this rubric and manifest")
    batches = manifest.get("batches")
    if not isinstance(batches, list) or not batches:
        raise ValueError("manifest needs nonempty batches")
    snapshots, keys, names = [], set(), set()
    hashes = {"manifest.json": sha256(prepared / "manifest.json")}
    for batch in batches:
        name = batch.get("file") if isinstance(batch, dict) else None
        if not isinstance(name, str) or Path(name).name != name or name in names:
            raise ValueError("batch filenames must be unique basenames")
        path = prepared / name
        if path.resolve().parent != prepared.resolve():
            raise ValueError("batch file escapes prepared directory")
        hashes[name] = sha256(path)
        if batch.get("sha256") != hashes[name]:
            raise ValueError("batch differs from frozen hash")
        snapshot = validate_input(read(path))
        if batch.get("day") != snapshot["day"] or batch.get("articles") != len(
            snapshot["articles"]
        ):
            raise ValueError("batch metadata differs from input")
        if snapshots and snapshot["day"] < snapshots[-1]["day"]:
            raise ValueError("batches must be chronological")
        for article in snapshot["articles"]:
            key = (snapshot["day"], article["id"])
            if key in keys:
                raise ValueError("duplicate capture-day article ID")
            keys.add(key)
        names.add(name)
        snapshots.append(snapshot)
    questions = criteria.get("applicable_original_questions")
    if questions is None:
        questions = [q for t in criteria.get("trajectories", []) for q in t["evaluation_questions"]]
    if not isinstance(questions, list) or not questions:
        raise ValueError("rubric needs semantic questions")
    question_ids = set()
    for question in questions:
        if question["id"] in question_ids or not question.get("required_article_refs"):
            raise ValueError("questions need unique IDs and source references")
        question_ids.add(question["id"])
        for ref in question["required_article_refs"]:
            if (ref["day"], ref["article_id"]) not in keys:
                raise ValueError("question references an absent source capture")
    return manifest, criteria, cross_review, snapshots, hashes


def execute(engine, snapshot, state, timeout):
    if engine == "events":
        return pipeline.run(snapshot, state, strategy="single", timeout=timeout)
    from news import trajectory

    return trajectory.run(snapshot, state, timeout=timeout)


def render_story(state, story_id):
    from news import trajectory

    return trajectory.story(state, story_id)


def evaluate(
    prepared: Path, rubric: Path, review: Path, output: Path, *, engine, max_calls, timeout=360
):
    if engine not in {"events", "stories"} or type(max_calls) is not int or max_calls < 1:
        raise ValueError("invalid engine or call budget")
    if not math.isfinite(timeout) or not 1 <= timeout <= 1800:
        raise ValueError("timeout must be finite and between 1 and 1800")
    if output.exists():
        raise ValueError("output exists; use a fresh directory")
    manifest, criteria, cross_review, snapshots, hashes = preflight(prepared, rubric, review)
    if len(snapshots) > max_calls:
        raise ValueError("plan exceeds call budget")
    version = subprocess.run(
        ["codex", "--version"], capture_output=True, text=True, check=True, timeout=10
    ).stdout.strip()
    root = Path(__file__).resolve().parents[1]
    source_files = sorted(
        {
            *root.glob("news/*.py"),
            *root.glob("news/tasks/*"),
            Path(__file__),
            root / "evals/historical.py",
            root / "evals/replay.py",
            root / "pyproject.toml",
        }
    )
    output.mkdir(parents=True)
    write(
        output / "manifest.json",
        {
            "created_at": datetime.now(UTC).isoformat(),
            "engine": engine,
            "model": codex.MODEL,
            "reasoning_effort": codex.REASONING_EFFORT,
            "codex_version": version,
            "codex_config": codex.CONFIG,
            "python": platform.python_version(),
            "timeout_per_call": timeout,
            "max_calls": max_calls,
            "planned_calls": len(snapshots),
            "prepared_files": hashes,
            "rubric_sha256": sha256(rubric),
            "review_sha256": sha256(review),
            "source_files": {str(p.relative_to(root)): sha256(p) for p in source_files},
            "source_manifest": manifest,
        },
    )
    write(output / "rubric.json", criteria)
    write(output / "label-cross-review.json", cross_review)
    state, start = output / "state", time.monotonic()
    report = {
        "completed": False,
        "engine": engine,
        "batches": [],
        "failures": [],
        "calls": [],
        "assigned_records": 0,
        "semantic_review": "Pending separate review of reader-facing outputs",
        "interpretation": "Purposive trajectories; not representative system accuracy. Capture dates "
        "are observations, not automatically occurrence dates. Missing usage remains unknown.",
    }
    known_inputs, stories, briefings = set(), set(), []
    write(output / "report.json", report)
    for batch, snapshot in zip(manifest["batches"], snapshots, strict=True):
        begun, interruption = time.monotonic(), None
        entry = {
            "file": batch["file"],
            "day": snapshot["day"],
            "articles": len(snapshot["articles"]),
            "error": None,
            "request_chars": None,
        }
        try:
            result, reused = execute(engine, snapshot, state, timeout)
            if reused:
                raise RuntimeError("unexpected cached decision in fresh state")
            entry["run_id"] = result["run_id"]
            report["assigned_records"] += len(snapshot["articles"])
            directory = state / "runs" / result["run_id"]
            briefings.append((directory / "briefing.md").read_text(encoding="utf-8"))
            stories.update(s["id"] for s in result.get("stories", []))
        except BaseException as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"
            if not isinstance(exc, Exception):
                interruption = exc
        inputs = set(state.glob("runs/*/input.json")) - known_inputs
        known_inputs.update(inputs)
        entry["artifacts"] = [str(p.parent.relative_to(output)) for p in sorted(inputs)]
        for path in sorted(inputs):
            entry["request_chars"] = len(canonical(read(path)))
            retrieval = path.with_name("retrieval.json")
            if retrieval.exists():
                entry["retrieval"] = read(retrieval)
            report["calls"].extend(read(p) for p in sorted(path.parent.glob("*/metadata.json")))
        entry["duration_seconds"] = round(time.monotonic() - begun, 3)
        report["batches"].append(entry)
        report["duration_seconds"] = round(time.monotonic() - start, 3)
        if entry["error"]:
            report["failures"].append(dict(entry))
        usage = {}
        for call in report["calls"]:
            for key, value in (call.get("usage") or {}).items():
                if type(value) is int and value >= 0:
                    usage[key] = usage.get(key, 0) + value
        report["reported_usage"] = usage
        report["calls_without_usage"] = sum(c.get("usage") is None for c in report["calls"])
        write(output / "report.json", report)
        print(f"{engine} {batch['file']}: {entry['error'] or 'accepted'}", flush=True)
        if interruption:
            raise interruption
        if entry["error"]:
            break
    else:
        report["completed"] = True
    (output / "daily-briefings.md").write_text("\n\n---\n\n".join(briefings), encoding="utf-8")
    report["reader_outputs"] = ["daily-briefings.md"]
    if stories:
        (output / "timelines").mkdir()
        for sid in sorted(stories):
            name = f"timelines/{sid}.md"
            try:
                if Path(sid).name != sid:
                    raise ValueError("invalid materialized story ID")
                (output / name).write_text(render_story(state, sid), encoding="utf-8")
                report["reader_outputs"].append(name)
            except Exception as exc:
                report["completed"] = False
                report["failures"].append(
                    {
                        "phase": "timeline_export",
                        "story_id": sid,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
    report["reader_output_sha256"] = {
        name: sha256(output / name) for name in report["reader_outputs"]
    }
    write(output / "report.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("prepared", "rubric", "review", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--engine", choices=("events", "stories"), required=True)
    parser.add_argument("--max-calls", type=int, required=True)
    parser.add_argument("--timeout", type=float, default=360)
    args = parser.parse_args(argv)
    try:
        report = evaluate(**vars(args))
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"evolution: {exc}\n")
    return 0 if report["completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
