#!/usr/bin/env python3
"""Small offline replay contract. Checks provenance/mechanics, never news meaning."""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time

BASELINE = "bc7b0fb93d3ca34fdb9400d91deb4a627cf96fe9"
SOURCE_FIELDS = {"source", "language", "url", "title", "description", "text", "published_at"}
KINDS = {"new_occurrence", "same_occurrence_material_fact", "source_correction",
         "question_opened", "question_answered", "question_closed", "conflict", "context_only"}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def keys(value, required, optional=()):
    require(isinstance(value, dict) and set(required) <= set(value) <= set(required) | set(optional),
            "Unexpected or missing fields: " + ",".join(required))


def integer(value):
    return type(value) is int and value >= 0


def string_list(value):
    return isinstance(value, list) and all(isinstance(x, str) and x for x in value)


def instant(value):
    require(isinstance(value, str) and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|\+00:00)", value),
            "Expected explicit UTC timestamp")
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def ids(rows, key):
    require(isinstance(rows, list), "Expected array")
    values = [row[key] for row in rows]
    require(all(isinstance(x, str) and x for x in values) and len(set(values)) == len(values),
            "Empty or duplicate identity")
    return set(values)


def validate_manifest(manifest):
    keys(manifest, ("schema_version", "fixture_id", "chronology_mode", "observations", "boundaries", "coverage"), ("search_events",))
    require(type(manifest["schema_version"]) is int and manifest["schema_version"] == 1, "Unknown manifest version")
    mode = manifest["chronology_mode"]
    require(mode in {"actual_observed", "editorial_reconstruction", "synthetic_stress", "captured_observation", "publication_order_simulation"}, "Unknown chronology")
    observations = manifest["observations"]
    ids(observations, "observation_id")
    versions, previous = {}, None
    for row in observations:
        keys(row, ("observation_id", "source_version_id", "source_sha256", "fields", "observed_at", "published_at_utc", "available_at"), ("search_event_id",))
        require(isinstance(row["source_version_id"], str) and row["source_version_id"], "Invalid source version")
        fields = row["fields"]
        require(isinstance(fields, dict) and set(fields) <= SOURCE_FIELDS and all(isinstance(x, str) for x in fields.values()), "Unexpected source fields")
        require(digest(fields) == row["source_sha256"], "Source digest mismatch")
        require(versions.setdefault(row["source_version_id"], row["source_sha256"]) == row["source_sha256"], "Source version reused for revision")
        available = instant(row["available_at"])
        require(previous is None or previous <= available, "Sources not chronological")
        previous = available
        for key in ("observed_at", "published_at_utc"):
            if row[key] is not None:
                instant(row[key])
        clock = "observed_at" if mode in {"actual_observed", "captured_observation"} else "published_at_utc"
        if mode != "synthetic_stress":
            require(row[clock] is not None and instant(row[clock]) == available, "Availability does not match chronology clock")
    require(manifest["boundaries"], "No boundaries")
    ids(manifest["boundaries"], "prefix_id")
    previous = None
    for boundary in manifest["boundaries"]:
        keys(boundary, ("prefix_id", "day", "at"))
        at = instant(boundary["at"])
        require(boundary["day"] == at.date().isoformat(), "UTC day/cutoff mismatch")
        require(previous is None or at > previous, "Boundaries not strictly chronological")
        previous = at
    require(all(instant(row["available_at"]) <= previous for row in observations), "Unscheduled future source")
    keys(manifest["coverage"], ("scope", "gaps"))
    require(isinstance(manifest["coverage"]["scope"], str) and isinstance(manifest["coverage"]["gaps"], list), "Invalid coverage scope/gaps")
    for gap in manifest["coverage"]["gaps"]:
        keys(gap, ("from", "to", "reason"))
        require(datetime.fromisoformat(gap["from"]).date().isoformat() == gap["from"] and
                datetime.fromisoformat(gap["to"]).date().isoformat() == gap["to"] and gap["from"] <= gap["to"], "Invalid coverage gap")
    events = manifest.get("search_events", [])
    event_ids = ids(events, "event_id")
    by_id = {row["observation_id"]: row for row in observations}
    linked = set()
    for event in events:
        keys(event, ("event_id", "kind", "observed_at", "request", "response", "observation_ids", "status", "usage"))
        require(event["kind"] in {"search", "fetch"} and event["status"] in {"ok", "empty", "failed", "blocked"}, "Invalid search event")
        at = instant(event["observed_at"])
        require(at <= previous, "Unscheduled future search")
        usage = event["usage"]
        keys(usage, ("tool_calls", "elapsed_ms", "cost", "model_tokens"))
        require(type(usage["tool_calls"]) is int and usage["tool_calls"] == 1 and (usage["elapsed_ms"] is None or integer(usage["elapsed_ms"])), "Invalid tool accounting")
        require(usage["cost"] is None or (type(usage["cost"]) in {float, int} and usage["cost"] >= 0), "Invalid tool cost")
        if usage["model_tokens"] is not None:
            validate_usage(usage["model_tokens"])
        refs = event["observation_ids"]
        require(string_list(refs) and len(set(refs)) == len(refs), "Invalid or duplicate search observation")
        require(not refs or (event["kind"] == "fetch" and event["status"] == "ok"), "Only successful fetches admit source text")
        for ref in refs:
            require(ref in by_id and ref not in linked, "Invalid search observation link")
            row = by_id[ref]
            require(row.get("search_event_id") == event["event_id"] and instant(row["available_at"]) >= at, "Search provenance/availability mismatch")
            linked.add(ref)
    require(all(row.get("search_event_id") in event_ids and row["observation_id"] in linked
                for row in observations if "search_event_id" in row), "Unlinked search source")
    canonical(manifest)


