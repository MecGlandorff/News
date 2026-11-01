"""Offline executable transport probes. No Codex or model is launched."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import codex_backend as cb
import model_adapters as ma
import replay


SCHEMA = ma.obj(ok={"type": "boolean"})
COMPLETE = {"type": "turn.completed", "usage": {"input_tokens": 12, "output_tokens": 7, "cached_input_tokens": 3}}


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plan = dict(schema_version=1, purpose="transport_probe", isolation=dict(status="limited", evidence="Offline fake executable"),
            schedule=[dict(call_id="p1", stage="probe", input_tokens=100, output_tokens=100, timeout_seconds=2),
                      dict(call_id="p2", stage="probe", input_tokens=100, output_tokens=100, timeout_seconds=2)],
            budget=dict(input_tokens=500, output_tokens=500, model_active_seconds=6, wall_seconds=10, max_failures=1))

    def fake(self, code):
        path = self.root / "fake.py"
        path.write_text("#!" + sys.executable + "\nimport json,sys,os,time,pathlib,signal\n" + code)
        path.chmod(0o700)
        return path

    def backend(self, code):
        self.backend_obj = cb.Backend(self.root / "run", self.plan, executable=self.fake(code))
        return self.backend_obj

    def success_code(self, output=None, events=None):
        return ("p=pathlib.Path(sys.argv[sys.argv.index('--output-last-message')+1])\n"
                "assert (p.parent/'request.json').exists()\n"
                "assert list(pathlib.Path.cwd().iterdir()) == []\n"
                "p.write_text(" + repr(json.dumps({"ok": True} if output is None else output)) + ")\n" +
                "print(" + repr("\n".join(json.dumps(x) for x in ([COMPLETE] if events is None else events))) + ", flush=True)\n")

    def test_success_durable_request_output_and_usage(self):
        backend = self.backend(self.success_code())
        response = backend.invoke("p1", "probe", "Literal $(not_shell) `no interpolation`", SCHEMA)
        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["usage"], dict(input_tokens=12, output_tokens=7))
        directory = self.root / "run/p1"
        for name in ("request.json", "prompt.txt", "schema.json", "stdout.jsonl", "stderr.txt", "last-message.txt", "response.json", "usage.json", "terminal.json"):
            self.assertTrue((directory / name).is_file(), name)
        request = json.loads((directory / "request.json").read_text())
        self.assertIn("gpt-6-astra", request["argv"])
        self.assertIn('model_reasoning_effort="medium"', request["argv"])
        self.assertNotIn("--ignore-rules", request["argv"])
        self.assertFalse(request["token_bounds_enforced"])

    def test_nonzero_exit_retains_known_usage(self):
        response = self.backend(self.success_code() + "sys.exit(4)\n").invoke("p1", "probe", "test", SCHEMA)
        self.assertEqual(response["usage"], dict(input_tokens=12, output_tokens=7))
        self.assertEqual(response["error"], "process_exit:4")

    def test_launch_failure_recorded_before_dispatch(self):
        backend = cb.Backend(self.root / "run", self.plan, executable=self.root / "absent")
        response = backend.invoke("p1", "probe", "test", SCHEMA)
        self.assertEqual(response["status"], "failed")
        self.assertIsNone(response["usage"]["input_tokens"])
        self.assertTrue((self.root / "run/p1/request.json").exists())
        self.assertTrue((self.root / "run/p1/terminal.json").exists())

    def test_missing_partial_bool_and_multiple_usage_stop(self):
        cases = [[], [{"type": "turn.completed", "usage": {"input_tokens": 4}}],
                 [{"type": "turn.completed", "usage": {"input_tokens": True, "output_tokens": 7}}], [COMPLETE, COMPLETE]]
        for index, events in enumerate(cases):
            with self.subTest(events=events):
                fake = self.root / ("fake" + str(index))
                fake.write_text("#!" + sys.executable + "\nimport sys,pathlib\n" + self.success_code(events=events))
                fake.chmod(0o700)
                backend = cb.Backend(self.root / ("run" + str(index)), self.plan, fake)
                result = backend.invoke("p1", "probe", "test", SCHEMA)
                self.assertEqual(result["status"], "failed")
                self.assertEqual(backend.stopped, "unknown_usage")
                with self.assertRaisesRegex(RuntimeError, "stopped"):
                    backend.invoke("p2", "probe", "test", SCHEMA)

    def test_tool_event_kills_process_and_stops(self):
        code = "print(json.dumps({'type':'item.started','item':{'type':'command_execution'}}),flush=True)\ntime.sleep(20)\n"
        started = time.monotonic()
        backend = self.backend(code)
        result = backend.invoke("p1", "probe", "test", SCHEMA)
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertEqual(result["error"], "forbidden_or_unknown_event")
        self.assertEqual(backend.stopped, "isolation_event_failure")

    def test_emitted_transport_error_stops_without_waiting_for_retry(self):
        code = "print(json.dumps({'type':'error','message':'Reconnecting 1/5'}),flush=True)\ntime.sleep(20)\n"
        started = time.monotonic()
        backend = self.backend(code)
        result = backend.invoke("p1", "probe", "test", SCHEMA)
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertEqual(result["error"], "backend_error_event")
        self.assertEqual(backend.stopped, "unknown_usage")

    def test_timeout_terminates_descendant_process_group(self):
        marker = self.root / "descendant-finished"
        self.plan["schedule"][0]["timeout_seconds"] = .2
        code = "child=os.fork()\nif child == 0:\n time.sleep(1)\n pathlib.Path(" + repr(str(marker)) + ").write_text('escaped')\n os._exit(0)\ntime.sleep(10)\n"
        backend = self.backend(code)
        result = backend.invoke("p1", "probe", "test", SCHEMA)
        self.assertEqual(result["error"], "process_timeout")
        time.sleep(1)
        self.assertFalse(marker.exists())

    def test_malformed_stream_and_output_fail(self):
        for index, code in enumerate(["print('not json',flush=True)\n", self.success_code(output={"ok": "wrong"})]):
            executable = self.root / ("fake" + str(index))
            executable.write_text("#!" + sys.executable + "\nimport pathlib,sys\n" + code)
            executable.chmod(0o700)
            result = cb.Backend(self.root / ("run" + str(index)), self.plan, executable).invoke("p1", "probe", "test", SCHEMA)
            self.assertEqual(result["status"], "failed")

    def test_overshoot_and_reservation_stop(self):
        self.plan["schedule"][0]["output_tokens"] = 6
        backend = self.backend(self.success_code())
        self.assertEqual(backend.invoke("p1", "probe", "test", SCHEMA)["status"], "failed")
        self.assertEqual(backend.stopped, "token_threshold_overshoot")
        with self.assertRaises(RuntimeError):
            backend.invoke("p2", "probe", "test", SCHEMA)

    def test_schedule_nonoverwrite_and_isolation_gate(self):
        backend = self.backend(self.success_code())
        with self.assertRaises(ValueError):
            backend.invoke("p2", "probe", "test", SCHEMA)
        with self.assertRaises(FileExistsError):
            cb.Backend(self.root / "run", self.plan)
        self.plan["purpose"] = "candidate"
        with self.assertRaisesRegex(ValueError, "isolation"):
            cb.Backend(self.root / "candidate", self.plan)

    def protocol_events(self):
        path = Path(__file__).resolve().parents[1] / "protocol-fixtures/codex-0.164.0-disabled-host.jsonl"
        metadata = json.loads(path.with_suffix(".json").read_text())
        self.assertEqual(cb.hashlib.sha256(path.read_bytes()).hexdigest(), metadata["stdout_sha256"])
        return [json.loads(line) for line in path.read_text().splitlines()]

    def test_real_protocol_fixture_is_classified_and_rejected_by_default(self):
        events = self.protocol_events()
        self.assertEqual(events[1], cb.DISABLED_HOST_EVENT)
        backend = self.backend(self.success_code(events=events + [COMPLETE]))
        result = backend.invoke("p1", "probe", "test", SCHEMA)
        self.assertEqual(result["error"], "disabled_code_mode_startup")
        self.assertEqual(backend.stopped, "unknown_usage")
        diagnostic = json.loads((self.root / "run/p1/diagnostics.json").read_text())
        self.assertFalse(diagnostic["diagnostics"][0]["continued"])

    def test_opt_in_pinned_fake_continuation_records_diagnostic_and_usage(self):
        self.plan["startup_diagnostic_policy"] = cb.STARTUP_POLICY
        executable = self.fake(self.success_code(events=self.protocol_events() + [COMPLETE]))
        # Substitute only the executable pin for this explicitly offline protocol test.
        # The fake continuation is not evidence of live CLI acknowledgement success.
        with patch.object(cb, "STARTUP_EXECUTABLE_SHA256", cb.hashlib.sha256(executable.read_bytes()).hexdigest()):
            backend = cb.Backend(self.root / "run", self.plan, executable)
            result = backend.invoke("p1", "probe", "test", SCHEMA)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["usage"], dict(input_tokens=12, output_tokens=7))
        diagnostic = json.loads((self.root / "run/p1/diagnostics.json").read_text())
        self.assertEqual(diagnostic["policy"], cb.STARTUP_POLICY)
        self.assertTrue(diagnostic["diagnostics"][0]["continued"])
        self.assertEqual(backend.calls, 1)

    def test_startup_policy_rejects_unpinned_binary_and_source_bearing_purpose(self):
        self.plan["startup_diagnostic_policy"] = cb.STARTUP_POLICY
        executable = self.fake(self.success_code())
        with self.assertRaisesRegex(ValueError, "exact recorded CLI"):
            cb.Backend(self.root / "run", self.plan, executable)
        self.plan["purpose"] = "synthetic_diagnostic"
        with self.assertRaisesRegex(ValueError, "source-free"):
            cb.Backend(self.root / "source-bearing", self.plan, executable)

    def test_startup_exception_rejects_late_duplicate_changed_and_tool_events(self):
        thread, diagnostic, turn = self.protocol_events()
        changed = copy.deepcopy(diagnostic)
        changed["item"]["message"] += " "
        extra = copy.deepcopy(diagnostic)
        extra["item"]["command"] = "unexpected"
        for sequence, expected in [
                ([thread, turn, diagnostic], "unexpected_disabled_code_mode_startup"),
                ([thread, diagnostic, diagnostic], "unexpected_disabled_code_mode_startup"),
                ([thread, changed], "backend_error_item"), ([thread, extra], "backend_error_item"),
                ([thread, {"type": "error", "message": diagnostic["item"]["message"]}], "backend_error_event"),
                ([thread, {"type": "item.started", "item": {"type": "command_execution"}}], "forbidden_or_unknown_event")]:
            with self.subTest(sequence=sequence):
                gate = cb.EventGate(allow_disabled_host=True)
                results = [gate.inspect(event) for event in sequence]
                self.assertEqual(results[-1], expected)

    def test_allowlisted_diagnostic_does_not_make_unknown_usage_free(self):
        self.plan["startup_diagnostic_policy"] = cb.STARTUP_POLICY
        executable = self.fake(self.success_code(events=self.protocol_events()))
        with patch.object(cb, "STARTUP_EXECUTABLE_SHA256", cb.hashlib.sha256(executable.read_bytes()).hexdigest()):
            backend = cb.Backend(self.root / "run", self.plan, executable)
            result = backend.invoke("p1", "probe", "test", SCHEMA)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["usage"], dict(input_tokens=None, output_tokens=None))
        self.assertEqual(backend.stopped, "unknown_usage")


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.row = dict(observation_id="o1", source_version_id="v1", fields={"text": "A fact."},
            observed_at="2026-01-01T12:00:00Z", available_at="2026-01-01T12:00:00Z", published_at_utc=None)
        self.row["source_sha256"] = replay.digest(self.row["fields"])
        self.context = dict(prefix_id="p1", day="2026-01-01", at=self.row["available_at"], chronology_mode="synthetic_stress",
            observations=[self.row], coverage=dict(scope="test", gaps=[]))
        self.extraction = dict(schema_version=1, source_version_id="v1", facts=[dict(id="f1", claim="A fact.", attribution="Source",
            source_spans=[dict(source_version_id="v1", field="text", start=0, end=7, quote="A fact.")], uncertainty=[])], status="processed", reason=None)
        self.calls = []
        class Stub:
            def invoke(inner, call_id, stage, text, schema, validate=None):
                self.calls.append((stage, text))
                value = self.extraction if stage == "E_extract" else dict(schema_version=1, contributions=[], relations=[],
                    source_accounting=[dict(observation_id="o1", status="unassigned", contribution_ids=[], reason="Insufficient")],
                    deltas=[], questions=[], analysis=[], repair=dict(reason=None, supersedes=None))
                if validate:
                    validate(value)
                return dict(status="ok", output=value, usage=dict(input_tokens=2, output_tokens=3), error=None)
        self.backend = Stub()

    def test_extraction_source_local_and_repeated_version_artifact(self):
        row = dict(self.row, labels="must not be sent", future_source="secret")
        result = ma.extract(self.backend, "e1", row)
        self.assertNotIn("must not be sent", self.calls[0][1])
        self.assertNotIn("secret", self.calls[0][1])
        self.assertNotIn("o1", self.calls[0][1])
        context = copy.deepcopy(self.context)
        context["observations"].append(dict(self.row, observation_id="o2"))
        artifact = ma.extraction_artifact(context, {"v1": result, "future": "excluded"})
        self.assertEqual(set(artifact["payload"]), {"v1"})
        replay.validate_artifacts({"extraction": artifact}, context, "E")

    def test_prior_state_and_future_source_blocked(self):
        for addition in ({"prior_state": {}}, {"previous_published": {}}, {"labels": {}}):
            with self.assertRaises(ValueError):
                ma.reconstruct(self.backend, "d1", dict(self.context, **addition))
        context = copy.deepcopy(self.context)
        context["observations"][0]["available_at"] = "2026-01-02T12:00:00Z"
        with self.assertRaisesRegex(ValueError, "Future"):
            ma.reconstruct(self.backend, "d1", context)
        self.assertEqual(self.calls, [])

    def test_wrong_extraction_quote_and_recipe_rejected(self):
        result = ma.extract(self.backend, "e1", self.row)
        artifact = ma.extraction_artifact(self.context, {"v1": result})
        artifact["payload"]["v1"]["facts"][0]["source_spans"][0]["quote"] = "Wrong"
        with self.assertRaisesRegex(ValueError, "quote"):
            ma.reconstruct(self.backend, "e2", self.context, "E", artifact)
        artifact["recipe_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "recipe"):
            ma.reconstruct(self.backend, "e2", self.context, "E", artifact)


if __name__ == "__main__":
    unittest.main()
