"""A durable FIFO of captured sources around the existing story workflow."""

import contextlib
import hashlib
import json
import math
import sqlite3
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from news import codex, feeds, trajectory
from news.domain import MAX_INPUT_CHARS, TIMEZONE, canonical, digest, validate_input

ARTICLE_FIELDS = ("id", "source", "url", "title", "text", "published_at")


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    text = (
        value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    )
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _versions(articles):
    versions = {}
    for article in articles:
        versions.setdefault((article["source"], article["url"]), set()).add(digest(article))
    return versions


def _batches(articles, day, size):
    batch = []
    for article in articles:
        candidate = {"day": day, "articles": batch + [article]}
        duplicate = any(
            item["id"] == article["id"] or item["url"] == article["url"] for item in batch
        )
        if batch and (
            len(batch) >= size or duplicate or len(canonical(candidate)) > MAX_INPUT_CHARS
        ):
            yield validate_input({"day": day, "articles": batch})
            batch = []
        batch.append(article)
    if batch:
        yield validate_input({"day": day, "articles": batch})


def _capture(config, state, manifests, started, size):
    day = started.astimezone(TIMEZONE).date().isoformat()
    if manifests and day < manifests[-1]["day"]:
        raise ValueError("capture clock precedes the frozen archive; check the system date")
    capture_id = (
        f"{len(manifests) + 1:08d}-" + started.strftime("%Y%m%dT%H%M%S%fZ-") + uuid.uuid4().hex[:8]
    )
    directory = state / "captures" / capture_id
    (directory / "feeds").mkdir(parents=True)
    articles, coverage = feeds.collect(config, day, directory / "feeds")
    previous = {}
    for manifest in manifests:
        previous.update(_versions(manifest["articles"]))
    new = [
        article
        for article in articles
        if digest(article) not in previous.get((article["source"], article["url"]), set())
    ]
    manifest = {
        "version": 1,
        "id": capture_id,
        "captured_at": started.isoformat(),
        "day": day,
        "articles": articles,
        "new_versions": len(new),
        "coverage": coverage,
        "capture_protocol": _protocol(),
        "batch_size": size,
        "processing_ids": {
            digest(article): digest([capture_id, digest(article)])[:24] for article in new
        },
        "batches": [],
    }
    processing = [dict(article, id=manifest["processing_ids"][digest(article)]) for article in new]
    for index, snapshot in enumerate(_batches(processing, day, size)):
        filename = f"batches/{index:04d}.json"
        _write(directory / filename, snapshot)
        manifest["batches"].append({"file": filename, "digest": digest(snapshot)})
    # Publish the manifest last. An interrupted capture remains visibly incomplete.
    _write(directory / "manifest.json", manifest)
    return manifest


def _accepted(memory):
    path = memory / "journal.sqlite3"
    if not path.exists():
        return {}
    with contextlib.closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA application_id").fetchone()[0] != trajectory.APP_ID:
            raise ValueError("not a story trajectory database")
        accepted = {}
        for raw_input, raw_result in db.execute(
            "SELECT input_json, result_json FROM runs ORDER BY rowid"
        ):
            payload = json.loads(raw_input)
            snapshot = validate_input(
                {
                    "day": payload["day"],
                    "articles": [
                        {field: article[field] for field in ARTICLE_FIELDS}
                        for article in payload["articles"]
                    ],
                }
            )
            accepted[digest(snapshot)] = json.loads(raw_result)
        return accepted


def _queue(state, manifests):
    queue = []
    for manifest in manifests:
        for batch in manifest["batches"]:
            path = state / "captures" / manifest["id"] / batch["file"]
            snapshot = validate_input(_read(path))
            if digest(snapshot) != batch["digest"] or snapshot["day"] != manifest["day"]:
                raise ValueError(f"frozen batch changed: {path}")
            queue.append(dict(batch, capture_id=manifest["id"], path=path, snapshot=snapshot))
    return queue


def _protocol():
    directory = Path(__file__).parent
    paths = sorted(directory.glob("*.py")) + sorted((directory / "tasks").glob("*"))
    return {
        "model": codex.MODEL,
        "reasoning_effort": codex.REASONING_EFFORT,
        "max_context_chars": trajectory.DEFAULT_CONTEXT_CHARS,
        "hits_per_article": 3,
        "file_sha256": {
            str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths
            if path.is_file()
        },
    }


