"""Pinned driver probes using a fake executable only, including independent arm failure."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import codex_backend as cb
import model_adapters as ma
import replay
import trial_driver as td


class DriverTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[2]
        (self.root / ".news").mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=self.root / ".news", prefix="driver-test-")
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.pins = list(td.CODE)
        self.fake = self.folder / "fake.py"
        self.fake.write_text("#!" + sys.executable + '''
import json,pathlib,sys
p=pathlib.Path(sys.argv[sys.argv.index('--output-last-message')+1])
request=json.loads((p.parent/'request.json').read_text())
stage=request['stage']
if stage=='probe': result={'ack':'ok'}
elif stage=='D': result={'bad':'intentional schema failure'}
elif stage=='E_extract':
 source=json.loads(request['prompt'].split('UNTRUSTED INPUT JSON:\\n')[1])
 result={'schema_version':1,'source_version_id':source['source_version_id'],'facts':[], 'status':'unassigned','reason':'Empty'}
elif stage=='E':
 source=json.loads(request['prompt'].split('UNTRUSTED INPUT JSON:\\n')[1])
 result={'schema_version':1,'contributions':[],'relations':[],'source_accounting':[{'observation_id':s['observation_id'],'status':'unassigned','contribution_ids':[],'reason':'Empty'} for s in source['observations']], 'deltas':[],'questions':[],'analysis':[],'repair':{'reason':None,'supersedes':None}}
else: result={'deltas':[]}
p.write_text(json.dumps(result))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':5,'output_tokens':3}}),flush=True)
''')
        self.fake.chmod(0o700)
        self.review = self.write("review.json", {"status": "offline test review fixture"})

    def write(self, name, value):
        path = self.folder / name
        path.write_text(json.dumps(value))
        relative = str(path.relative_to(self.root))
        self.pins.append(relative)
        return relative

    def slot(self, call_id, stage):
        return dict(call_id=call_id, stage=stage, input_tokens=100, output_tokens=100, timeout_seconds=2)

    def backend(self, name, purpose, schedule):
        return self.write(name, dict(schema_version=1, purpose=purpose, isolation=dict(status="limited", evidence="Invented offline fixture"),
            schedule=schedule, budget=dict(input_tokens=1000, output_tokens=1000, model_active_seconds=20, wall_seconds=30, max_failures=1)))

    def capsule(self, phase, plan, source=None, previous=None):
        value = dict(schema_version=1, phase=phase, phase_plan=plan, source=source, schemas=td.schemas(),
            executable=dict(path=str(self.fake), sha256=td.sha(self.fake), version="offline-fake-v1"), review_record=self.review,
            prior_runs=[] if previous is None else [dict(path=str(previous), sha256=td.sha(previous))],
            files=[dict(path=name, sha256=td.sha(self.root / name)) for name in self.pins])
        path = self.folder / (phase + "-capsule.json")
        path.write_text(json.dumps(value))
        return path

    def preflight(self):
        backend = self.backend("probe-backend.json", "transport_probe", [self.slot("p1", "probe"), self.slot("p2", "probe")])
        schema = ma.obj(ack=dict(type="string", enum=["ok"]))
        inputs = [self.write("probe" + str(i) + ".json", dict(call_id="p" + str(i), prompt="Say ok", response_schema=schema, expected_output={"ack": "ok"})) for i in (1, 2)]
        plan = self.write("preflight-plan.json", dict(schema_version=1, phase="preflight", backend_plans={"preflight": backend}, inputs=inputs))
        path = self.capsule("preflight", plan)
        report = td.run(path, self.root, self.folder / "preflight-output")
        return report, self.folder / "preflight-output/report.json"

    def synthetic(self, previous):
        t = "2026-01-01T00:00:00Z"
        fields = {"text": ""}
        source = self.write("source.json", dict(schema_version=1, fixture_id="invented", chronology_mode="synthetic_stress",
            observations=[dict(observation_id="o1", source_version_id="v1", source_sha256=replay.digest(fields), fields=fields, observed_at=t, published_at_utc=t, available_at=t)],
            boundaries=[dict(prefix_id="p1", day="2026-01-01", at=t)], coverage=dict(scope="Invented source", gaps=[])))
        d = self.backend("D.json", "synthetic_diagnostic", [self.slot("D1", "D"), self.slot("Dd1", "delta")])
        e = self.backend("E.json", "synthetic_diagnostic", [self.slot("ex1", "E_extract"), self.slot("E1", "E"), self.slot("Ed1", "delta")])
        order = [dict(arm=arm, call_id=call_id, stage=stage, prefix_id="p1", source_version_id="v1" if stage == "E_extract" else None)
                 for arm, call_id, stage in (("D", "D1", "D"), ("D", "Dd1", "delta"), ("E", "ex1", "E_extract"), ("E", "E1", "E"), ("E", "Ed1", "delta"))]
        plan = self.write("synthetic-plan.json", dict(schema_version=1, phase="synthetic", backend_plans={"D": d, "E": e}, order=order))
        return self.capsule("synthetic", plan, source, previous)

    def test_preflight_unused_reserve_and_independent_arm_failure(self):
        probe, previous = self.preflight()
        self.assertEqual(probe["actual"]["calls"], 1)
        self.assertEqual(probe["slots"][1]["status"], "unused")
        path = self.synthetic(previous)
        result = td.run(path, self.root, self.folder / "synthetic-output")
        self.assertEqual([s["status"] for s in result["slots"]], ["failed", "pending", "ok", "ok", "ok"])
        self.assertEqual(result["actual"]["calls"], 4)
        self.assertEqual(result["combined"]["calls"], 5)
        self.assertEqual(result["clock_origin"], probe["clock_origin"])
        self.assertFalse((self.folder / "synthetic-output/backends/D/Dd1").exists())

    def test_changed_frozen_input_rejected_before_dispatch(self):
        _, previous = self.preflight()
        path = self.synthetic(previous)
        (self.folder / "source.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "Changed frozen"):
            td.run(path, self.root, self.folder / "changed")
        self.assertFalse((self.folder / "changed").exists())

    def test_started_only_prior_attempt_blocks_following_phase(self):
        _, previous = self.preflight()
        path = self.synthetic(previous)
        added = previous.parent / "backends/preflight/unrecorded"
        added.mkdir()
        (added / "request.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "Incomplete prior"):
            td.run(path, self.root, self.folder / "incomplete")

    def test_unknown_usage_stops_otherwise_independent_arm(self):
        _, previous = self.preflight()
        self.fake.write_text(self.fake.read_text().replace("'input_tokens':5", "'input_tokens':None if stage=='D' else 5"))
        path = self.synthetic(previous)
        report = td.run(path, self.root, self.folder / "unknown")
        self.assertEqual(report["actual"]["calls"], 1)
        self.assertEqual(report["global_stop"], "unknown_usage")
        self.assertEqual([s["status"] for s in report["slots"]], ["failed", "pending", "pending", "pending", "pending"])

    def test_changed_prior_terminal_usage_cannot_reset_ledger(self):
        _, previous = self.preflight()
        path = self.synthetic(previous)
        terminal = previous.parent / "backends/preflight/p1/terminal.json"
        value = json.loads(terminal.read_text())
        value["response"]["usage"]["input_tokens"] = 0
        terminal.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "Prior call record changed"):
            td.run(path, self.root, self.folder / "tampered")

    def test_synthetic_purpose_rejects_search_and_natural_candidate_stays_gated(self):
        plan = json.loads((self.root / self.backend("bad.json", "synthetic_diagnostic", [self.slot("search", "search_plan")])).read_text())
        with self.assertRaisesRegex(ValueError, "cannot search"):
            cb.Backend(self.folder / "bad-output", plan)
        plan["purpose"] = "candidate"
        with self.assertRaisesRegex(ValueError, "isolation"):
            cb.Backend(self.folder / "natural-output", plan)

    def test_wrapper_bridge_keeps_unknown_usage_and_original_clock(self):
        self.fake.write_text(self.fake.read_text().replace("'input_tokens':5", "'input_tokens':None"))
        report, previous = self.preflight()
        folder = previous.parent
        terminal = json.loads((folder / "backends/preflight/p1/terminal.json").read_text())
        summary = dict(phase="preflight", application_invocations=1, ledger=str(folder / "backends/preflight"),
            reported_usage=terminal["response"]["usage"], status="failed", expected_output_match=False,
            started_at=report["clock_origin"], global_stop="unknown_usage")
        (folder / "phase-summary.json").write_text(json.dumps(summary))
        (folder / "trial-start.json").write_text(json.dumps(dict(started_at=report["clock_origin"])))
        (folder / "preflight-execution-v1.json").write_text("{}")
        before = (folder / "phase-summary.json").read_bytes()
        path = folder / "bridge.json"
        result = td.bridge_preflight(folder / "phase-summary.json", path)
        self.assertEqual(result["global_stop"], "unknown_usage")
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["clock_origin"], report["clock_origin"])
        self.assertEqual((folder / "phase-summary.json").read_bytes(), before)
        capsule = self.synthetic(path)
        with self.assertRaisesRegex(ValueError, "Successful preflight"):
            td.run(capsule, self.root, self.folder / "blocked")


if __name__ == "__main__":
    unittest.main()
