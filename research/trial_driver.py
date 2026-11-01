"""Pinned source-free preflight and invented D/E diagnostic. Never natural news."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import codex_backend as cb
import model_adapters as ma
import replay

GLOBAL = dict(calls=18, input_tokens=480000, output_tokens=72000,
              model_active_seconds=1800, wall_seconds=2700, failures=2)
CODE = ("research/trial_driver.py", "research/codex_backend.py", "research/model_adapters.py", "research/replay.py",
        "research/prompts/reconstruct-v1.txt", "research/prompts/extract-v1.txt", "research/prompts/delta-v1.txt")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def schemas():
    return {name: replay.digest(value) for name, value in
            (("reconstruction", ma.OUTPUT_SCHEMA), ("extraction", ma.EXTRACTION_SCHEMA), ("delta", ma.DELTA_SCHEMA))}


def bridge_preflight(summary_path, output_path):
    """Append a verified accounting bridge for the earlier root-owned probe wrapper."""
    path, destination = Path(summary_path).resolve(), Path(output_path).resolve()
    replay.require(destination.parent == path.parent and destination != path, "Bridge must be a new sibling file")
    summary = read(path)
    replay.require(summary["phase"] == "preflight" and summary["application_invocations"] == 1, "Unexpected wrapper phase")
    ledger = Path(summary["ledger"]).resolve()
    replay.require(ledger.is_relative_to(path.parent), "Wrapper ledger outside phase directory")
    requests, terminals = list(ledger.glob("*/request.json")), list(ledger.glob("*/terminal.json"))
    replay.require(len(requests) == len(terminals) == 1 and requests[0].parent == terminals[0].parent, "Incomplete wrapper attempt")
    request, terminal = read(requests[0]), read(terminals[0])
    replay.require(request["stage"] == "probe" and request["model"] == cb.MODEL and request["reasoning_effort"] == cb.EFFORT, "Unexpected wrapper model/stage")
    usage = terminal["response"]["usage"]
    replay.validate_usage(usage)
    replay.require(summary["reported_usage"] == usage and summary["status"] == terminal["response"]["status"], "Wrapper summary disagrees with terminal")
    start = read(path.parent / "trial-start.json")
    replay.require(start["started_at"] == summary["started_at"], "Wrapper clock mismatch")
    actual = dict(calls=1, input_tokens=usage["input_tokens"] or 0, output_tokens=usage["output_tokens"] or 0,
                  model_active_seconds=terminal["elapsed_seconds"], failures=int(summary["status"] != "ok"))
    success = summary["status"] == "ok" and summary["expected_output_match"] is True
    if success:
        cb.validate_schema(terminal["response"]["output"], request["schema"])
    stopped = "unknown_usage" if None in usage.values() else summary["global_stop"]
    report = dict(schema_version=1, phase="preflight", status="completed" if success else "incomplete", actual=actual,
                  clock_origin=summary["started_at"], global_stop=stopped, backend_roots=[str(ledger.relative_to(path.parent))],
                  slots=[dict(call_id=request["call_id"], status=summary["status"]),
                         dict(call_id="transport-diagnostic-v1", status="unused", reason="Not dispatched by original wrapper")],
                  bridge_source=str(path), record_pins=[])
    files = [path, path.parent / "trial-start.json", path.parent / "preflight-execution-v1.json"]
    files += [p for p in ledger.rglob("*") if p.is_file()]
    report["record_pins"] = [dict(path=str(p.relative_to(path.parent)), sha256=sha(p)) for p in sorted(files)]
    cb.save(destination, report)
    return report


class Capsule:
    def __init__(self, root, path):
        self.root, self.path = Path(root).resolve(), Path(path).resolve()
        self.value = read(path)
        self.digest = sha(path)
        replay.keys(self.value, ("schema_version", "phase", "files", "phase_plan", "source", "schemas",
                                "executable", "review_record", "prior_runs"))
        replay.require(type(self.value["schema_version"]) is int and self.value["schema_version"] == 1, "Invalid capsule version")
        replay.require(self.value["phase"] in {"preflight", "synthetic"}, "Unsupported phase")
        self.pins = {}
        for pin in self.value["files"]:
            replay.keys(pin, ("path", "sha256"))
            replay.require(pin["path"] not in self.pins, "Duplicate pin")
            self.pins[pin["path"]] = pin["sha256"]
        replay.require(set(CODE) <= set(self.pins), "Missing code/prompt pins")
        replay.require(self.value["schemas"] == schemas(), "Schema pins changed")
        for module in (cb, ma, replay):
            replay.require(Path(module.__file__).resolve() == self.root / "research" / Path(module.__file__).name,
                           "Imported code outside pinned root")
        replay.require(Path(__file__).resolve() == self.root / "research/trial_driver.py", "Driver outside pinned root")
        replay.keys(self.value["executable"], ("path", "sha256", "version"))
        replay.require(isinstance(self.value["executable"]["version"], str) and bool(self.value["executable"]["version"]), "Missing executable version")
        self.verify()
        self.file(self.value["review_record"])

    def file(self, name):
        replay.require(isinstance(name, str) and name in self.pins, "Unpinned input: " + str(name))
        path = (self.root / name).resolve()
        replay.require(path.is_relative_to(self.root) and not Path(name).is_absolute(), "Input outside root")
        replay.require(sha(path) == self.pins[name], "Changed frozen file: " + name)
        return path

    def verify(self):
        replay.require(sha(self.path) == self.digest, "Execution capsule changed")
        for name in self.pins:
            self.file(name)
        executable = self.value["executable"]
        replay.require(sha(executable["path"]) == executable["sha256"], "Executable changed")
        replay.require(self.value["schemas"] == schemas(), "Schema changed")


def prior_state(capsule):
    totals = dict(calls=0, input_tokens=0, output_tokens=0, model_active_seconds=0., failures=0)
    origin, phases, unknown, stopped = None, [], False, None
    seen = set()
    for previous in capsule.value["prior_runs"]:
        replay.keys(previous, ("path", "sha256"))
        path = Path(previous["path"]).resolve()
        replay.require(str(path) not in seen, "Duplicate prior report")
        seen.add(str(path))
        replay.require(sha(path) == previous["sha256"], "Prior report changed")
        report = read(path)
        replay.require(report["schema_version"] == 1 and report["phase"] not in phases, "Duplicate prior phase")
        if capsule.value["phase"] == "synthetic":
            replay.require(report["phase"] == "preflight" and report["status"] == "completed", "Successful preflight required")
        phases.append(report["phase"])
        for pin in report["record_pins"]:
            record = (path.parent / pin["path"]).resolve()
            replay.require(record.is_relative_to(path.parent) and sha(record) == pin["sha256"], "Prior call record changed")
        roots = [(path.parent / name).resolve() for name in report["backend_roots"]]
        replay.require(all(root.is_relative_to(path.parent) for root in roots), "Prior backend outside report directory")
        requests = [p for root in roots for p in root.glob("*/request.json")]
        terminals = [p for root in roots for p in root.glob("*/terminal.json")]
        replay.require(len(requests) == report["actual"]["calls"] == len(terminals), "Incomplete prior dispatch accounting")
        pinned = {pin["path"] for pin in report["record_pins"]}
        replay.require(all(str(p.relative_to(path.parent)) in pinned for p in requests + terminals), "Unpinned prior attempt")
        actual = dict(calls=len(terminals), input_tokens=0, output_tokens=0, model_active_seconds=0., failures=0)
        for terminal in terminals:
            row = read(terminal)
            usage = row["response"]["usage"]
            unknown |= None in usage.values()
            for key in ("input_tokens", "output_tokens"):
                if usage[key] is not None:
                    replay.require(replay.integer(usage[key]), "Invalid prior usage")
                    actual[key] += usage[key]
            actual["model_active_seconds"] += row["elapsed_seconds"]
            actual["failures"] += row["response"]["status"] != "ok"
        replay.require(all(abs(actual[k] - report["actual"][k]) < 0.000001 if k == "model_active_seconds"
                           else actual[k] == report["actual"][k] for k in actual), "Prior summary/terminal mismatch")
        for key in totals:
            totals[key] += actual[key]
        if report["clock_origin"]:
            origin = min(origin, report["clock_origin"]) if origin else report["clock_origin"]
        stopped = stopped or report["global_stop"]
    if unknown:
        stopped = "unknown_usage"
    return totals, origin, phases, stopped


class Shared:
    def __init__(self, capsule, report):
        self.capsule, self.report = capsule, report
        self.total, self.origin, phases, self.stopped = prior_state(capsule)
        replay.require(capsule.value["phase"] not in phases, "Phase already executed")
        replay.require(capsule.value["phase"] != "synthetic" or phases == ["preflight"], "Synthetic phase requires pinned preflight report")
        if self.origin:
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(self.origin)).total_seconds()
            replay.require(elapsed >= 0, "Clock moved backwards")
        else:
            elapsed = 0
        self.started, self.prior_wall = time.monotonic(), elapsed

    def dispatch(self, backend, call_id, stage, prompt, schema, validate=None):
        self.capsule.verify()
        if self.stopped:
            raise RuntimeError("Shared stop: " + self.stopped)
        slot = backend.plan["schedule"][backend.calls]
        remaining = min(GLOBAL["model_active_seconds"] - self.total["model_active_seconds"],
                        GLOBAL["wall_seconds"] - self.prior_wall - (time.monotonic() - self.started))
        if self.total["calls"] >= GLOBAL["calls"] or self.total["failures"] >= GLOBAL["failures"] or remaining <= 0 or \
                any(self.total[key] + slot[key] > GLOBAL[key] for key in ("input_tokens", "output_tokens")):
            self.stopped = "global_budget_exhausted"
            raise RuntimeError(self.stopped)
        if self.origin is None:
            self.origin = datetime.now(timezone.utc).isoformat()
        before = backend.active_seconds
        response = backend.invoke(call_id, stage, prompt, schema, validate=validate, remaining_seconds=remaining)
        elapsed = backend.active_seconds - before
        for counter in (self.total, self.report["actual"]):
            counter["calls"] += 1
            counter["model_active_seconds"] += elapsed
            counter["failures"] += response["status"] != "ok"
            for key in ("input_tokens", "output_tokens"):
                if response["usage"][key] is not None:
                    counter[key] += response["usage"][key]
        if None in response["usage"].values():
            self.stopped = "unknown_usage"
        elif backend.stopped in {"isolation_event_failure", "token_threshold_overshoot"}:
            self.stopped = backend.stopped
        if any(self.total[key] > GLOBAL[key] for key in ("input_tokens", "output_tokens")):
            self.stopped = "global_token_overshoot"
        return response


class Guarded:
    def __init__(self, shared, backend):
        self.shared, self.backend = shared, backend

    def invoke(self, *args, **kwargs):
        return self.shared.dispatch(self.backend, *args, **kwargs)


def run(capsule_path, root, output_dir):
    capsule = Capsule(root, capsule_path)
    phase = capsule.value["phase"]
    plan = read(capsule.file(capsule.value["phase_plan"]))
    replay.require(plan["schema_version"] == 1 and plan["phase"] == phase, "Phase plan mismatch")
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    cb.save(output / "capsule.json", capsule.value)
    report = dict(schema_version=1, phase=phase, capsule_sha256=capsule.digest, status="running", slots=[],
                  actual=dict(calls=0, input_tokens=0, output_tokens=0, model_active_seconds=0., failures=0),
                  clock_origin=None, global_stop=None, record_pins=[], backend_roots=[])
    shared = Shared(capsule, report)
    backends = {}
    try:
        expected = {"preflight"} if phase == "preflight" else {"D", "E"}
        replay.require(set(plan["backend_plans"]) == expected, "Unexpected phase backends")
        for arm, name in plan["backend_plans"].items():
            backend_plan = read(capsule.file(name))
            purpose = "transport_probe" if phase == "preflight" else "synthetic_diagnostic"
            replay.require(backend_plan["purpose"] == purpose, "Wrong diagnostic purpose")
            replay.require(len(backend_plan["schedule"]) <= {"preflight": 2, "D": 4, "E": 7}[arm], "Phase call ceiling")
            backends[arm] = cb.Backend(output / "backends" / arm, backend_plan, capsule.value["executable"]["path"])
            report["backend_roots"].append("backends/" + arm)
        if phase == "preflight":
            replay.require(capsule.value["source"] is None and len(plan["inputs"]) in {1, 2}, "Preflight must be source-free")
            inputs = [read(capsule.file(name)) for name in plan["inputs"]]
            backend = backends["preflight"]
            replay.require([value["call_id"] for value in inputs] == [s["call_id"] for s in backend.plan["schedule"]], "Preflight schedule mismatch")
            value = inputs[0]
            response = shared.dispatch(backend, value["call_id"], "probe", value["prompt"], value["response_schema"],
                validate=lambda result: replay.require(result == value["expected_output"], "Probe acknowledgement mismatch"))
            report["slots"].append(dict(call_id=value["call_id"], status=response["status"]))
            for unused in inputs[1:]:
                report["slots"].append(dict(call_id=unused["call_id"], status="unused", reason="Reserved diagnostic is never automatically dispatched"))
        else:
            manifest = read(capsule.file(capsule.value["source"]))
            replay.validate_manifest(manifest)
            replay.require(manifest["chronology_mode"] == "synthetic_stress" and not manifest.get("search_events") and
                           all("search_event_id" not in row for row in manifest["observations"]), "Only frozen invented sources allowed")
            boundaries = {value["prefix_id"]: value for value in manifest["boundaries"]}
            for arm in backends:
                selected = [row for row in plan["order"] if row["arm"] == arm]
                replay.require([(s["call_id"], s["stage"]) for s in selected] ==
                               [(s["call_id"], s["stage"]) for s in backends[arm].plan["schedule"]], "Interleaved schedule mismatch")
                replay.require(all(s["stage"] in ({"D", "delta"} if arm == "D" else {"E_extract", "E", "delta"}) for s in selected), "Wrong arm stage")
            replay.require(all(s["arm"] in backends for s in plan["order"]), "Unknown scheduled arm")
            failed, current, published, extractions = set(), {}, {}, {}
            for slot in plan["order"]:
                arm, stage = slot["arm"], slot["stage"]
                status = dict(call_id=slot["call_id"], arm=arm, status="pending")
                report["slots"].append(status)
                if shared.stopped or arm in failed:
                    status["reason"] = shared.stopped or "Earlier arm dependency failed"
                    continue
                context = replay.prefix(manifest, boundaries[slot["prefix_id"]])
                backend = Guarded(shared, backends[arm])
                try:
                    if stage == "E_extract":
                        rows = [row for row in context["observations"] if row["source_version_id"] == slot["source_version_id"]]
                        replay.require(bool(rows) and slot["source_version_id"] not in extractions, "Missing/repeated extraction dependency")
                        response = ma.extract(backend, slot["call_id"], rows[0])
                        extractions[slot["source_version_id"]] = response
                    elif stage in {"D", "E"}:
                        artifact = ma.extraction_artifact(context, extractions) if arm == "E" else None
                        response = ma.reconstruct(backend, slot["call_id"], context, arm, artifact)
                        current[arm] = (slot["prefix_id"], response["output"])
                        cb.save(output / (slot["call_id"] + "-canonical.json"), response)
                    else:
                        replay.require(arm in current and current[arm][0] == slot["prefix_id"], "Missing reconstruction dependency")
                        response = ma.compare_delta(backend, slot["call_id"], dict(prefix_id=slot["prefix_id"], at=context["at"],
                            current=current[arm][1], previous_published=published.get(arm)))
                        if response["status"] == "ok":
                            view = dict(current[arm][1], deltas=response["output"]["deltas"])
                            published[arm] = dict(version=replay.digest(view), at=context["at"], output=view, origin="synthetic_diagnostic")
                            cb.save(output / (slot["call_id"] + "-published.json"), published[arm])
                    status["status"] = response["status"]
                    if response["status"] != "ok":
                        failed.add(arm)
                        status["reason"] = response["error"]
                except (ValueError, KeyError, RuntimeError) as error:
                    failed.add(arm)
                    status.update(status="pending", reason=str(error))
        report["status"] = "completed" if all(s["status"] in {"ok", "unused"} for s in report["slots"]) else "incomplete"
    except BaseException as error:
        report.update(status="interrupted" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "invalid", error=str(error))
        raise
    finally:
        report.update(clock_origin=shared.origin, global_stop=shared.stopped, combined=shared.total)
        report["record_pins"] = [{"path": str(path.relative_to(output)), "sha256": sha(path)}
                                 for path in sorted(output.rglob("*")) if path.is_file()]
        cb.save(output / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("capsule", "root", "output"):
        parser.add_argument("--" + key, type=Path)
    parser.add_argument("--bridge-preflight", type=Path)
    args = parser.parse_args()
    if args.bridge_preflight:
        if args.output is None or args.capsule or args.root:
            parser.error("--bridge-preflight requires --output only")
        report = bridge_preflight(args.bridge_preflight, args.output)
        print(json.dumps({key: report[key] for key in ("status", "actual", "global_stop")}))
        return 0
    if not all((args.capsule, args.root, args.output)):
        parser.error("--capsule, --root and --output are required")
    report = run(args.capsule, args.root, args.output)
    print(json.dumps({key: report[key] for key in ("status", "actual", "global_stop")}))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