def prefix(manifest, boundary, enrichment=False):
    at = instant(boundary["at"])
    observations = [row for row in manifest["observations"] if instant(row["available_at"]) <= at and
                    (enrichment or "search_event_id" not in row)]
    events = [event for event in manifest.get("search_events", []) if enrichment and instant(event["observed_at"]) <= at]
    visible = {row["observation_id"] for row in observations}
    require(all(set(event["observation_ids"]) <= visible for event in events), "Future source linked from search event")
    coverage = copy.deepcopy(manifest["coverage"])
    coverage["gaps"] = [dict(gap, to=min(gap["to"], boundary["day"])) for gap in coverage["gaps"] if gap["from"] <= boundary["day"]]
    return {**boundary, "chronology_mode": manifest["chronology_mode"], "observations": copy.deepcopy(observations),
            "coverage": coverage, "search_events": copy.deepcopy(events)}


def validate_spans(spans, observations):
    require(isinstance(spans, list) and spans, "Missing evidence spans")
    for span in spans:
        keys(span, ("observation_id", "source_version_id", "field", "start", "end", "quote"))
        require(span["observation_id"] in observations, "Future or unknown source span")
        source = observations[span["observation_id"]]
        require(span["source_version_id"] == source["source_version_id"], "Wrong source version in span")
        require(span["field"] in {"title", "description", "text"}, "Invalid evidence field")
        text = source["fields"].get(span["field"], "")
        start, end = span["start"], span["end"]
        require(integer(start) and integer(end) and start < end <= len(text), "Invalid evidence offsets")
        require(text[start:end] == span["quote"], "Exact quote mismatch")


def validate_deltas(deltas, contribution_ids):
    require(isinstance(deltas, list), "Invalid deltas")
    for delta in deltas:
        keys(delta, ("kind", "contribution_ids"))
        require(delta["kind"] in KINDS - {"context_only"}, "Repair/context is not a news delta")
        require(string_list(delta["contribution_ids"]) and delta["contribution_ids"] and set(delta["contribution_ids"]) <= contribution_ids, "Unknown delta contribution")


