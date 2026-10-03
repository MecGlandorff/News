"""Small commands with explicit files and no background services."""

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from urllib.error import URLError
from xml.etree.ElementTree import ParseError

from news import feeds, pipeline
from news.domain import TIMEZONE


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Local source-grounded news memory via Codex exec")
    commands = root.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("fetch", help="capture RSS/Atom articles without AI calls")
    capture.add_argument("--feeds", type=Path, default=Path("feeds.json"))
    capture.add_argument("--day", default=datetime.now(TIMEZONE).date().isoformat())
    capture.add_argument("--max-per-feed", type=int, default=10)
    capture.add_argument("--output", type=Path, required=True)
    run = commands.add_parser("run", help="build event memory and a Markdown briefing")
    run.add_argument("--input", type=Path, required=True)
    run.add_argument("--state", type=Path, default=Path(".news"))
    run.add_argument("--strategy", choices=["single", "staged"], default="single")
    run.add_argument("--timeout", type=float, default=180, help="seconds per Codex call")
    replay = commands.add_parser("replay", help="render a saved run without model or network calls")
    replay.add_argument("run_id")
    replay.add_argument("--state", type=Path, default=Path(".news"))
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
            result, reused = pipeline.run(
                json.loads(args.input.read_text()),
                args.state,
                strategy=args.strategy,
                timeout=args.timeout,
            )
            print(
                json.dumps(
                    {
                        "run_id": result["run_id"],
                        "reused": reused,
                        "events": len(result["events"]),
                        "briefing": str(args.state / "runs" / result["run_id"] / "briefing.md"),
                    },
                    indent=2,
                )
            )
        else:
            print(pipeline.replay(args.state, args.run_id), end="")
        return 0
    except (ValueError, OSError, RuntimeError, sqlite3.Error, URLError, ParseError) as exc:
        print(f"news: {exc}", file=sys.stderr)
        for note in getattr(exc, "__notes__", ()):
            print(note, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("news: interrupted; accepted event memory was not partially written", file=sys.stderr)
        return 130