def _call_diagnostics(directory, task, state):
    call = {
        "task": task,
        "artifact": str(directory.relative_to(state)),
        "process_started": None,
        "usage": None,
        "duration_seconds": None,
    }
    try:
        metadata = _read(directory / "metadata.json")
        if not isinstance(metadata, dict):
            raise ValueError("model metadata is not an object")
    except (OSError, ValueError, TypeError) as exc:
        call["diagnostic_error"] = str(exc)
        return call
    errors = []
    if type(metadata.get("process_started")) is bool:
        call["process_started"] = metadata["process_started"]
    else:
        errors.append("model metadata has no reliable process_started flag")
    usage = metadata.get("usage")
    if usage is not None and (
        not isinstance(usage, dict)
        or any(type(value) is not int or value < 0 for value in usage.values())
    ):
        errors.append("model metadata has invalid usage")
    else:
        call["usage"] = usage
    seconds = metadata.get("duration_seconds")
    if seconds is not None and (
        type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0
    ):
        errors.append("model metadata has invalid duration")
    else:
        call["duration_seconds"] = seconds
    if errors:
        call["diagnostic_error"] = "; ".join(errors)
    return call


def _attempt(batch, state, timeout):
    memory = state / "memory"
    before = set((memory / "runs").glob("*"))
    started = time.monotonic()
    attempt = {
        "capture_id": batch["capture_id"],
        "batch": str(batch["path"].relative_to(state)),
        "status": "failed",
        "error": None,
        "artifact": None,
        "calls": [],
        "model_invocations": 0,
        "unknown_usage_invocations": 0,
        "unknown_launch_attempts": 0,
        "usage": None,
    }
    result = None
    try:
        result, reused = trajectory.run(batch["snapshot"], memory, timeout=timeout)
        attempt.update(status="reused" if reused else "accepted", run_id=result["run_id"])
    except (Exception, KeyboardInterrupt) as exc:
        attempt.update(error=str(exc) or type(exc).__name__, error_type=type(exc).__name__)
    finally:
        try:
            created = sorted(set((memory / "runs").glob("*")) - before)
            directory = (
                memory / "runs" / result["run_id"]
                if result
                else created[0]
                if len(created) == 1
                else None
            )
            if len(created) > 1:
                raise ValueError("multiple run artifacts appeared; inspect concurrent writers")
            if directory is not None:
                attempt["artifact"] = str(directory.relative_to(state))
                # A reused result has no new launch or usage to charge to this invocation.
                if attempt["status"] != "reused":
                    for name, task in (("model", "trajectory"), ("review", "coherence")):
                        if (directory / name).exists() or result:
                            attempt["calls"].append(
                                _call_diagnostics(directory / name, task, state)
                            )
        except (OSError, ValueError, TypeError) as exc:
            attempt["diagnostic_error"] = str(exc)
            attempt["unknown_launch_attempts"] += 1
        for call in attempt["calls"]:
            attempt["model_invocations"] += int(call["process_started"] is True)
            attempt["unknown_launch_attempts"] += int(call["process_started"] is None)
            attempt["unknown_usage_invocations"] += int(
                call["process_started"] is True and call["usage"] is None
            )
            if call["usage"] is not None:
                attempt["usage"] = attempt["usage"] or {}
                for key, value in call["usage"].items():
                    attempt["usage"][key] = attempt["usage"].get(key, 0) + value
        seconds = [
            call["duration_seconds"]
            for call in attempt["calls"]
            if call["duration_seconds"] is not None
        ]
        if seconds:
            attempt["model_seconds"] = sum(seconds)
        errors = [attempt["diagnostic_error"]] if attempt.get("diagnostic_error") else []
        errors.extend(
            f"{call['task']}: {call['diagnostic_error']}"
            for call in attempt["calls"]
            if call.get("diagnostic_error")
        )
        if errors:
            attempt["diagnostic_error"] = "; ".join(errors)
        if attempt["unknown_launch_attempts"]:
            attempt["invocation_status_uncertain"] = True
        attempt["duration_seconds"] = round(time.monotonic() - started, 6)
    return result, attempt


def _briefing(report, results):
    lines = [
        f"# Dogfood briefing — run on {report['day']}",
        "",
        f"**Run status: {report['status']}**",
        "",
    ]
    lines.extend(f"- {warning}" for warning in report["warnings"])
    if report["error"]:
        lines.extend(["", f"Processing error: {report['error']}"])
    if not results:
        lines.extend(
            ["", "No new accepted observations in this run; this does not mean no news occurred."]
        )
    for result in results:
        body = trajectory.render_daily(result).replace(
            "](stories/", f"](../../memory/runs/{result['run_id']}/stories/"
        )
        lines.extend(["", f"Accepted run `{result['run_id']}`", ""])
        lines.extend("#" + line if line.startswith("#") else line for line in body.splitlines())
    lines.extend(
        [
            "",
            "## Run receipt",
            "",
            "[Full report](report.json) · [Feedback](../../feedback.md)",
            "",
        ]
    )
    lines.append(
        f"{report['accepted_batches']} accepted batches; {report['recovered_batches']} recovered from the journal; "
        f"{report['pending_batches'] if report['pending_batches'] is not None else 'Unknown'} pending. "
        f"{report['model_invocations']} confirmed model invocations; "
        f"{report['unknown_usage_invocations']} with unknown usage; "
        f"{report['unknown_launch_attempts']} call attempts with unknown launch status."
    )
    return "\n".join(lines).rstrip() + "\n"


