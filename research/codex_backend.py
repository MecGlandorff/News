"""Bounded Codex subprocess transport; no automatic process retries or cost estimates."""
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import tempfile
import time

MODEL, EFFORT = "gpt-6-astra", "medium"
DISABLED = ("shell_tool", "unified_exec", "apps", "plugins", "remote_plugin",
            "multi_agent", "multi_agent_v2", "browser_use", "browser_use_external",
            "computer_use", "in_app_browser", "in_app_local_automation", "image_generation",
            "hooks", "skill_search", "tool_suggest", "memories", "code_mode_host",
            "code_mode", "view_image", "sleep_tool", "goals", "unbounded_connection_retries")
MAX_STREAM_BYTES = 4 * 1024 * 1024
ENVIRONMENT_KEYS = {"HOME", "PATH", "USER", "LOGNAME", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE",
                    "CODEX_HOME", "SSL_CERT_FILE", "SSL_CERT_DIR", "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "NO_PROXY",
                    "https_proxy", "http_proxy", "all_proxy", "no_proxy"}


def save(path, value):
    with Path(path).open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def positive(value):
    return type(value) in (int, float) and 0 < value < float("inf")


def validate_schema(value, schema):
    """Validate the deliberately small JSON Schema subset used by these adapters."""
    types = {"object": lambda v: isinstance(v, dict), "array": lambda v: isinstance(v, list),
             "string": lambda v: isinstance(v, str), "integer": lambda v: type(v) is int,
             "null": lambda v: v is None, "boolean": lambda v: type(v) is bool}
    allowed = schema.get("type", [])
    allowed = [allowed] if isinstance(allowed, str) else allowed
    if not allowed or not any(types[t](value) for t in allowed):
        raise ValueError("Schema type mismatch")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError("Schema enum mismatch")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        if not set(schema.get("required", [])) <= set(value):
            raise ValueError("Schema missing property")
        if schema.get("additionalProperties") is False and not set(value) <= set(properties):
            raise ValueError("Schema unexpected property")
        for key in value.keys() & properties.keys():
            validate_schema(value[key], properties[key])
    elif isinstance(value, list):
        for item in value:
            validate_schema(item, schema["items"])


def command(executable, schema_path, response_path):
    args = [str(executable), "exec", "--ignore-user-config", "--json", "--ephemeral",
            "--skip-git-repo-check", "--sandbox", "read-only", "--model", MODEL,
            "-c", 'model_reasoning_effort="medium"', "-c", 'web_search="disabled"',
            "--output-schema", str(schema_path), "--output-last-message", str(response_path)]
    for feature in DISABLED:
        args.extend(("--disable", feature))
    return args + ["-"]


def safe_event(event):
    """Fail closed on tools and unfamiliar event/item types; this is detection."""
    if not isinstance(event, dict):
        return False
    if event.get("type") in {"thread.started", "turn.started", "turn.completed", "turn.failed", "error"}:
        return True
    return event.get("type") in {"item.started", "item.updated", "item.completed"} and \
        isinstance(event.get("item"), dict) and event["item"].get("type") in {"agent_message", "reasoning"}


def stop_group(process):
    """Bounded TERM/KILL cleanup also covers descendants of an exited parent."""
    for sig, grace in ((signal.SIGTERM, .2), (signal.SIGKILL, .2)):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            break
        try:
            process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            pass
    try:
        process.wait(timeout=.2)
    except subprocess.TimeoutExpired:
        pass


