"""Replay frozen legacy RSS snapshots through the rebuild, without old model labels."""

import argparse
import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from news import codex
from news.domain import validate_input
from news.feeds import plain_text
from news.pipeline import run


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def snapshot_article(raw: dict) -> dict:
    """Title and RSS description are source evidence; classifications are not."""
    value = raw["published_at"]
    try:
        published = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        published = parsedate_to_datetime(value)
    if published.tzinfo is None:
        raise ValueError("archived publication timestamp has no timezone")
    title = plain_text(raw["title"])
    description = plain_text(raw.get("description", ""))
    return {
        "id": raw["id"],
        "source": raw["source"],
        "url": raw["url"],
        "published_at": published.isoformat(),
        "title": title,
        "text": "\n\n".join(part for part in (title, description) if part),
    }


def prepare(archive: Path, destination: Path) -> dict:
    """Export every row in original snapshot order; never silently drop a source."""
    if destination.exists():
        raise ValueError("prepared snapshot directory already exists")
    snapshots = sorted((archive / "data/daily").glob("*/articles.json"))
    if not snapshots:
        raise ValueError("no archived daily snapshots")
    batches, sources = [], []
    for source in snapshots:
        raw = json.loads(source.read_text())
        if not isinstance(raw, list) or not raw:
            raise ValueError("daily snapshot must be a nonempty article list")
        ids = [article["id"] for article in raw]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate article IDs in archived day")
        day = source.parent.name
        articles = [snapshot_article(article) for article in raw]
        sources.append(
            {
                "day": day,
                "articles": len(articles),
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "empty_descriptions": sum(not a.get("description", "").strip() for a in raw),
            }
        )
        current = []
        for article in articles:
            validate_input({"day": day, "articles": [article]})
            if current:
                try:
                    validate_input({"day": day, "articles": current + [article]})
                except ValueError:
                    batches.append({"day": day, "articles": current})
                    current = []
            current.append(article)
        if current:
            batches.append({"day": day, "articles": current})
    destination.mkdir(parents=True)
    paths = []
    for number, batch in enumerate(batches, 1):
        path = destination / f"{number:02d}-{batch['day']}.json"
        write(path, batch)
        paths.append({"file": path.name, "day": batch["day"], "articles": len(batch["articles"])})
    manifest = {
        "source_days": sources,
        "batches": paths,
        "article_count": sum(row["articles"] for row in sources),
        "evidence": "captured title plus HTML-stripped RSS description; bodies excluded",
        "order": "chronological days, original snapshot order, greedy bounded batches",
        "generated_fields_excluded": ["theme", "importance", "story_label", "occurrence_id"],
    }
    write(destination / "manifest.json", manifest)
    return manifest


def load_reviews(archive: Path) -> tuple[list[dict], list[dict]]:
    path = archive / "evals/datasets/matching_reconstruction_review_2026-07-21_22.jsonl"
    reviews = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    included, excluded = [], []
    for case in reviews:
        if case["layer"] == "arc":
            excluded.append(
                {"case_id": case["case_id"], "reason": "named arcs outside rebuild contract"}
            )
        elif case.get("review_status") == "insufficient_evidence":
            excluded.append({"case_id": case["case_id"], "reason": case["evidence_gap"]})
        else:
            included.append(case)
    return included, excluded


def compare(assignments: dict, reviews: list[dict]) -> list[dict]:
    results = []
    for case in reviews:
        current = assignments.get((case["today_date"], case["today_article_id"]))
        ids = [case["candidate_article_id"], *case.get("candidate_article_ids", [])]
        candidates = [assignments.get((case["candidate_date"], value)) for value in ids]
        missing = current is None or any(value is None for value in candidates)
        accepted = current in candidates if not missing else None
        results.append(
            {
                "case_id": case["case_id"],
                "layer": case["layer"],
                "expected_accepted": case["expected_accepted"],
                "accepted": accepted,
                "correct": accepted == case["expected_accepted"] if not missing else False,
                "missing_assignment": missing,
                "current_event": current,
                "candidate_events": candidates,
                "review_note": case["review_note"],
            }
        )
    return results


