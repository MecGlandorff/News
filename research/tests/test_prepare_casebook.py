import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / "prepare_casebook.py"
spec = importlib.util.spec_from_file_location("prepare_casebook", MODULE)
prep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prep)


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.row = dict(id=0, source="Example", language="en", url="https://example.test/a",
                        title="Title", description="Source says story_label literally.", text="",
                        published_at="Fri, 08 May 2026 17:30:51 +0200",
                        theme="FORBIDDEN THEME", story_label="FORBIDDEN LABEL", importance=99)
        self.path = self.root / "articles.json"
        self.write_rows([self.row])

    def write_rows(self, rows):
        self.path.write_text(json.dumps(rows))
        fields = prep.sanitize(rows[0], "legacy")
        self.observation = dict(observation_id="O001", source_version_id="S001", archive="legacy",
            file="articles.json", row_index=0, file_sha256=hashlib.sha256(self.path.read_bytes()).hexdigest(),
            row_sha256=prep.digest(rows[0]), source_sha256=prep.digest(fields), url=fields["url"],
            published_at_utc=prep.timestamp(fields["published_at"]), observed_at=None, snapshot_day="2026-05-08")

    def test_source_whitelist_removes_generated_fields_preserving_source_text(self):
        self.row["occurrence_id"] = "FORBIDDEN OCCURRENCE"
        self.write_rows([self.row])
        result = prep.rehydrate([self.observation], {"legacy": self.root})["O001"]
        encoded = json.dumps(result)
        self.assertNotIn("FORBIDDEN", encoded)
        self.assertEqual(result["fields"]["description"], self.row["description"])
        self.assertEqual(set(result["fields"]), set(prep.SOURCE_FIELDS))

    def test_unknown_field_schema_fails_even_on_unselected_row(self):
        other = dict(self.row, model_output="must not leak")
        self.path.write_text(json.dumps([self.row, other]))
        self.observation["file_sha256"] = hashlib.sha256(self.path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "schema"):
            prep.rehydrate([self.observation], {"legacy": self.root})

    def test_each_provenance_hash_is_enforced(self):
        for key in ("file_sha256", "row_sha256", "source_sha256"):
            with self.subTest(key=key):
                broken = dict(self.observation, **{key: "0" * 64})
                with self.assertRaisesRegex(ValueError, "digest mismatch"):
                    prep.rehydrate([broken], {"legacy": self.root})

    def test_archive_change_and_path_escape_fail(self):
        self.path.write_text("[]")
        with self.assertRaisesRegex(ValueError, "file digest mismatch"):
            prep.rehydrate([self.observation], {"legacy": self.root})
        with self.assertRaisesRegex(ValueError, "escapes"):
            prep.contained(self.root, "../other.json")

    def test_revisions_and_repeat_observations_are_not_collapsed(self):
        updated = dict(self.row, description="A revised source claim.")
        self.write_rows([self.row, updated, self.row])
        first = self.observation
        observations = [first]
        for index, row in ((1, updated), (2, self.row)):
            observations.append(dict(first, observation_id=f"O00{index+1}", row_index=index,
                source_version_id="S002" if index == 1 else "S001", row_sha256=prep.digest(row),
                source_sha256=prep.digest(prep.sanitize(row, "legacy"))))
        result = prep.rehydrate(observations, {"legacy": self.root})
        self.assertEqual(len(result), 3)
        self.assertNotEqual(result["O001"]["source_sha256"], result["O002"]["source_sha256"])
        self.assertEqual(result["O001"]["source_sha256"], result["O003"]["source_sha256"])

    def test_prefix_is_cumulative_and_cannot_contain_future_source(self):
        records = prep.rehydrate([self.observation], {"legacy": self.root})
        records["O002"] = copy.deepcopy(records["O001"])
        records["O002"].update(observation_id="O002", source_version_id="S002", published_at_utc="2026-05-09T15:30:51+00:00")
        case = dict(case_id="C01", chronology_mode="publication_order_simulation", checkpoints=[
            dict(at="2026-05-08T15:30:51+00:00", add_observation_ids=["O001"]),
            dict(at="2026-05-09T15:30:51+00:00", add_observation_ids=["O002"])])
        packets = list(prep.make_packets([case], records).values())
        self.assertEqual(packets[0]["source_version_ids"], ["S001"])
        self.assertEqual(packets[1]["source_version_ids"], ["S001", "S002"])
        case["checkpoints"][0]["add_observation_ids"] = ["O001", "O002"]
        with self.assertRaisesRegex(ValueError, "Future source"):
            prep.make_packets([case], records)

    def test_capture_clock_is_not_publication_clock(self):
        records = prep.rehydrate([self.observation], {"legacy": self.root})
        records["O001"]["observed_at"] = "2026-05-09T15:30:51+00:00"
        case = dict(case_id="C01", chronology_mode="captured_observation", checkpoints=[
            dict(at="2026-05-08T15:30:51+00:00", add_observation_ids=["O001"])])
        with self.assertRaisesRegex(ValueError, "Future source"):
            prep.make_packets([case], records)

    def test_reversed_checkpoint_order_fails(self):
        records = prep.rehydrate([self.observation], {"legacy": self.root})
        case = dict(case_id="C01", chronology_mode="publication_order_simulation", checkpoints=[
            dict(at="2026-05-09T15:30:51+00:00", add_observation_ids=["O001"]),
            dict(at="2026-05-08T15:30:51+00:00", add_observation_ids=[])])
        with self.assertRaisesRegex(ValueError, "strictly chronological"):
            prep.make_packets([case], records)

    def test_empty_duplicate_and_reused_identities_fail(self):
        for key in ("observation_id", "source_version_id"):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "Invalid"):
                prep.rehydrate([dict(self.observation, **{key: ""})], {"legacy": self.root})
        with self.assertRaisesRegex(ValueError, "Duplicate observation"):
            prep.rehydrate([self.observation, self.observation], {"legacy": self.root})
        revision = dict(self.observation, observation_id="O002", source_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "reused for a revision"):
            prep.rehydrate([self.observation, revision], {"legacy": self.root})

    def test_unknown_chronology_and_unsafe_or_duplicate_case_id_fail(self):
        records = prep.rehydrate([self.observation], {"legacy": self.root})
        case = dict(case_id="C01", chronology_mode="publication_order_simulation", checkpoints=[])
        for change in ({"case_id": "../../escape"}, {"case_id": ""}, {"chronology_mode": "unknown"}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "Invalid"):
                prep.make_packets([dict(case, **change)], records)
        with self.assertRaisesRegex(ValueError, "Duplicate case"):
            prep.make_packets([case, case], records)

    def test_existing_packet_is_untouched_and_conflicts_abort_before_write(self):
        output = self.root / "output"
        packets = {"prefixes/C01/C01-p01.json": {"value": "source"}}
        prep.write_packets(output, packets, {})
        target = output / "prefixes/C01/C01-p01.json"
        before = target.stat().st_mtime_ns
        prep.write_packets(output, packets, {})
        self.assertEqual(target.stat().st_mtime_ns, before)
        conflicting = {**packets, "prefixes/C02/C02-p01.json": {}}
        target.write_text("saved labeling packet")
        with self.assertRaisesRegex(ValueError, "Output conflict"):
            prep.write_packets(output, conflicting, {})
        self.assertEqual(target.read_text(), "saved labeling packet")
        self.assertFalse((output / "prefixes/C02/C02-p01.json").exists())
        with self.assertRaisesRegex(ValueError, "escapes"):
            prep.write_packets(output, {"../outside.json": {}}, {})


if __name__ == "__main__":
    unittest.main()