def run(
    config: list | None,
    state: Path,
    *,
    batch_size: int = 8,
    max_batches: int = 12,
    timeout: float = 360,
    collect_only: bool = False,
    resume_only: bool = False,
) -> dict:
    """Capture once, drain oldest pending batches, and retain a receipt even on failure."""
    if type(batch_size) is not int or not 1 <= batch_size <= 50:
        raise ValueError("batch_size must be between 1 and 50")
    if type(max_batches) is not int or not 1 <= max_batches <= 100:
        raise ValueError("max_batches must be between 1 and 100")
    if not 1 <= timeout <= 1800:
        raise ValueError("timeout must be between 1 and 1800 seconds")
    if collect_only and resume_only:
        raise ValueError("collect_only and resume_only are mutually exclusive")
    started_at, clock = datetime.now(UTC), time.monotonic()
    state = Path(state).resolve()
    report_id = started_at.strftime("%Y%m%dT%H%M%S%fZ-") + uuid.uuid4().hex[:8]
    report = {
        "version": 1,
        "id": report_id,
        "started_at": started_at.isoformat(),
        "day": started_at.astimezone(TIMEZONE).date().isoformat(),
        "status": "failed",
        "error": None,
        "warnings": [],
        "protocol": _protocol(),
        "limits": {
            "batch_size": batch_size,
            "max_batches": max_batches,
            "timeout_seconds": timeout,
        },
        "mode": "collect" if collect_only else "resume" if resume_only else "daily",
        "capture_id": None,
        "captured_versions": None,
        "new_versions": None,
        "coverage": [],
        "attempts": [],
        "accepted_run_ids": [],
        "accepted_batches": 0,
        "recovered_batches": 0,
        "pending_batches": None,
        "model_invocations": 0,
        "unknown_usage_invocations": 0,
        "unknown_launch_attempts": 0,
        "known_usage": {},
    }
    with trajectory.state_lock(state):
        report_dir = state / "reports" / report_id
        report_dir.mkdir(parents=True)
        _write(report_dir / "started.json", dict(report, status="started"))
        manifests, queue, accepted, results = [], [], {}, []
        try:
            manifests = [
                _read(path) for path in sorted((state / "captures").glob("*/manifest.json"))
            ]
            accepted = _accepted(state / "memory")
            queue = _queue(state, manifests)
            if accepted.keys() - {batch["digest"] for batch in queue}:
                raise ValueError(
                    "managed memory contains unqueued inputs; use separate state for manual runs"
                )
            previously_reported = {
                run_id
                for path in (state / "reports").glob("*/report.json")
                for run_id in _read(path)["accepted_run_ids"]
            }
            results = [
                result
                for result in accepted.values()
                if result["run_id"] not in previously_reported
            ]
            report["recovered_batches"] = len(results)
            if not resume_only:
                manifest = _capture(config, state, manifests, started_at, batch_size)
                manifests.append(manifest)
                report["capture_id"] = manifest["id"]
                report["captured_versions"] = len(manifest["articles"])
                report["new_versions"] = manifest["new_versions"]
                queue = _queue(state, manifests)
            pending = [batch for batch in queue if batch["digest"] not in accepted]
            if not collect_only:
                for batch in pending[:max_batches]:
                    # Identical frozen snapshots can already have been accepted in this invocation.
                    if batch["digest"] in accepted:
                        continue
                    attempt_id = f"{len(report['attempts']) + 1:04d}"
                    _write(
                        report_dir / "attempts" / f"{attempt_id}.started.json",
                        {
                            "batch": str(batch["path"].relative_to(state)),
                            "digest": batch["digest"],
                            "started_at": datetime.now(UTC).isoformat(),
                            "timeout_seconds": timeout,
                        },
                    )
                    result, attempt = _attempt(batch, state, timeout)
                    report["attempts"].append(attempt)
                    if result is not None:
                        accepted[batch["digest"]] = result
                        results.append(result)
                        report["accepted_batches"] += int(attempt["status"] == "accepted")
                    _write(report_dir / "attempts" / f"{attempt_id}.json", attempt)
                    if result is None:
                        report["error"] = attempt["error"]
                        break
            report["pending_batches"] = sum(batch["digest"] not in accepted for batch in queue)
            involved = {attempt["capture_id"] for attempt in report["attempts"]} | {
                report["capture_id"]
            }
            displayed = {result["run_id"] for result in results}
            involved.update(
                batch["capture_id"]
                for batch in queue
                if accepted.get(batch["digest"], {}).get("run_id") in displayed
            )
            report["coverage"] = [
                {"capture_id": manifest["id"], **manifest["coverage"]}
                for manifest in manifests
                if manifest["id"] in involved
            ]
            for coverage in report["coverage"]:
                if coverage["feed_errors"] or coverage["invalid"]:
                    report["warnings"].append(
                        f"Capture {coverage['capture_id']}: {coverage['feed_errors']} failed feeds; "
                        f"{coverage['invalid']} invalid items. Coverage is incomplete."
                    )
            if report["pending_batches"]:
                report["warnings"].append(
                    f"{report['pending_batches']} frozen batches remain pending; resume before treating coverage as complete."
                )
            report["status"] = (
                "failed" if report["error"] else "partial" if report["warnings"] else "complete"
            )
        except (Exception, KeyboardInterrupt) as exc:
            report.update(
                error=str(exc) or type(exc).__name__, error_type=type(exc).__name__, status="failed"
            )
        finally:
            unfinished = [
                path
                for path in sorted((state / "reports").iterdir())
                if path.is_dir() and path != report_dir and not (path / "report.json").exists()
            ]
            report["incomplete_reports"] = [str(path.relative_to(state)) for path in unfinished]
            report["unfinished_prior_attempts"] = [
                str(path.relative_to(state))
                for directory in unfinished
                for path in directory.glob("attempts/*.started.json")
                if not path.with_name(path.name.replace(".started.json", ".json")).exists()
            ]
            if unfinished:
                report["warnings"].append(
                    f"{len(unfinished)} prior invocations have no final receipt; their launch status, failures and usage need review: {', '.join(report['incomplete_reports'])}"
                )
            incomplete = [
                str(path.relative_to(state))
                for path in sorted((state / "captures").glob("*"))
                if path.is_dir() and not (path / "manifest.json").exists()
            ]
            report["incomplete_captures"] = incomplete
            if incomplete:
                report["warnings"].append(
                    f"{len(incomplete)} interrupted captures need review; raw files are preserved but unqueued: {', '.join(incomplete)}"
                )
            for attempt in report["attempts"]:
                report["model_invocations"] += attempt["model_invocations"]
                report["unknown_launch_attempts"] += attempt["unknown_launch_attempts"]
                report["unknown_usage_invocations"] += attempt["unknown_usage_invocations"]
                for key, value in (attempt["usage"] or {}).items():
                    report["known_usage"][key] = report["known_usage"].get(key, 0) + value
                if attempt.get("diagnostic_error"):
                    report["warnings"].append(
                        f"Run diagnostics unavailable for {attempt['artifact']}: {attempt['diagnostic_error']}"
                    )
            if report["warnings"] and report["status"] == "complete":
                report["status"] = "partial"
            report["accepted_run_ids"] = [result["run_id"] for result in results]
            report["duration_seconds"] = round(time.monotonic() - clock, 6)
            _write(report_dir / "briefing.md", _briefing(report, results))
            _write(report_dir / "report.json", report)
            if not (state / "feedback.md").exists():
                _write(
                    state / "feedback.md",
                    "# Reader feedback\n\nAdd dated entries with briefing/run ID, source URLs, severity and what went wrong.\nCategories: missed development, incorrect merge, missed connection, unsupported claim, repetition.\nKeep unanswered questions and positive examples too. This file is never overwritten.\n",
                )
            _write(
                state / "latest.md",
                f"# Latest dogfood run\n\n[{report['day']} — {report['status']}](reports/{report_id}/briefing.md)\n",
            )
            lines = [
                "# News dogfood archive",
                "",
                "[Latest run](latest.md) · [Reader feedback](feedback.md)",
                "",
            ]
            for path in sorted((state / "reports").glob("*/report.json"), reverse=True):
                receipt = _read(path)
                lines.append(
                    f"- [{receipt['started_at']} — {receipt['status']}](reports/{path.parent.name}/briefing.md)"
                )
            lines.extend(["", "## Frozen batches", ""])
            for batch in queue:
                result = accepted.get(batch["digest"])
                target = (
                    f"memory/runs/{result['run_id']}/briefing.md"
                    if result
                    else str(batch["path"].relative_to(state))
                )
                label = "accepted" if result else "pending"
                lines.append(f"- [{batch['capture_id']}/{batch['file']} — {label}]({target})")
            _write(state / "index.md", "\n".join(lines) + "\n")
    return dict(
        report, briefing=str(report_dir / "briefing.md"), report=str(report_dir / "report.json")
    )
