#!/usr/bin/env python3
"""Rehydrate a pinned source-only casebook, offline. No application/model calls."""
import argparse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
from pathlib import Path
import re

SOURCE_FIELDS = ("source", "language", "url", "title", "description", "text", "published_at")
LEGACY_KEYS = set(SOURCE_FIELDS) | {"id", "theme", "story_label", "importance"}
CAPTURE_KEYS = {"id", "source", "url", "title", "text", "published_at"}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def timestamp(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        result = parsedate_to_datetime(value)
    if result.tzinfo is None:
        raise ValueError("Naive source timestamp")
    return result.astimezone(timezone.utc).isoformat()


def sanitize(row, kind):
    keys = set(row)
    allowed = [LEGACY_KEYS, LEGACY_KEYS | {"occurrence_id"}] if kind == "legacy" else [CAPTURE_KEYS]
    if keys not in allowed:
        raise ValueError(f"Unexpected {kind} article schema: {sorted(keys)}")
    result = {key: row[key] for key in SOURCE_FIELDS if key in row}
    if any(not isinstance(value, str) for value in result.values()):
        raise ValueError("Non-string source field")
    return result


def contained(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Locator escapes archive root")
    return path


def rehydrate(specs, roots):
    cache, records, versions = {}, {}, {}
    for spec in specs:
        if not re.fullmatch(r"O[0-9]{3,}", spec["observation_id"]) or not re.fullmatch(r"S[0-9]{3,}", spec["source_version_id"]):
            raise ValueError("Invalid observation or source version identity")
        if spec["observation_id"] in records:
            raise ValueError("Duplicate observation identity")
        known_hash = versions.setdefault(spec["source_version_id"], spec["source_sha256"])
        if known_hash != spec["source_sha256"]:
            raise ValueError("Source version identity reused for a revision")
        kind = spec["archive"]
        path = contained(roots[kind], spec["file"])
        if path not in cache:
            raw = path.read_bytes()
            cache[path] = (hashlib.sha256(raw).hexdigest(), json.loads(raw))
        file_hash, document = cache[path]
        if file_hash != spec["file_sha256"]:
            raise ValueError(f"Archive file digest mismatch: {spec['file']}")
        rows = document if kind == "legacy" else document["articles"]
        if not isinstance(rows, list):
            raise ValueError("Article container is not a list")
        # Validate the complete snapshot's article schema, even for unselected rows.
        for row in rows:
            sanitize(row, kind)
        row = rows[spec["row_index"]]
        if digest(row) != spec["row_sha256"]:
            raise ValueError("Raw row digest mismatch")
        fields = sanitize(row, kind)
        if digest(fields) != spec["source_sha256"]:
            raise ValueError("Sanitized source version digest mismatch")
        if fields["url"] != spec["url"]:
            raise ValueError("URL/locator mismatch")
        published = timestamp(fields["published_at"])
        if published != spec["published_at_utc"]:
            raise ValueError("Publication timestamp mismatch")
        observed = spec["observed_at"]
        if kind == "capture" and timestamp(document["captured_at"]) != observed:
            raise ValueError("Capture timestamp mismatch")
        records[spec["observation_id"]] = {
            "observation_id": spec["observation_id"], "source_version_id": spec["source_version_id"],
            "source_sha256": spec["source_sha256"], "fields": fields,
            "published_at_utc": published, "observed_at": observed,
            "snapshot_day": spec["snapshot_day"],
            "source_field_char_counts": {k: len(v) for k, v in fields.items()},
            "provenance": {k: spec[k] for k in ("archive", "file", "row_index", "file_sha256", "row_sha256")},
        }
    return records


def make_packets(cases, records):
    packets = {}
    case_ids = set()
    for case in cases:
        if not re.fullmatch(r"C[0-9]{2,}", case["case_id"]) or case["chronology_mode"] not in {"captured_observation", "publication_order_simulation"}:
            raise ValueError("Invalid case identity or chronology mode")
        if case["case_id"] in case_ids:
            raise ValueError("Duplicate case identity")
        case_ids.add(case["case_id"])
        seen, previous = [], None
        for number, checkpoint in enumerate(case["checkpoints"], 1):
            instant = checkpoint["at"]
            if previous is not None and timestamp(instant) <= timestamp(previous):
                raise ValueError("Checkpoints must be strictly chronological")
            previous = instant
            for observation_id in checkpoint["add_observation_ids"]:
                if observation_id in seen:
                    raise ValueError("Observation repeated within case")
                record = records[observation_id]
                availability = record["observed_at"] if case["chronology_mode"] == "captured_observation" else record["published_at_utc"]
                if availability is None or timestamp(availability) > timestamp(instant):
                    raise ValueError("Future source in prefix")
                seen.append(observation_id)
            prefix_id = f"{case['case_id']}-p{number:02d}"
            packet = {
                "case_id": case["case_id"], "prefix_id": prefix_id,
                "chronology_mode": case["chronology_mode"], "checkpoint_at": instant,
                "source_version_ids": list(dict.fromkeys(records[x]["source_version_id"] for x in seen)),
                "observations": [records[x] for x in seen],
                "evidence_span_convention": "observation_id + fields.<field> + [start,end) Unicode codepoint offsets; preserve raw HTML",
            }
            packets[f"prefixes/{case['case_id']}/{prefix_id}.json"] = packet
    return packets


def write_packets(output, packets, index):
    payloads = {name: (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
                for name, value in {**packets, "packet-index.json": index}.items()}
    payloads["traversal.txt"] = ("\n".join(sorted(packets)) + "\n").encode()
    targets = {contained(output, name): value for name, value in payloads.items()}
    # A frozen labeling packet is never rewritten; a conflicting file aborts all writes.
    for target, value in targets.items():
        if target.exists() and target.read_bytes() != value:
            raise ValueError(f"Output conflict; use a new directory: {target}")
    for target, value in targets.items():
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-root", type=Path, required=True)
    parser.add_argument("--capture-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest-dir", type=Path, default=Path(__file__).parent / "casebook")
    args = parser.parse_args()
    specs = json.loads((args.manifest_dir / "sources.json").read_text())["observations"]
    cases = json.loads((args.manifest_dir / "cases.json").read_text())["cases"]
    records = rehydrate(specs, {"legacy": args.legacy_root, "capture": args.capture_root})
    packets = make_packets(cases, records)
    index = {"schema_version": 1, "prefix_sha256": {name: digest(packet) for name, packet in sorted(packets.items())}}
    packet_digest = digest(index)
    freeze = json.loads((args.manifest_dir / "freeze.json").read_text())
    if packet_digest != freeze["packet_digest"] or digest(specs) != freeze["observations_digest"] or digest(cases) != freeze["cases_digest"]:
        raise ValueError("Frozen packet/manifests digest mismatch")
    # Verification completes before any packet is written.
    write_packets(args.output, packets, index)
    print(json.dumps({"packet_digest": packet_digest, "cases": len(cases), "observations": len(records), "source_versions": len({r['source_version_id'] for r in records.values()}), "prefixes": len(packets)}, sort_keys=True))


if __name__ == "__main__":
    main()
