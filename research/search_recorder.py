#!/usr/bin/env python3
"""Write-once receipts for a controller-owned explicit search/fetch transport.

This module makes no network/model calls. It caps reservations, not a provider's
hidden work, timeout, or financial limits. Models supply query/URL plans only; a
trusted controller must reserve each operation before invoking its tool once.
"""
import argparse
import copy
from contextlib import contextmanager
import fcntl
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from urllib.parse import urlsplit


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def require(ok, message):
    if not ok:
        raise ValueError(message)


def utc(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(parsed.utcoffset() == timezone.utc.utcoffset(parsed), "Expected UTC timestamp")
    return parsed


def http_url(value):
    require(isinstance(value, str), "Expected URL")
    parsed = urlsplit(value)
    require(parsed.scheme in {"https", "http"} and parsed.hostname and
            not parsed.username and not parsed.password, "Expected absolute HTTP(S) URL")


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


class BudgetExhausted(RuntimeError):
    """No tool was dispatched; this is not a failed tool attempt."""


class Recorder:
    """Two-phase receipts for an external controller; never dispatches tools itself.

    Create once with a plan, then reopen by directory. `begin` reserves one attempt
    before the controller invokes one tool. `complete` retains the exact returned
    JSON. An unfinished start blocks new attempts. Reopening never resets counts.
    This enforces controller reservations, not calls made outside this interface
    or hidden provider retries. The root controller remains part of the trust base.
    """

    def __init__(self, directory, plan=None, *, clock=utc_now):
        self.directory, self.clock = Path(directory), clock
        if plan is not None:
            self._validate_plan(plan)
            self.directory.mkdir(parents=True, exist_ok=False)
            self._write("plan.json", plan)
        self.plan = json.loads((self.directory / "plan.json").read_text())
        self._validate_plan(self.plan)

    @staticmethod
    def _validate_plan(plan):
        required = {"collection_id", "story_id", "cutoff", "scope", "provider", "mode",
                    "transport_id", "max_searches", "max_fetches"}
        require(isinstance(plan, dict) and set(plan) == required, "Invalid recorder plan")
        require(all(isinstance(plan[k], str) and plan[k] for k in required -
                    {"max_searches", "max_fetches"}), "Missing recorder identity/scope")
        utc(plan["cutoff"])
        require(all(type(plan[k]) is int and plan[k] >= 0 for k in
                    ("max_searches", "max_fetches")), "Invalid attempt caps")

    @contextmanager
    def _guard(self):
        with (self.directory / ".lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _write(self, name, value):
        data = canonical(value)
        with (self.directory / name).open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        (self.directory / name).chmod(0o444)
        return {"path": name, "sha256": hashlib.sha256(data).hexdigest()}

    def _state(self):
        starts = [json.loads(p.read_text()) for p in sorted(self.directory.glob("attempt-*-started.json"))]
        completed = [json.loads(p.read_text()) for p in sorted(self.directory.glob("attempt-*-completed.json"))]
        require(all(s["plan_sha256"] == digest(self.plan) for s in starts), "Plan changed")
        by_id = {s["event_id"]: s for s in starts}
        require(len(by_id) == len(starts), "Duplicate attempt")
        for terminal in completed:
            start = by_id.get(terminal["event"]["event_id"])
            require(start is not None and terminal["started_sha256"] == digest(start),
                    "Started receipt changed")
            snapshot = terminal["event"]["response"].get("snapshot")
            if snapshot:
                expected = f"attempt-{start['number']:04}-raw.json"
                require(snapshot["path"] == expected and
                        hashlib.sha256((self.directory / expected).read_bytes()).hexdigest() ==
                        snapshot["sha256"], "Raw snapshot changed")
        return starts, completed

    def begin(self, kind, request):
        """Reserve and persist one attempt; the caller dispatches only after success."""
        with self._guard():
            require(kind in {"search", "fetch"}, "Invalid operation")
            require(isinstance(request, dict) and set(request) ==
                    ({"query", "reason"} if kind == "search" else {"url", "reason"}),
                    "Invalid request fields")
            require(all(isinstance(x, str) and x.strip() for x in request.values()),
                    "Empty query/URL/reason")
            if kind == "fetch":
                http_url(request["url"])
            request = json.loads(canonical(request))
            starts, completed = self._state()
            completed_ids = {c["event"]["event_id"] for c in completed}
            cap = self.plan["max_searches" if kind == "search" else "max_fetches"]
            reason = None
            if any(s["event_id"] not in completed_ids for s in starts):
                reason = "unfinished_attempt"
            elif any(c["stop_collection"] for c in completed):
                reason = "collection_stopped"
            elif sum(s["kind"] == kind for s in starts) >= cap:
                reason = "budget_exhausted"
            if reason:
                self._write(f"refusal-{len(list(self.directory.glob('refusal-*.json'))) + 1:04}.json",
                            {"kind": kind, "request": request, "at": self.clock(), "reason": reason})
                raise BudgetExhausted("No dispatch: " + reason)
            number = len(starts) + 1
            started_at = self.clock()
            utc(started_at)
            start = {"event_id": f"{self.plan['collection_id']}-attempt-{number:04}",
                     "number": number, "kind": kind, "started_at": started_at,
                     "request": request, "plan_sha256": digest(self.plan)}
            self._write(f"attempt-{number:04}-started.json", start)
            return copy.deepcopy(start)

    def complete(self, event_id, payload, *, status="ok", source=None, error=None,
                 cost=None, model_tokens=None):
        """Retain a tool return or explicit exception once; capture time is now.

        `payload` is the COMPLETE tool return, without summarizing or text cleanup.
        Source metadata: {fields, completeness, redirects, published_at_utc}.
        Raw payload is snapshotted before normalized result validation. Source text
        must occur unchanged in a returned string, and may be a labeled excerpt.
        A failed/blocked/empty tool attempt consumes its reserved budget.
        """
        with self._guard():
            starts, completed = self._state()
            matches = [s for s in starts if s["event_id"] == event_id]
            require(len(matches) == 1, "Unknown attempt")
            require(event_id not in {c["event"]["event_id"] for c in completed}, "Attempt already completed")
            start = matches[0]
            number, kind = start["number"], start["kind"]
            observed_at = self.clock()
            response, observation, stop = {}, None, False
            elapsed_ms = None
            try:
                response["snapshot"] = self._write(f"attempt-{number:04}-raw.json", payload)
                elapsed = (utc(observed_at) - utc(start["started_at"])).total_seconds()
                require(elapsed >= 0, "Observation clock moved backwards")
                elapsed_ms = round(elapsed * 1000)
                require(status in {"ok", "empty", "failed", "blocked"}, "Invalid status")
                require(error is None or isinstance(error, dict), "Invalid error")
                require(error is None or status in {"failed", "blocked"}, "Error marked successful")
                require(not isinstance(payload, dict) or not payload.get("isError") or
                        status in {"failed", "blocked"}, "Tool error marked successful")
                require(cost is None or type(cost) in {int, float} and math.isfinite(cost) and cost >= 0,
                        "Invalid provider cost")
                if model_tokens is not None:
                    require(isinstance(model_tokens, dict) and set(model_tokens) ==
                            {"input_tokens", "output_tokens"} and all(v is None or
                            type(v) is int and v >= 0 for v in model_tokens.values()),
                            "Invalid provider tokens")
                if source is not None:
                    require(kind == "fetch" and status == "ok", "Only successful fetch admits text")
                    observation = self._source(source, payload, event_id, observed_at)
                response.update(payload=copy.deepcopy(payload), error=error,
                                source_metadata=copy.deepcopy(source))
                canonical(response)
            except Exception as exc:
                stop, status, observation, cost, model_tokens = True, "failed", None, None, None
                response["error"] = {"type": type(exc).__name__, "message": str(exc),
                                     "transport_error": error}
                response["capture_incomplete"] = "snapshot" not in response
            event = {"event_id": event_id, "kind": kind, "observed_at": observed_at,
                     "request": {**start["request"], "started_at": start["started_at"],
                                 **{k: self.plan[k] for k in ("story_id", "provider", "mode", "transport_id")}},
                     "response": response, "status": status,
                     "observation_ids": [observation["observation_id"]] if observation else [],
                     "usage": {"tool_calls": 1, "elapsed_ms": elapsed_ms,
                               "cost": cost, "model_tokens": model_tokens}}
            self._write(f"attempt-{number:04}-completed.json",
                        {"event": event, "observation": observation,
                         "started_sha256": digest(start), "stop_collection": stop})
            return copy.deepcopy(event)

    def _source(self, source, payload, event_id, observed_at):
        require(isinstance(source, dict) and set(source) ==
                {"fields", "completeness", "redirects", "published_at_utc"}, "Invalid source metadata")
        fields = source["fields"]
        allowed = {"source", "language", "url", "title", "description", "text", "published_at"}
        require(isinstance(fields, dict) and {"url", "text"} <= set(fields) <= allowed and
                all(isinstance(v, str) for v in fields.values()), "Invalid source fields")
        http_url(fields["url"])
        require(bool(fields["text"]) and any(fields["text"] in s for s in strings(payload)),
                "Source text must be an unchanged span of returned payload")
        require(source["completeness"] in {"full", "excerpt", "truncated", "unknown"},
                "Missing source completeness")
        require(source["redirects"] is None or isinstance(source["redirects"], list), "Invalid redirects")
        for url in source["redirects"] or []:
            http_url(url)
        if source["published_at_utc"] is not None:
            utc(source["published_at_utc"])
        return {"observation_id": event_id + "-source", "source_version_id": "sha256-" + digest(fields),
                "source_sha256": digest(fields), "fields": copy.deepcopy(fields),
                "observed_at": observed_at, "available_at": observed_at,
                "published_at_utc": source["published_at_utc"], "search_event_id": event_id}

    def package(self):
        """Replay-compatible evidence plus pending attempts; no silent crash success."""
        with self._guard():
            starts, completed = self._state()
            complete_ids = {c["event"]["event_id"] for c in completed}
            return {"search_events": [c["event"] for c in completed],
                    "observations": [c["observation"] for c in completed if c["observation"]],
                    "pending_attempts": [s for s in starts if s["event_id"] not in complete_ids]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "begin", "complete", "package"))
    parser.add_argument("--directory", required=True)
    parser.add_argument("--plan")
    parser.add_argument("--kind", choices=("search", "fetch"))
    parser.add_argument("--request")
    parser.add_argument("--event-id")
    parser.add_argument("--result")
    parser.add_argument("--source")
    parser.add_argument("--error")
    parser.add_argument("--status", choices=("ok", "empty", "failed", "blocked"), default="ok")
    args = parser.parse_args()
    def read(path):
        return json.loads(Path(path).read_text()) if path else None
    if args.action == "init":
        require(args.plan is not None, "init requires --plan")
        recorder = Recorder(args.directory, read(args.plan))
        result = {"plan_sha256": digest(recorder.plan)}
    else:
        recorder = Recorder(args.directory)
        if args.action == "begin":
            result = recorder.begin(args.kind, read(args.request))
        elif args.action == "complete":
            require(args.result is not None or args.error is not None, "complete requires result or error")
            result = recorder.complete(args.event_id, read(args.result), status=args.status,
                                       source=read(args.source), error=read(args.error))
        else:
            result = recorder.package()
    print(canonical(result).decode())


if __name__ == "__main__":
    main()