def historical_baseline(archive: Path, reviews: list[dict]) -> dict:
    """Read run-scoped historical decisions rather than a later mutable projection."""
    assignments, runs = {}, set()
    db = sqlite3.connect((archive / "source-archive.db").resolve().as_uri() + "?mode=ro", uri=True)
    try:
        for source in sorted((archive / "data/daily").glob("*/articles.json")):
            for article in json.loads(source.read_text()):
                rows = db.execute(
                    "SELECT run_id, story_id FROM occurrence_assignment_history WHERE occurrence_id=?",
                    (article["occurrence_id"],),
                ).fetchall()
                if len(rows) != 1:
                    raise ValueError("ambiguous or missing run-scoped historical assignment")
                run_id, story_id = rows[0]
                runs.add(run_id)
                assignments[(source.parent.name, article["id"])] = str(story_id)
        metadata = [
            dict(zip(["run_id", "date", "git_sha", "status"], row))
            for run_id in sorted(runs)
            for row in db.execute(
                "SELECT run_id,run_date,git_sha,status FROM runs WHERE run_id=?", (run_id,)
            )
        ]
    finally:
        db.close()
    return {
        "type": "historical live-run assignments; no legacy model rerun",
        "runs": metadata,
        "scored_cases": compare(assignments, reviews),
        "assigned_articles": len(assignments),
    }


def evaluate(
    archive: Path,
    prepared: Path,
    output: Path,
    *,
    repeats: int = 2,
    max_calls: int = 8,
    timeout: float = 180,
) -> dict:
    manifest = json.loads((prepared / "manifest.json").read_text())
    if not 1 <= repeats <= 5 or repeats * len(manifest["batches"]) > max_calls:
        raise ValueError("replay plan exceeds repeat or call budget")
    if output.exists():
        raise ValueError("output directory already exists")
    if not 1 <= timeout <= 1800 or not manifest["batches"]:
        raise ValueError("invalid replay timeout or empty batch plan")
    snapshots = [
        json.loads((prepared / batch["file"]).read_text()) for batch in manifest["batches"]
    ]
    for snapshot in snapshots:
        validate_input(snapshot)
    reviews, excluded = load_reviews(archive)
    baseline = historical_baseline(archive, reviews)
    output.mkdir(parents=True)
    root = Path(__file__).resolve().parents[1]
    paths = [*root.glob("news/*.py"), *root.glob("news/tasks/*"), Path(__file__)]
    write(
        output / "manifest.json",
        {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "model": codex.MODEL,
            "reasoning_effort": codex.REASONING_EFFORT,
            "source_files": {
                str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(paths)
            },
            "prepared_files": {
                batch["file"]: hashlib.sha256((prepared / batch["file"]).read_bytes()).hexdigest()
                for batch in manifest["batches"]
            },
        },
    )
    report = {
        "completed": False,
        "input_manifest": manifest,
        "baseline": baseline,
        "excluded_cases": excluded,
        "replays": [],
        "limits": {"max_calls": max_calls, "timeout_per_call": timeout, "repeats": repeats},
        "comparison": "source replay against original saved assignments and pre-existing reviewed labels",
    }
    write(output / "report.json", report)
    for repeat in range(1, repeats + 1):
        state = output / f"replay-{repeat}"
        assignments, batches = {}, []
        begun = time.monotonic()
        for batch, snapshot in zip(manifest["batches"], snapshots, strict=True):
            try:
                result, reused = run(snapshot, state, timeout=timeout)
            except (ValueError, OSError, RuntimeError) as exc:
                report["replays"].append(
                    {
                        "repeat": repeat,
                        "completed": False,
                        "error": str(exc),
                        "batches": batches,
                        "scored_cases": compare(assignments, reviews),
                    }
                )
                write(output / "report.json", report)
                raise
            assert not reused
            for event in result["events"]:
                for article_id in event["article_ids"]:
                    assignments[(snapshot["day"], article_id)] = event["id"]
            batches.append(
                {
                    "file": batch["file"],
                    "run_id": result["run_id"],
                    "day": snapshot["day"],
                    "articles": len(snapshot["articles"]),
                    "events": len(result["events"]),
                }
            )
            print(
                f"Replay {repeat}/{repeats}: {batch['file']} accepted, {len(result['events'])} events",
                flush=True,
            )
        scores = compare(assignments, reviews)
        report["replays"].append(
            {
                "repeat": repeat,
                "completed": True,
                "batches": batches,
                "duration_seconds": round(time.monotonic() - begun, 3),
                "scored_cases": scores,
                "assigned_articles": len(assignments),
            }
        )
        write(
            output / f"assignments-{repeat}.json",
            [
                {"day": day, "article_id": article_id, "event_id": event_id}
                for (day, article_id), event_id in sorted(assignments.items())
            ],
        )
        write(output / "report.json", report)
        print(
            f"Replay {repeat}: {sum(row['correct'] for row in scores)}/{len(scores)} reviewed relations correct",
            flush=True,
        )
    report["completed"] = True
    write(output / "report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--max-calls", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()
    if not args.prepared.exists():
        print(json.dumps(prepare(args.archive, args.prepared), indent=2))
    if args.output:
        report = evaluate(
            args.archive,
            args.prepared,
            args.output,
            repeats=args.repeats,
            max_calls=args.max_calls,
            timeout=args.timeout,
        )
        print(json.dumps({"baseline": report["baseline"], "replays": report["replays"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
