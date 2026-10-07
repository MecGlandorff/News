"""Small commands with explicit files and no background services."""

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from urllib.error import URLError
from xml.etree.ElementTree import ParseError

from news import daily, feeds, trajectory
from news.domain import TIMEZONE


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Local source-grounded news memory via Codex exec")
    commands = root.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("fetch", help="capture RSS/Atom articles without AI calls")
    capture.add_argument("--feeds", type=Path, default=Path("feeds.json"))
    capture.add_argument("--day", default=datetime.now(TIMEZONE).date().isoformat())
    capture.add_argument("--max-per-feed", type=int, default=10)
    capture.add_argument("--output", type=Path, required=True)
    run = commands.add_parser("run", help="update sourced stories and write a Markdown briefing")
    run.add_argument("--input", type=Path, required=True)
    run.add_argument("--state", type=Path, default=Path(".news"))
    run.add_argument("--timeout", type=float, default=180, help="seconds per Codex call")
    run.add_argument("--max-context-chars", type=int, default=trajectory.DEFAULT_CONTEXT_CHARS)
    run.add_argument("--hits-per-article", type=int, default=3)
    scheduled = commands.add_parser("daily", help="capture feeds and process a durable daily queue")
    scheduled.add_argument("--feeds", type=Path, default=Path("feeds.json"))
    scheduled.add_argument("--state", type=Path, default=Path(".news/dogfood"))
    scheduled.add_argument("--batch-size", type=int, default=8)
    scheduled.add_argument("--max-batches", type=int, default=12)
    scheduled.add_argument("--timeout", type=float, default=360)
    mode = scheduled.add_mutually_exclusive_group()
    mode.add_argument("--collect-only", action="store_true")
    mode.add_argument("--resume-only", action="store_true")
    story = commands.add_parser("story", help="render a complete accepted story without AI calls")
    story.add_argument("story_id")
    story.add_argument("--state", type=Path, default=Path(".news"))
    story.add_argument("--as-of", help="include observations through this capture day (YYYY-MM-DD)")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "fetch":
            if args.output.exists():
                raise ValueError("output already exists; choose a new snapshot filename")
            snapshot, report = feeds.fetch(
                json.loads(args.feeds.read_text()),
                args.day,
                max_per_feed=args.max_per_feed,
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as file:
                json.dump(snapshot, file, indent=2, ensure_ascii=False)
                file.write("\n")
            print(json.dumps(report, indent=2), file=sys.stderr)
            print(args.output)
        elif args.command == "run":
            result, reused = trajectory.run(
                json.loads(args.input.read_text()),
                args.state,
                timeout=args.timeout,
                max_context_chars=args.max_context_chars,
                hits_per_article=args.hits_per_article,
            )
            print(
                json.dumps(
                    {
                        "run_id": result["run_id"],
                        "reused": reused,
                        "stories": [item["id"] for item in result["stories"]],
                        "briefing": str(args.state / "runs" / result["run_id"] / "briefing.md"),
                    },
                    indent=2,
                )
            )
        elif args.command == "daily":
            report = daily.run(
                None if args.resume_only else json.loads(args.feeds.read_text()),
                args.state,
                batch_size=args.batch_size,
                max_batches=args.max_batches,
                timeout=args.timeout,
                collect_only=args.collect_only,
                resume_only=args.resume_only,
            )
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 0 if report["status"] == "complete" else 1
        else:
            print(trajectory.story(args.state, args.story_id, as_of=args.as_of), end="")
        return 0
    except (ValueError, OSError, RuntimeError, sqlite3.Error, URLError, ParseError) as exc:
        print(f"news: {exc}", file=sys.stderr)
        for note in getattr(exc, "__notes__", ()):
            print(note, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(
            "news: interrupted; accepted story journal was not partially written", file=sys.stderr
        )
        return 130