def validate_output(output, context):
    keys(output, ("schema_version", "contributions", "relations", "source_accounting", "deltas", "questions", "analysis", "repair"))
    require(type(output["schema_version"]) is int and output["schema_version"] == 1, "Unknown output version")
    require(all(isinstance(output[key], list) for key in ("contributions", "relations", "source_accounting", "deltas", "questions", "analysis")), "Expected output arrays")
    sources = {row["observation_id"]: row for row in context["observations"]}
    contribution_ids = ids(output["contributions"], "id")
    references, attributed = set(contribution_ids), {ref: set() for ref in sources}
    for contribution in output["contributions"]:
        keys(contribution, ("id", "kind", "claim", "attribution", "source_spans", "occurrence_id", "story_id", "uncertainty"))
        require(contribution["kind"] in KINDS and isinstance(contribution["claim"], str) and isinstance(contribution["attribution"], str), "Invalid contribution")
        require(isinstance(contribution["uncertainty"], list) and all(isinstance(x, str) for x in contribution["uncertainty"]), "Invalid uncertainty")
        for key in ("occurrence_id", "story_id"):
            value = contribution[key]
            require(value is None or (isinstance(value, str) and value), "Invalid interpretation identity")
            if value is not None:
                references.add(value)
        validate_spans(contribution["source_spans"], sources)
        for span in contribution["source_spans"]:
            attributed[span["observation_id"]].add(contribution["id"])
    for relation in output["relations"]:
        keys(relation, ("from", "to", "type", "status", "source_spans"))
        require(relation["from"] in references and relation["to"] in references and isinstance(relation["type"], str), "Unknown relation endpoint")
        require(relation["status"] in {"accepted", "possible"}, "Unknown relation status")
        validate_spans(relation["source_spans"], sources)
    require(ids(output["source_accounting"], "observation_id") == set(sources), "Incomplete visible source accounting")
    for row in output["source_accounting"]:
        keys(row, ("observation_id", "status", "contribution_ids", "reason"))
        refs = row["contribution_ids"]
        require(string_list(refs) and len(refs) == len(set(refs)) and set(refs) == attributed[row["observation_id"]], "Contribution accounting mismatch")
        require(row["status"] in {"processed", "unassigned", "pending"}, "Invalid source status")
        require((row["status"] != "processed" or refs) and (row["status"] != "unassigned" or not refs), "Inconsistent source status")
        require(row["reason"] is None or isinstance(row["reason"], str), "Invalid source reason")
        require(row["status"] == "processed" or bool(row["reason"]), "Missing unassigned/pending reason")
    validate_deltas(output["deltas"], contribution_ids)
    ids(output["questions"], "id")
    for question in output["questions"]:
        keys(question, ("id", "status", "claim", "source_spans", "closure_reason"))
        require(question["status"] in {"open", "answered", "closed"} and isinstance(question["claim"], str), "Invalid question")
        require(question["closure_reason"] is None or isinstance(question["closure_reason"], str), "Invalid question closure reason")
        require(question["status"] == "open" or bool(question["closure_reason"]), "Missing question closure reason")
        validate_spans(question["source_spans"], sources)
    for analysis in output["analysis"]:
        keys(analysis, ("text", "evidence_contribution_ids"))
        require(isinstance(analysis["text"], str) and string_list(analysis["evidence_contribution_ids"]) and set(analysis["evidence_contribution_ids"]) <= contribution_ids, "Invalid read-only analysis")
    keys(output["repair"], ("reason", "supersedes"))
    require(all(value is None or isinstance(value, str) for value in output["repair"].values()), "Invalid repair audit")
    canonical(output)


def validate_artifacts(artifacts, context, arm):
    require(isinstance(artifacts, dict), "Expected artifact mapping")
    required = {"extraction"} if arm in {"E", "I", "R"} else set()
    if arm == "R":
        required.add("index")
    require(set(artifacts) == required, "Arm artifacts do not match contract")
    versions = {row["source_version_id"]: row["source_sha256"] for row in context["observations"]}
    for kind, artifact in artifacts.items():
        keys(artifact, ("kind", "version", "cutoff", "source_only", "source_versions", "recipe_sha256", "payload"))
        require(artifact["kind"] == kind and artifact["source_only"] is True, "Interpretation-derived artifact")
        require(instant(artifact["cutoff"]) <= instant(context["at"]), "Future artifact cutoff")
        require(artifact["source_versions"] == versions, "Future, later-version or incomplete artifact corpus")
        available_versions = {row["source_version_id"] for row in context["observations"] if instant(row["available_at"]) <= instant(artifact["cutoff"])}
        require(available_versions == set(versions), "Source dependency is future to artifact cutoff")
        require(isinstance(artifact["version"], str) and re.fullmatch(r"[a-f0-9]{64}", artifact["recipe_sha256"]), "Unpinned artifact recipe")


