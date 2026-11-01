#!/usr/bin/env python3
"""Export pinned, ungrouped development sources into ignored local storage.

This is a metadata/provenance transform, not a source labeler or replay scorer.
It reads no archive glob, source outside its explicit packet pins, or candidate.
"""

import argparse
import hashlib
import json
from pathlib import Path


FIELDS = {"title", "description", "text", "source", "url", "published_at", "language"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def pinned_file(root, relative, expected):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Pinned path escapes root")
    data = path.read_bytes()
    if sha(data) != expected:
        raise ValueError("Pinned file hash mismatch: " + relative)
    return data


def materialize(repo, packets, locator):
    """Return candidate input; never return the source/grouping/label locator map."""
    for pin in locator["reference_pins"]:
        pinned_file(repo, pin["path"], pin["sha256"])
    observations, cache, ids, versions = [], {}, set(), {}
    for row in locator["observations"]:
        pin = row["packet"]
        key = (pin["path"], pin["sha256"])
        if key not in cache:
            cache[key] = json.loads(pinned_file(packets, *key))
        packet = cache[key]
        if packet["chronology_mode"] != "captured_observation":
            raise ValueError("Publication simulation cannot enter captured stream")
        observation = packet["observations"][pin["observation_index"]]
        checks = {
            "observation_id": row["original_observation_id"],
            "source_version_id": row["original_source_version_id"],
            "source_sha256": row["source_sha256"],
            "observed_at": row["observed_at"],
            "published_at_utc": row["published_at_utc"],
            "provenance": row["archive_locator"],
        }
        if any(observation.get(k) != value for k, value in checks.items()):
            raise ValueError("Observation locator or provenance mismatch")
        fields = observation["fields"]
        if not isinstance(fields, dict) or not set(fields) <= FIELDS:
            raise ValueError("Unexpected source field")
        if not all(isinstance(value, str) for value in fields.values()):
            raise ValueError("Source fields must be strings")
        if sha(canonical(fields)) != row["source_sha256"]:
            raise ValueError("Source field hash mismatch")
        if row["available_at"] != observation["observed_at"] or not row["available_at"]:
            raise ValueError("Actual availability must equal observed capture")
        if row["observation_id"] in ids:
            raise ValueError("Duplicate neutral observation ID")
        ids.add(row["observation_id"])
        version = row["source_version_id"]
        if version in versions and versions[version] != row["source_sha256"]:
            raise ValueError("Source version collision")
        versions[version] = row["source_sha256"]
        observations.append({
            "observation_id": row["observation_id"],
            "source_version_id": version,
            "source_sha256": row["source_sha256"],
            "fields": fields,
            "observed_at": row["observed_at"],
            "published_at_utc": row["published_at_utc"],
            "available_at": row["available_at"],
        })
    return {
        "schema_version": 1,
        "fixture_id": locator["fixture_id"],
        "chronology_mode": "captured_observation",
        "observations": observations,
        "boundaries": locator["boundaries"],
        "coverage": {key: locator["coverage"][key] for key in ("scope", "gaps")},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packets", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(".news/research/replay-observed-v1.json"))
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    if not output.is_relative_to((repo / ".news").resolve()):
        raise ValueError("Real source text must stay beneath this checkout's ignored .news directory")
    path = Path(__file__).resolve().parent / "scorer/observed-capture-locators-v1.json"
    locator = json.loads(path.read_bytes())
    result = materialize(repo, args.packets.resolve(), locator)
    data = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode()
    if output.exists():
        if output.read_bytes() != data:
            raise ValueError("Refusing to overwrite a different output")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as handle:
            handle.write(data)
    print(json.dumps({"output": str(output), "sha256": sha(data), "observations": len(result["observations"])}))


if __name__ == "__main__":
    main()
