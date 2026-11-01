"""Offline receipt tests. Synthetic tool returns establish no search quality."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


recorder, replay = module("search_recorder"), module("replay")


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "receipts"
        self.plan = dict(collection_id="synthetic", story_id="frozen-seed", cutoff="2026-01-01T00:00:00Z",
                         scope="Synthetic question", provider="offline-stub", mode="synthetic",
                         transport_id="explicit-stub", max_searches=2, max_fetches=3)
        self.now = "2026-02-01T00:00:00Z"
        self.r = recorder.Recorder(self.path, self.plan, clock=lambda: self.now)

    def start(self, kind="search"):
        request = {"query": "synthetic question", "reason": "test"} if kind == "search" else {
            "url": "https://example.test/report", "reason": "test"}
        return self.r.begin(kind, request)["event_id"]

    def source(self, text="Original évidence\nsecond line"):
        return {"fields": {"url": "https://example.test/report", "text": text, "source": "Synthetic"},
                "completeness": "excerpt", "redirects": None,
                "published_at_utc": "2026-01-01T00:00:00Z"}

    def test_counts_survive_reopen_and_refusals_are_not_tool_events(self):
        for status in ("failed", "empty"):
            event_id = self.start()
            self.r.complete(event_id, {"results": []}, status=status)
            self.r = recorder.Recorder(self.path, clock=lambda: self.now)
        with self.assertRaises(recorder.BudgetExhausted):
            self.start()
        package = self.r.package()
        self.assertEqual(len(package["search_events"]), 2)
        self.assertEqual(sum(x["usage"]["tool_calls"] for x in package["search_events"]), 2)
        self.assertEqual(len(list(self.path.glob("refusal-*.json"))), 1)
        self.assertEqual(len(list(self.path.glob("attempt-*-started.json"))), 2)

    def test_pending_attempt_survives_crash_and_blocks_dispatch(self):
        event_id = self.start()
        self.r = recorder.Recorder(self.path, clock=lambda: self.now)
        with self.assertRaisesRegex(recorder.BudgetExhausted, "unfinished"):
            self.start("fetch")
        self.assertEqual(self.r.package()["pending_attempts"][0]["event_id"], event_id)
        self.r.complete(event_id, None, status="failed", error={"type": "Cancelled", "message": "unknown usage"})
        self.assertIsNone(self.r.package()["search_events"][0]["usage"]["cost"])
        self.start("fetch")

    def test_raw_order_text_provenance_and_capture_clock_are_preserved(self):
        event_id = self.start("fetch")
        source = self.source()
        payload = {"content": [{"type": "text", "text": "Header\n" + source["fields"]["text"]}],
                   "results": [{"rank": 2}, {"rank": 1}]}
        self.now = "2026-02-01T00:00:02Z"
        event = self.r.complete(event_id, payload, source=source)
        self.assertEqual(event["usage"]["elapsed_ms"], 2000)
        raw = self.path / event["response"]["snapshot"]["path"]
        self.assertEqual(json.loads(raw.read_text()), payload)
        payload["results"].reverse()
        package = self.r.package()
        observation = package["observations"][0]
        self.assertEqual(observation["available_at"], self.now)
        self.assertEqual(observation["fields"]["text"], source["fields"]["text"])
        self.assertEqual(observation["source_sha256"], replay.digest(observation["fields"]))
        self.assertEqual(package["search_events"][0]["response"]["payload"]["results"][0]["rank"], 2)
        self.assertEqual(package["search_events"][0]["response"]["source_metadata"]["completeness"], "excerpt")
        manifest = dict(schema_version=1, fixture_id="synthetic", chronology_mode="actual_observed",
                        observations=package["observations"], search_events=package["search_events"],
                        boundaries=[dict(prefix_id="before", day="2026-01-01", at=self.plan["cutoff"]),
                                    dict(prefix_id="after", day="2026-02-01", at=self.now)],
                        coverage={"scope": "Synthetic", "gaps": []})
        replay.validate_manifest(manifest)
        self.assertEqual(replay.prefix(manifest, manifest["boundaries"][0], True)["observations"], [])
        self.assertEqual(replay.prefix(manifest, manifest["boundaries"][1], False)["search_events"], [])
        self.assertEqual(len(replay.prefix(manifest, manifest["boundaries"][1], True)["observations"]), 1)

    def test_invalid_text_retains_payload_and_stops_next_dispatch(self):
        event = self.r.complete(self.start("fetch"), {"text": "actual"}, source=self.source("invented"))
        self.assertEqual(event["status"], "failed")
        self.assertEqual(json.loads((self.path / event["response"]["snapshot"]["path"]).read_text()), {"text": "actual"})
        self.assertEqual(self.r.package()["observations"], [])
        with self.assertRaisesRegex(recorder.BudgetExhausted, "stopped"):
            self.start()

    def test_search_cannot_mint_claim_evidence_and_tool_error_cannot_be_ok(self):
        event = self.r.complete(self.start(), {"text": "same"}, source=self.source("same"))
        self.assertEqual(event["observation_ids"], [])
        self.assertEqual(event["status"], "failed")

    def test_tool_error_preserved_and_block_consumes_fetch_budget(self):
        event = self.r.complete(self.start("fetch"), {"isError": True, "content": ["denied"]}, status="blocked")
        self.assertEqual(event["status"], "blocked")
        self.assertEqual(event["usage"]["tool_calls"], 1)
        self.assertIsNone(event["usage"]["model_tokens"])

    def test_non_json_result_records_capture_failure(self):
        event = self.r.complete(self.start(), object())
        self.assertTrue(event["response"]["capture_incomplete"])
        self.assertEqual(event["status"], "failed")
        self.assertIsNone(event["usage"]["model_tokens"])

    def test_attempt_cannot_be_completed_twice_or_directory_reused(self):
        event_id = self.start()
        self.r.complete(event_id, {"results": []}, status="empty")
        with self.assertRaisesRegex(ValueError, "already completed"):
            self.r.complete(event_id, {})
        with self.assertRaises(FileExistsError):
            recorder.Recorder(self.path, self.plan)

    def test_changed_snapshot_is_detected_before_next_dispatch(self):
        event = self.r.complete(self.start(), {"results": []}, status="empty")
        path = self.path / event["response"]["snapshot"]["path"]
        path.chmod(0o644)
        path.write_text("{}")
        with self.assertRaisesRegex(ValueError, "snapshot changed"):
            self.start()

    def test_cli_round_trip_preserves_full_return(self):
        request = Path(self.temp.name) / "request.json"
        payload = Path(self.temp.name) / "result.json"
        request.write_text(json.dumps({"query": "synthetic", "reason": "test"}))
        payload.write_text(json.dumps({"content": [{"text": "synthetic result"}], "metadata": {"all": True}}))
        command = [sys.executable, str(ROOT / "search_recorder.py")]
        start = json.loads(subprocess.check_output(command + ["begin", "--directory", str(self.path),
                          "--kind", "search", "--request", str(request)], text=True))
        subprocess.check_output(command + ["complete", "--directory", str(self.path), "--event-id",
                                start["event_id"], "--result", str(payload)], text=True)
        package = json.loads(subprocess.check_output(command + ["package", "--directory", str(self.path)], text=True))
        self.assertEqual(package["search_events"][0]["response"]["payload"], json.loads(payload.read_text()))


if __name__ == "__main__":
    unittest.main()