def validate_usage(usage):
    keys(usage, ("input_tokens", "output_tokens"))
    require(all(value is None or integer(value) for value in usage.values()), "Invalid token telemetry")
    return None if None in usage.values() else sum(usage.values())


def validate_plan(plan, manifest):
    keys(plan, ("schema_version", "arm", "implementation_id", "enrichment", "delta_comparison", "budget", "per_call_tokens", "recovery_prefixes"), ("adapter",))
    require(type(plan["schema_version"]) is int and plan["schema_version"] == 1 and plan["arm"] in {"D", "E", "I", "R", "B"}, "Invalid arm/version")
    require(isinstance(plan["implementation_id"], str) and plan["implementation_id"], "Unidentified offline implementation")
    require(type(plan["enrichment"]) is bool and type(plan["delta_comparison"]) is bool, "Invalid experiment switches")
    keys(plan["budget"], ("calls", "tokens", "seconds", "tool_calls", "recovery_calls"))
    require(all(integer(value) for value in plan["budget"].values()) and integer(plan["per_call_tokens"]) and plan["per_call_tokens"] > 0, "Invalid finite budget")
    require(string_list(plan["recovery_prefixes"]) and set(plan["recovery_prefixes"]) <= {row["prefix_id"] for row in manifest["boundaries"]}, "Unknown recovery prefix")
    if plan["arm"] == "B":
        keys(plan.get("adapter"), ("baseline_revision", "adapter_sha256"))
        require(plan["adapter"]["baseline_revision"] == BASELINE and re.fullmatch(r"[a-f0-9]{64}", plan["adapter"]["adapter_sha256"]), "Unpinned baseline adapter")
    else:
        require("adapter" not in plan, "Adapter only belongs to B")


def save(path, value):
    with path.open("xb") as handle:
        handle.write(canonical(value) + b"\n")


