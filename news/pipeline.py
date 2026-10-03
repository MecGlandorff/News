"""One explicit pipeline and a small transactional SQLite journal."""

import contextlib
import fcntl
import json
import sqlite3
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from news.codex import run_task
from news.domain import (
    TASKS,
    canonical,
    digest,
    render,
    validate_extraction,
    validate_input,
    validate_result,
)

APP_ID = 0x4E455753
MEMORY_DAYS = 14
MEMORY_EVENTS = 30


def analyze(
    payload: dict,
    strategy: str,
    artifact_dir: Path,
    *,
    timeout: float = 180,
    executable: str = "codex",
) -> dict:
    options = {"timeout": timeout, "executable": executable}
    if strategy == "single":
        result = run_task("single", payload, artifact_dir / "single", **options)
    elif strategy == "staged":
        extracted = run_task("extract", payload, artifact_dir / "extract", **options)
        reduced = validate_extraction(payload, extracted)
        result = run_task("group", reduced, artifact_dir / "group", **options)
    else:
        raise ValueError(f"unknown strategy: {strategy}")
    validate_result(payload, result)
    return result


def connect(path: Path) -> sqlite3.Connection:
    """Refuse unrelated/legacy databases; never migrate them implicitly."""
    db = sqlite3.connect(path, timeout=5)
    try:
        identity = db.execute("PRAGMA application_id").fetchone()[0]
        tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if identity != APP_ID and (identity or tables):
            raise ValueError("not a News rebuild database; choose a fresh state directory")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version not in {0, 1}:
            raise ValueError("unsupported News database version")
        db.execute(f"PRAGMA application_id = {APP_ID}")
        db.execute("PRAGMA user_version = 1")
        db.execute("""CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
            day TEXT NOT NULL, created_at TEXT NOT NULL,
            input_json TEXT NOT NULL, result_json TEXT NOT NULL
        )""")
        db.commit()
        return db
    except BaseException:
        db.close()
        raise


def memory(db: sqlite3.Connection, day: str) -> list[dict]:
    since = (date.fromisoformat(day) - timedelta(days=MEMORY_DAYS)).isoformat()
    events = {}
    for (raw,) in db.execute(
        "SELECT result_json FROM runs WHERE day >= ? AND day <= ? ORDER BY rowid",
        (since, day),
    ):
        for event in json.loads(raw)["events"]:
            events[event["id"]] = {
                "id": event["id"],
                "title": event["title"],
                "first_seen": event["first_seen"],
                "last_seen": event["last_seen"],
                "evidence": event["evidence"],
            }
    ordered = sorted(events.values(), key=lambda event: (event["last_seen"], event["id"]))
    return ordered[-MEMORY_EVENTS:]


@contextlib.contextmanager
def state_lock(state: Path):
    state.mkdir(parents=True, exist_ok=True)
    with (state / "run.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("another run is using this state directory") from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _fingerprint(snapshot: dict, strategy: str) -> str:
    task_names = ["single"] if strategy == "single" else ["extract", "group"]
    files = {
        path.name: path.read_text()
        for name in task_names
        for path in (TASKS / f"{name}.md", TASKS / f"{name}.schema.json")
    }
    return digest(
        {
            "snapshot": snapshot,
            "strategy": strategy,
            "tasks": files,
            "model": "gpt-6-astra",
            "reasoning": "medium",
            "policy": 1,
        }
    )


def _materialize(payload: dict, decision: dict, run_id: str, strategy: str) -> dict:
    articles = {article["id"]: article for article in payload["articles"]}
    previous = {event["id"]: event for event in payload["memory"]}
    result = {"run_id": run_id, "day": payload["day"], "strategy": strategy, "events": []}
    for event in decision["events"]:
        prior = previous.get(event["previous_event_id"])
        event_id = (
            prior["id"]
            if prior
            else "e-" + digest({"run": run_id, "articles": sorted(event["article_ids"])})[:20]
        )
        evidence = [
            dict(
                item,
                source=articles[item["article_id"]]["source"],
                url=articles[item["article_id"]]["url"],
                published_at=articles[item["article_id"]]["published_at"],
            )
            for item in event["evidence"]
        ]
        old_quotes = {item["quote"] for item in prior["evidence"]} if prior else set()
        result["events"].append(
            dict(
                event,
                id=event_id,
                first_seen=prior["first_seen"] if prior else payload["day"],
                last_seen=payload["day"],
                evidence=evidence,
                new_quote_count=sum(item["quote"] not in old_quotes for item in evidence),
            )
        )
    return result


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(
    snapshot: dict,
    state: Path,
    *,
    strategy: str = "single",
    timeout: float = 180,
    executable: str = "codex",
) -> tuple[dict, bool]:
    snapshot = validate_input(snapshot)
    if strategy not in {"single", "staged"}:
        raise ValueError("strategy must be single or staged")
    if not 1 <= timeout <= 1800:
        raise ValueError("timeout must be between 1 and 1800 seconds per call")
    fingerprint = _fingerprint(snapshot, strategy)
    with state_lock(state), contextlib.closing(connect(state / "memory.sqlite3")) as db:
        saved = db.execute(
            "SELECT result_json FROM runs WHERE fingerprint = ?", (fingerprint,)
        ).fetchone()
        if saved:
            result = json.loads(saved[0])
            directory = state / "runs" / result["run_id"]
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "briefing.md").write_text(render(result), encoding="utf-8")
            return result, True
        latest = db.execute("SELECT MAX(day) FROM runs").fetchone()[0]
        if latest and snapshot["day"] < latest:
            raise ValueError("new runs must be chronological; use a separate state for backtests")
        payload = dict(snapshot, memory=memory(db, snapshot["day"]))
        run_id = uuid.uuid4().hex
        directory = state / "runs" / run_id
        directory.mkdir(parents=True)
        _write_json(directory / "input.json", payload)
        try:
            decision = analyze(payload, strategy, directory, timeout=timeout, executable=executable)
            result = _materialize(payload, decision, run_id, strategy)
            _write_json(directory / "result.json", result)
            (directory / "briefing.md").write_text(render(result), encoding="utf-8")
            with db:
                db.execute(
                    "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        fingerprint,
                        snapshot["day"],
                        datetime.now(timezone.utc).isoformat(),
                        canonical(payload),
                        canonical(result),
                    ),
                )
        except BaseException as exc:
            _write_json(directory / "failure.json", {"error": str(exc), "type": type(exc).__name__})
            raise
        return result, False


def replay(state: Path, run_id: str) -> str:
    """Render persisted accepted decisions without feeds or Codex."""
    path = state / "memory.sqlite3"
    if not path.is_file():
        raise ValueError("no News state exists here")
    with contextlib.closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA application_id").fetchone()[0] != APP_ID:
            raise ValueError("not a News rebuild database")
        row = db.execute("SELECT result_json FROM runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            raise ValueError("unknown run ID")
        return render(json.loads(row[0]))
