"""Versioned D and source-local E candidates; I/R/B remain unimplemented."""
import copy
import json
from pathlib import Path

import replay

VERSION = "codex-DE-v1"
PROMPT_DIR = Path(__file__).with_name("prompts")


def obj(**properties):
    return dict(type="object", properties=properties, required=list(properties), additionalProperties=False)


def array(item):
    return dict(type="array", items=item)


TEXT = {"type": "string"}
NULLABLE = {"type": ["string", "null"]}
LOCAL_SPAN = obj(source_version_id=TEXT, field=dict(type="string", enum=["title", "description", "text"]),
                 start={"type": "integer"}, end={"type": "integer"}, quote=TEXT)
SPAN = obj(observation_id=TEXT, **LOCAL_SPAN["properties"])
DELTA = obj(kind=dict(type="string", enum=sorted(replay.KINDS - {"context_only"})), contribution_ids=array(TEXT))
OUTPUT_SCHEMA = obj(schema_version=dict(type="integer", enum=[1]),
    contributions=array(obj(id=TEXT, kind=dict(type="string", enum=sorted(replay.KINDS)), claim=TEXT,
        attribution=TEXT, source_spans=array(SPAN), occurrence_id=NULLABLE, story_id=NULLABLE, uncertainty=array(TEXT))),
    relations=array(obj(**{"from": TEXT, "to": TEXT, "type": TEXT,
        "status": dict(type="string", enum=["accepted", "possible"]), "source_spans": array(SPAN)})),
    source_accounting=array(obj(observation_id=TEXT, status=dict(type="string", enum=["processed", "unassigned", "pending"]),
        contribution_ids=array(TEXT), reason=NULLABLE)),
    deltas=array(DELTA), questions=array(obj(id=TEXT, status=dict(type="string", enum=["open", "answered", "closed"]),
        claim=TEXT, source_spans=array(SPAN), closure_reason=NULLABLE)),
    analysis=array(obj(text=TEXT, evidence_contribution_ids=array(TEXT))), repair=obj(reason=NULLABLE, supersedes=NULLABLE))
EXTRACTION_SCHEMA = obj(schema_version=dict(type="integer", enum=[1]), source_version_id=TEXT,
    facts=array(obj(id=TEXT, claim=TEXT, attribution=TEXT, source_spans=array(LOCAL_SPAN), uncertainty=array(TEXT))),
    status=dict(type="string", enum=["processed", "unassigned", "pending"]), reason=NULLABLE)
DELTA_SCHEMA = obj(deltas=array(DELTA))


def prompt(name, payload):
    return (PROMPT_DIR / (name + "-v1.txt")).read_text(encoding="utf-8") + "\n\nUNTRUSTED INPUT JSON:\n" + \
        json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)


def recipe_hash():
    return replay.digest(dict(version=VERSION, schema=EXTRACTION_SCHEMA,
        prompt=(PROMPT_DIR / "extract-v1.txt").read_text(encoding="utf-8")))


def visible(context):
    """Reject prior interpretations, then copy only the replay source contract."""
    if any(key in context for key in ("prior_state", "previous_published", "seeded_defects", "labels")):
        raise ValueError("Reconstruction cannot see previous interpretation or evaluator labels")
    result = {key: copy.deepcopy(context[key]) for key in
              ("prefix_id", "day", "at", "chronology_mode", "observations", "coverage")}
    for row in result["observations"]:
        replay.keys(row, ("observation_id", "source_version_id", "source_sha256", "fields", "observed_at", "published_at_utc", "available_at"), ("search_event_id",))
        replay.require(isinstance(row["fields"], dict) and set(row["fields"]) <= replay.SOURCE_FIELDS and
                       all(isinstance(value, str) for value in row["fields"].values()) and
                       replay.digest(row["fields"]) == row["source_sha256"], "Invalid source fields/hash")
        replay.require(replay.instant(row["available_at"]) <= replay.instant(result["at"]), "Future source")
    return result


def reconstruct(backend, call_id, context, arm="D", artifact=None):
    if arm not in {"D", "E"}:
        raise ValueError("Only D/E candidates are implemented")
    source = visible(context)
    if arm == "E":
        replay.validate_artifacts({"extraction": artifact}, source, "E")
        replay.require(artifact["recipe_sha256"] == recipe_hash(), "Unknown extraction recipe")
        versions = {row["source_version_id"]: row for row in source["observations"]}
        replay.require(set(artifact["payload"]) == set(versions), "Incomplete extraction payload")
        for version, extraction in artifact["payload"].items():
            validate_extraction(extraction, versions[version])
        source["extraction"] = copy.deepcopy(artifact["payload"])
    elif artifact is not None:
        raise ValueError("D has no extraction artifact")
    def check(output):
        replay.validate_output(output, source)
        replay.require(output["deltas"] == [] and output["repair"] == {"reason": None, "supersedes": None},
                       "Canonical reconstruction must exclude previous-state interpretation/deltas")
    return backend.invoke(call_id, arm, prompt("reconstruct", dict(arm=arm, **source)), OUTPUT_SCHEMA, validate=check)


def validate_extraction(output, row):
    from codex_backend import validate_schema
    validate_schema(output, EXTRACTION_SCHEMA)
    replay.require(output["source_version_id"] == row["source_version_id"], "Wrong extraction source")
    replay.ids(output["facts"], "id")
    for fact in output["facts"]:
        spans = [dict(span, observation_id=row["observation_id"]) for span in fact["source_spans"]]
        replay.validate_spans(spans, {row["observation_id"]: row})
    replay.require(output["status"] != "processed" or bool(output["facts"]), "Processed extraction has no facts")
    replay.require(output["status"] != "unassigned" or not output["facts"], "Unassigned extraction has facts")
    replay.require(output["status"] == "processed" or bool(output["reason"]), "Missing extraction reason")


def extract(backend, call_id, row):
    """Exactly one source version. No corpus, interpretation, labels or cutoff."""
    payload = {key: copy.deepcopy(row[key]) for key in ("source_version_id", "source_sha256", "fields")}
    replay.require(isinstance(payload["fields"], dict) and set(payload["fields"]) <= replay.SOURCE_FIELDS and
                   all(isinstance(value, str) for value in payload["fields"].values()) and
                   replay.digest(payload["fields"]) == payload["source_sha256"], "Invalid extraction source")
    return backend.invoke(call_id, "E_extract", prompt("extract", payload), EXTRACTION_SCHEMA,
                          validate=lambda output: validate_extraction(output, row))


def extraction_artifact(context, extractions):
    """Prefix-safe selection of previously recorded successful source-only results."""
    source = visible(context)
    versions = {row["source_version_id"]: row["source_sha256"] for row in source["observations"]}
    payload = {}
    for row in source["observations"]:
        response = extractions[row["source_version_id"]]
        replay.require(response["status"] == "ok", "Failed extraction cannot become an artifact")
        validate_extraction(response["output"], row)
        payload[row["source_version_id"]] = copy.deepcopy(response["output"])
    return dict(kind="extraction", version=VERSION, cutoff=context["at"], source_only=True,
                source_versions=versions, recipe_sha256=recipe_hash(), payload=payload)


def compare_delta(backend, call_id, context):
    replay.keys(context, ("prefix_id", "at", "current", "previous_published"))
    return backend.invoke(call_id, "delta", prompt("delta", context), DELTA_SCHEMA,
        validate=lambda output: replay.validate_deltas(output["deltas"],
                     {row["id"] for row in context["current"]["contributions"]}))