def run(manifest, plan, candidate, output_dir, initial_state=None, artifacts=None, delta_compare=None, recorded_responses=None):
    """Invoke trusted *offline* callables on deep copies; persist every attempt.

    A callable returns {status, output, usage, error}; comparator output is {deltas}.
    There is no subprocess, import-by-name, model client, network or tool dispatcher.
    """
    manifest, plan = copy.deepcopy(manifest), copy.deepcopy(plan)
    artifacts, initial_state = copy.deepcopy({} if artifacts is None else artifacts), copy.deepcopy(initial_state)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    recorded_responses = copy.deepcopy(recorded_responses)
    frozen = {"manifest": manifest, "plan": plan, "initial_state": initial_state, "artifacts": artifacts,
              "recorded_responses": recorded_responses}
    save(output_dir / "inputs.json", frozen)
    report = {"schema_version": 1, "input_sha256": digest(frozen), "status": "running", "active": None,
              "history": [], "prefixes": [], "calls": [], "accounting": {"calls": 0, "known_tokens": 0,
              "unknown_usage_calls": 0, "tool_calls": 0, "recovery_calls": 0}, "search_events": []}
    started, last_state, last_published, stopped, seen_events = time.monotonic(), None, None, None, set()
    try:
        validate_manifest(manifest)
        validate_plan(plan, manifest)
        require(isinstance(artifacts, dict) and set(artifacts) <= {row["prefix_id"] for row in manifest["boundaries"]}, "Invalid prefix artifact mapping")
        if recorded_responses is not None:
            require(candidate is None and isinstance(recorded_responses, list), "Use either a callable or recorded responses")
            recording = iter(recorded_responses)
            candidate = lambda context: next(recording)
        require(callable(candidate) and (callable(delta_compare) == plan["delta_comparison"]), "Missing or undeclared callable")
        if initial_state is not None:
            validate_output(initial_state, prefix(manifest, manifest["boundaries"][0], plan["enrichment"]))
            last_state = {"version": digest(initial_state), "at": None, "output": initial_state, "origin": "seed"}
        budget, accounting = plan["budget"], report["accounting"]

        def invoke(function, context, stage, recovery):
            nonlocal stopped
            if (accounting["calls"] >= budget["calls"] or accounting["known_tokens"] + plan["per_call_tokens"] > budget["tokens"] or
                    time.monotonic() - started >= budget["seconds"] or
                    (recovery and accounting["recovery_calls"] >= budget["recovery_calls"])):
                stopped = "budget_exhausted"
                return None, stopped
            accounting["calls"] += 1
            if recovery:
                accounting["recovery_calls"] += 1
            record = {"call": accounting["calls"], "prefix_id": context["prefix_id"], "stage": stage, "recovery": recovery,
                      "context_sha256": digest(context), "response": None, "error": None, "status": "started"}
            save(output_dir / f"call-{accounting['calls']:04d}-started.json", record)
            call_started = time.monotonic()
            usage_recorded = False
            try:
                response = function(copy.deepcopy(context))
                try:
                    canonical(response)
                    record["response"] = copy.deepcopy(response)
                except (ValueError, TypeError) as invalid:
                    record["response_diagnostic"] = {"type": type(response).__name__, "serialization_error": str(invalid)}
                tokens = validate_usage(response["usage"]) if isinstance(response, dict) and "usage" in response else None
                if isinstance(response, dict) and "usage" in response:
                    accounting["known_tokens"] += sum(value for value in response["usage"].values() if integer(value))
                if tokens is None:
                    accounting["unknown_usage_calls"] += 1
                    stopped = "unknown_usage"
                else:
                    if tokens > plan["per_call_tokens"] or accounting["known_tokens"] > budget["tokens"]:
                        stopped = "token_overshoot"
                usage_recorded = True
                require("response_diagnostic" not in record, "Callable returned non-JSON response")
                keys(response, ("status", "output", "usage", "error"))
                require(response["error"] is None or isinstance(response["error"], str), "Invalid failure diagnostic")
                require(response["status"] in {"ok", "failed"}, "Invalid response status")
                require(response["status"] == "ok", "Candidate failure: " + str(response["error"]))
            except Exception as error:
                record["error"] = f"{type(error).__name__}: {error}"
                # A missing or invalid usage report cannot become free execution.
                if not usage_recorded:
                    accounting["unknown_usage_calls"] += 1
                    stopped = "unknown_usage"
            except (KeyboardInterrupt, SystemExit) as error:
                accounting["unknown_usage_calls"] += 1
                record.update(status="interrupted", error=type(error).__name__, elapsed_seconds=time.monotonic() - call_started)
                report["calls"].append(record)
                save(output_dir / f"call-{accounting['calls']:04d}.json", record)
                raise
            record["elapsed_seconds"] = time.monotonic() - call_started
            if time.monotonic() - started >= budget["seconds"]:
                stopped = "runtime_exhausted"
            record["status"] = "failed" if stopped or record["error"] else "returned"
            report["calls"].append(record)
            save(output_dir / f"call-{accounting['calls']:04d}.json", record)
            return record["response"], stopped or record["error"]

        for boundary in manifest["boundaries"]:
            report["active"] = None
            context = prefix(manifest, boundary, plan["enrichment"])
            context["arm"] = plan["arm"]
            context["artifacts"] = artifacts.get(boundary["prefix_id"], {})
            result = {**boundary, "status": "pending", "attempts": [], "version": None,
                      "source_accounting": [{"observation_id": row["observation_id"], "status": "pending",
                          "contribution_ids": [], "reason": "Prefix not completed"} for row in context["observations"]]}
            report["prefixes"].append(result)
            if stopped:
                result.update(status="budget_stopped", error=stopped)
                continue
            new_events = [event for event in context["search_events"] if event["event_id"] not in seen_events]
            if accounting["tool_calls"] + len(new_events) > budget["tool_calls"]:
                stopped = "tool_budget_exhausted"
                result.update(status="budget_stopped", error=stopped)
                continue
            seen_events.update(event["event_id"] for event in new_events)
            report["search_events"].extend(new_events)
            accounting["tool_calls"] += len(new_events)
            try:
                validate_artifacts(context["artifacts"], context, plan["arm"])
            except (ValueError, TypeError, KeyError) as error:
                result.update(status="failed", error=str(error))
                continue
            if plan["arm"] == "I":
                context["prior_state"] = copy.deepcopy(last_state)
            if plan["arm"] == "B":
                context["adapter"] = copy.deepcopy(plan["adapter"])
            for attempt in range(2):
                if attempt:
                    if (stopped or boundary["prefix_id"] not in plan["recovery_prefixes"] or accounting["recovery_calls"] >= budget["recovery_calls"]):
                        break
                context["recovery"] = bool(attempt)
                response, error = invoke(candidate, context, "candidate", bool(attempt))
                output = response.get("output") if isinstance(response, dict) else None
                if error is None:
                    try:
                        validate_output(output, context)
                        if plan["delta_comparison"]:
                            comparison = {"prefix_id": context["prefix_id"], "at": context["at"], "current": output,
                                          "previous_published": copy.deepcopy(last_published)}
                            compared, error = invoke(delta_compare, comparison, "delta_comparison", bool(attempt))
                            if error is None:
                                keys(compared["output"], ("deltas",))
                                validate_deltas(compared["output"]["deltas"], {row["id"] for row in output["contributions"]})
                                output = dict(output, deltas=compared["output"]["deltas"])
                    except (ValueError, TypeError, KeyError) as failure:
                        error = f"Invalid output: {failure}"
                version = None if error else digest({"prefix": boundary, "output": output, "previous": last_published and last_published["version"]})
                entry = {"prefix_id": boundary["prefix_id"], "attempt": attempt + 1, "status": "failed" if error else "success",
                         "error": error, "output": output, "version": version, "supersedes": last_state and last_state["version"]}
                save(output_dir / f"view-{len(report['history']) + 1:04d}.json", entry)
                report["history"].append(entry)
                result["attempts"].append(len(report["history"]))
                if error:
                    result.update(status="budget_stopped" if stopped else "failed", error=error)
                    continue
                last_state = {"version": version, "at": context["at"], "output": copy.deepcopy(output), "origin": "replay"}
                last_published = copy.deepcopy(last_state)
                report["active"] = version
                result.update(status="success", version=version, source_accounting=output["source_accounting"])
                result.pop("error", None)
                break
        report["status"] = "completed" if all(row["status"] == "success" for row in report["prefixes"]) else "incomplete"
    except (ValueError, TypeError, KeyError) as error:
        report.update(status="invalid", error=f"{type(error).__name__}: {error}", active=None)
    except (KeyboardInterrupt, SystemExit) as error:
        report.update(status="interrupted", error=type(error).__name__, active=None, elapsed_seconds=time.monotonic() - started)
        report["accounting"]["total_tokens"] = None
        save(output_dir / "report.json", report)
        raise
    report["elapsed_seconds"] = time.monotonic() - started
    report["accounting"]["total_tokens"] = None if report["accounting"]["unknown_usage_calls"] else report["accounting"]["known_tokens"]
    save(output_dir / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("manifest", "plan", "responses", "output"):
        parser.add_argument("--" + option, type=Path, required=True)
    args = parser.parse_args()
    responses = json.loads(args.responses.read_text())
    report = run(json.loads(args.manifest.read_text()), json.loads(args.plan.read_text()), None, args.output, recorded_responses=responses)
    print(json.dumps({key: report[key] for key in ("status", "active", "accounting")}, sort_keys=True))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