class Backend:
    """One frozen finite schedule; every dispatched slot has its own immutable files.

    Isolation is an external reviewed attestation, not established by this class.
    Limited isolation permits only a source-free transport probe. Token limits are
    post-call thresholds, never claimed as provider-enforced output ceilings.
    """

    def __init__(self, output_dir, plan, executable="codex"):
        self.plan = copy.deepcopy(plan)
        if set(plan) != {"schema_version", "purpose", "isolation", "schedule", "budget"} or type(plan["schema_version"]) is not int or plan["schema_version"] != 1:
            raise ValueError("Invalid backend plan")
        if plan["purpose"] not in {"transport_probe", "candidate"}:
            raise ValueError("Invalid purpose")
        isolation = plan["isolation"]
        if set(isolation) != {"status", "evidence"} or isolation["status"] not in {"limited", "verified"} or not isinstance(isolation["evidence"], str) or not isolation["evidence"]:
            raise ValueError("Missing isolation evidence")
        if plan["purpose"] == "candidate" and isolation["status"] != "verified":
            raise ValueError("Candidate calls require reviewed preventive isolation evidence")
        schedule, budget = plan["schedule"], plan["budget"]
        if not isinstance(schedule, list) or not schedule:
            raise ValueError("Empty call schedule")
        seen = set()
        for slot in schedule:
            if set(slot) != {"call_id", "stage", "input_tokens", "output_tokens", "timeout_seconds"}:
                raise ValueError("Invalid scheduled call")
            if not isinstance(slot["call_id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]+", slot["call_id"]) or slot["call_id"] in seen:
                raise ValueError("Unsafe or repeated call ID")
            seen.add(slot["call_id"])
            if slot["stage"] not in {"probe", "D", "E_extract", "E", "delta", "search_plan"} or (plan["purpose"] == "transport_probe" and slot["stage"] != "probe"):
                raise ValueError("Undeclared stage")
            if any(type(slot[k]) is not int or slot[k] <= 0 for k in ("input_tokens", "output_tokens")) or not positive(slot["timeout_seconds"]) or slot["timeout_seconds"] > 120:
                raise ValueError("Invalid per-call thresholds")
        if set(budget) != {"input_tokens", "output_tokens", "model_active_seconds", "wall_seconds", "max_failures"} or any(not positive(v) for v in budget.values()):
            raise ValueError("Invalid finite budget")
        if any(type(budget[k]) is not int for k in ("input_tokens", "output_tokens", "max_failures")):
            raise ValueError("Invalid integer budget")
        self.output_dir = Path(output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=False)
        self.executable = executable
        self.started = time.monotonic()
        self.calls, self.failures, self.active_seconds = 0, 0, 0.
        self.known_usage = {"input_tokens": 0, "output_tokens": 0}
        self.unknown_usage_calls, self.stopped = 0, None
        save(self.output_dir / "backend-plan.json", dict(plan=plan, model=MODEL, reasoning_effort=EFFORT,
             token_bounds_enforced=False, cost=None, disabled_features=list(DISABLED),
             backend_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             environment_key_allowlist=sorted(ENVIRONMENT_KEYS)))

    def invoke(self, call_id, stage, prompt, schema, validate=None):
        if self.stopped:
            raise RuntimeError("Backend stopped: " + self.stopped)
        if self.calls >= len(self.plan["schedule"]):
            raise RuntimeError("Call schedule exhausted")
        slot = self.plan["schedule"][self.calls]
        if (call_id, stage) != (slot["call_id"], slot["stage"]):
            raise ValueError("Call does not match frozen schedule")
        if not isinstance(prompt, str) or not prompt or not isinstance(schema, dict):
            raise ValueError("Invalid prompt/schema")
        budget = self.plan["budget"]
        remaining = min(slot["timeout_seconds"], budget["model_active_seconds"] - self.active_seconds,
                        budget["wall_seconds"] - (time.monotonic() - self.started))
        if remaining <= 0 or any(self.known_usage[k] + slot[k] > budget[k] for k in self.known_usage):
            self.stopped = "budget_exhausted"
            raise RuntimeError(self.stopped)
        directory = self.output_dir / call_id
        directory.mkdir(exist_ok=False)
        save(directory / "schema.json", schema)
        with (directory / "prompt.txt").open("x", encoding="utf-8") as handle:
            handle.write(prompt)
            handle.flush()
            os.fsync(handle.fileno())
        args = command(self.executable, directory / "schema.json", directory / "last-message.txt")
        request = dict(call_id=call_id, stage=stage, model=MODEL, reasoning_effort=EFFORT,
                       prompt=prompt, schema=schema, argv=args, thresholds=slot,
                       enforced_timeout_seconds=remaining, token_bounds_enforced=False,
                       started_at=datetime.now(timezone.utc).isoformat(), status="started")
        save(directory / "request.json", request)  # Durable before Popen, including launch failures.
        self.calls += 1
        started, process, interrupted = time.monotonic(), None, None
        events, error, output = [], None, None
        buffer, stream_bytes = b"", 0
        try:
            with tempfile.TemporaryDirectory(prefix="news2-empty-") as scratch, \
                    (directory / "prompt.txt").open("rb") as input_file, \
                    (directory / "stdout.jsonl").open("xb") as stdout_file, \
                    (directory / "stderr.txt").open("xb") as stderr_file, selectors.DefaultSelector() as selector:
                process = subprocess.Popen(args, stdin=input_file, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           cwd=scratch, shell=False, start_new_session=True,
                                           env={key: value for key, value in os.environ.items() if key in ENVIRONMENT_KEYS})
                for stream, target in ((process.stdout, stdout_file), (process.stderr, stderr_file)):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ, target)
                while selector.get_map():
                    if time.monotonic() - started >= remaining:
                        error = "process_timeout"
                        break
                    for key, _ in selector.select(timeout=min(.05, remaining)):
                        data = os.read(key.fileobj.fileno(), 65536)
                        if not data:
                            selector.unregister(key.fileobj)
                            key.fileobj.close()
                            continue
                        key.data.write(data)
                        key.data.flush()
                        stream_bytes += len(data)
                        if stream_bytes > MAX_STREAM_BYTES:
                            error = "stream_byte_limit"
                            break
                        if key.fileobj is process.stdout:
                            buffer += data
                            while b"\n" in buffer:
                                line, buffer = buffer.split(b"\n", 1)
                                if not line.strip():
                                    continue
                                try:
                                    event = json.loads(line)
                                except (ValueError, UnicodeDecodeError):
                                    error = "malformed_jsonl"
                                    break
                                events.append(event)
                                if not safe_event(event):
                                    error = "forbidden_or_unknown_event"
                                    break
                                if event.get("type") in {"turn.failed", "error"}:
                                    error = "backend_error_event"
                                    break
                    if error:
                        break
                if not error:
                    if buffer.strip():
                        event = json.loads(buffer)
                        events.append(event)
                        if not safe_event(event):
                            error = "forbidden_or_unknown_event"
                        elif event.get("type") in {"turn.failed", "error"}:
                            error = "backend_error_event"
                    process.wait(timeout=max(.001, remaining - (time.monotonic() - started)))
                    if process.returncode:
                        error = "process_exit:" + str(process.returncode)
                for handle in (stdout_file, stderr_file):
                    handle.flush()
                    os.fsync(handle.fileno())
        except (KeyboardInterrupt, SystemExit) as failure:
            interrupted, error = failure, type(failure).__name__
        except Exception as failure:
            error = type(failure).__name__ + ": " + str(failure)
        finally:
            if process is not None:
                stop_group(process)
                for stream in (process.stdout, process.stderr):
                    if stream and not stream.closed:
                        stream.close()
        elapsed = time.monotonic() - started
        self.active_seconds += elapsed
        completed = [event for event in events if isinstance(event, dict) and event.get("type") == "turn.completed"]
        usage = {"input_tokens": None, "output_tokens": None}
        if len(completed) == 1:
            raw_usage = completed[0].get("usage", {})
            if isinstance(raw_usage, dict):
                for key in usage:
                    value = raw_usage.get(key)
                    if type(value) is int and value >= 0:
                        usage[key] = value
        if len(completed) != 1:
            error = error or "missing_or_multiple_completed_turns"
        if any(event.get("type") in {"turn.failed", "error"} for event in events if isinstance(event, dict)):
            error = error or "backend_error_event"
        try:
            if (directory / "last-message.txt").exists():
                if (directory / "last-message.txt").stat().st_size > MAX_STREAM_BYTES:
                    raise ValueError("Last message exceeds byte limit")
                output = json.loads((directory / "last-message.txt").read_text(encoding="utf-8"))
                validate_schema(output, schema)
                if validate is not None:
                    validate(output)
            else:
                error = error or "missing_last_message"
        except Exception as failure:
            error = error or "invalid_output: " + str(failure)
        for key, value in usage.items():
            if value is not None:
                self.known_usage[key] += value
        if None in usage.values():
            self.unknown_usage_calls += 1
            self.stopped = "unknown_usage"
            error = error or "unknown_usage"
        elif any(usage[k] > slot[k] or self.known_usage[k] > budget[k] for k in usage):
            self.stopped = "token_threshold_overshoot"
            error = error or self.stopped
        if error:
            self.failures += 1
        if self.failures >= budget["max_failures"]:
            self.stopped = self.stopped or "failure_limit"
        if error == "forbidden_or_unknown_event":
            self.stopped = "isolation_event_failure"
        response = dict(status="failed" if error else "ok", output=output, usage=usage, error=error)
        save(directory / "response.json", response)
        save(directory / "usage.json", dict(usage=usage, raw_completed_events=completed, cost=None,
             elapsed_seconds=elapsed, process_returncode=process.returncode if process else None,
             token_bounds_enforced=False, stopped=self.stopped))
        save(directory / "terminal.json", dict(call_id=call_id, stage=stage, response=response,
             elapsed_seconds=elapsed, calls=self.calls, failures=self.failures, stopped=self.stopped,
             known_usage=self.known_usage, unknown_usage_calls=self.unknown_usage_calls,
             total_tokens=None if self.unknown_usage_calls else sum(self.known_usage.values())))
        if interrupted:
            raise interrupted
        return response
