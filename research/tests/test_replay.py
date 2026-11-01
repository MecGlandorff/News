"""Behavior probes for offline mechanics; these are not semantic model tests."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("replay", Path(__file__).resolve().parents[1] / "replay.py")
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)


def source(number, at, text="One fact."):
    fields = {"title": "Synthetic source", "text": text}
    return {"observation_id": f"o{number}", "source_version_id": f"v{number}", "fields": fields,
            "source_sha256": replay.digest(fields), "available_at": at, "observed_at": at, "published_at_utc": at}


def output(context):
    result = dict(schema_version=1, contributions=[], relations=[], source_accounting=[], deltas=[],
                  questions=[], analysis=[], repair={"reason": None, "supersedes": None})
    for row in context["observations"]:
        text, ref = row["fields"].get("text", ""), row["observation_id"]
        contribution_ids = []
        if text:
            contribution_ids.append("c-" + ref)
            result["contributions"].append(dict(id="c-" + ref, kind="context_only", claim=text,
                attribution="Synthetic source", occurrence_id=None, story_id=None, uncertainty=[],
                source_spans=[dict(observation_id=ref, source_version_id=row["source_version_id"], field="text", start=0, end=len(text), quote=text)]))
        result["source_accounting"].append(dict(observation_id=ref, status="processed" if text else "unassigned",
                                              contribution_ids=contribution_ids, reason=None if text else "Insufficient text"))
    return result


def response(value, usage=None):
    return dict(status="ok", output=value, usage=usage or dict(input_tokens=2, output_tokens=3), error=None)


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root, self.counter = Path(self.temp.name), 0
        self.t1, self.t2 = "2026-01-01T12:00:00Z", "2026-01-02T12:00:00Z"
        self.manifest = dict(schema_version=1, fixture_id="tiny-v1", chronology_mode="synthetic_stress",
            observations=[source(1, self.t1), source(2, self.t2, "")],
            boundaries=[dict(prefix_id="p1", day="2026-01-01", at=self.t1), dict(prefix_id="p2", day="2026-01-02", at=self.t2)],
            coverage=dict(scope="Synthetic incomplete stream", gaps=[dict(**{"from": "2026-01-02", "to": "2026-01-05"}, reason="Not observed")]))
        self.plan = dict(schema_version=1, arm="D", implementation_id="test-stub-v1", enrichment=False, delta_comparison=False,
            budget=dict(calls=10, tokens=1000, seconds=30, tool_calls=10, recovery_calls=2), per_call_tokens=100, recovery_prefixes=[])

    def run_replay(self, candidate=None, **kwargs):
        self.counter += 1
        self.path = self.root / str(self.counter)
        return replay.run(self.manifest, self.plan, candidate or (lambda context: response(output(context))), self.path, **kwargs)

    def context(self, number=0):
        return replay.prefix(self.manifest, self.manifest["boundaries"][number])

    def artifacts(self, arm):
        kinds = ["extraction", "index"] if arm == "R" else ["extraction"]
        return {boundary["prefix_id"]: {kind: dict(kind=kind, version="v1", cutoff=boundary["at"], source_only=True,
            source_versions={row["source_version_id"]: row["source_sha256"] for row in replay.prefix(self.manifest, boundary)["observations"]},
            recipe_sha256=replay.digest("frozen source-only recipe"), payload={"contributions": []}) for kind in kinds}
            for boundary in self.manifest["boundaries"]}

    def test_cumulative_boundary_and_coverage_gaps_do_not_leak_future(self):
        seen = []
        def candidate(context):
            seen.append(copy.deepcopy(context))
            return response(output(context))
        report = self.run_replay(candidate)
        self.assertEqual(report["status"], "completed")
        self.assertEqual([[x["observation_id"] for x in c["observations"]] for c in seen], [["o1"], ["o1", "o2"]])
        self.assertEqual(seen[0]["coverage"]["gaps"], [])
        self.assertEqual(seen[1]["coverage"]["gaps"][0]["to"], "2026-01-02")
        self.assertNotIn("fixture_id", seen[0])
        self.assertEqual(report["prefixes"][1]["source_accounting"][1]["status"], "unassigned")

    def test_sources_and_historical_outputs_are_immutable_under_callable_mutation(self):
        original = copy.deepcopy(self.manifest)
        def candidate(context):
            value = output(context)
            context["observations"][0]["fields"]["text"] = "changed"
            return response(value)
        report = self.run_replay(candidate)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(self.manifest, original)
        self.assertEqual(json.loads((self.path / "inputs.json").read_text())["manifest"], original)
        self.assertNotEqual(report["history"][0]["version"], report["history"][1]["version"])
        before = (self.path / "view-0001.json").read_bytes()
        with self.assertRaises(FileExistsError):
            replay.run(self.manifest, self.plan, candidate, self.path)
        self.assertEqual(before, (self.path / "view-0001.json").read_bytes())

    def test_complete_recording_is_frozen_and_exhaustion_is_visible(self):
        responses = [response(output(self.context()))]
        path = self.root / "recorded"
        report = replay.run(self.manifest, self.plan, None, path, recorded_responses=responses)
        frozen = json.loads((path / "inputs.json").read_text())
        self.assertEqual(frozen["recorded_responses"], responses)
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["accounting"]["unknown_usage_calls"], 1)
        self.assertIn("StopIteration", report["calls"][1]["error"])

    def test_zero_many_contributions_and_possible_relationship_are_expressible(self):
        value = output(self.context())
        second = copy.deepcopy(value["contributions"][0])
        second.update(id="second", occurrence_id="occurrence-2", story_id="story-2")
        value["contributions"][0].update(occurrence_id="occurrence-1", story_id="story-1")
        value["contributions"].append(second)
        value["source_accounting"][0]["contribution_ids"].append("second")
        value["relations"] = [dict(**{"from": "occurrence-1", "to": "story-2"}, type="membership", status="possible", source_spans=second["source_spans"])]
        value["analysis"] = [dict(text="A possible implication.", evidence_contribution_ids=["second"])]
        replay.validate_output(value, self.context())
        self.assertEqual(value["relations"][0]["status"], "possible")
        value["analysis"][0]["accepted_memberships"] = ["occurrence-1"]
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            replay.validate_output(value, self.context())

    def test_hidden_incomplete_coverage_and_span_revision_are_rejected(self):
        context = self.context(1)
        for mutate, message in [
            (lambda value: value["source_accounting"].pop(), "Incomplete"),
            (lambda value: value["contributions"][0]["source_spans"][0].update(observation_id="future"), "Future"),
            (lambda value: value["contributions"][0]["source_spans"][0].update(source_version_id="later"), "version"),
            (lambda value: value["contributions"][0]["source_spans"][0].update(quote="fabricated"), "quote"),
            (lambda value: value["source_accounting"][0].update(contribution_ids=[]), "accounting")]:
            with self.subTest(message=message):
                value = output(context)
                mutate(value)
                with self.assertRaisesRegex(ValueError, message):
                    replay.validate_output(value, context)

    def test_source_hash_version_clock_and_grouping_tampering_fail(self):
        changes = [lambda m: m["observations"][0]["fields"].update(text="tampered"),
                   lambda m: m["observations"][1].update(source_version_id="v1"),
                   lambda m: m["observations"][0].update(case_id="secret grouping"),
                   lambda m: m["boundaries"].reverse(),
                   lambda m: m["boundaries"][0].update(day="2026-01-02"),
                   lambda m: m["observations"][0].update(available_at="2026-01-01T12:00:00"),
                   lambda m: m.update(chronology_mode="actual_observed", observations=[dict(m["observations"][0], observed_at=self.t2)])]
        for mutate in changes:
            manifest = copy.deepcopy(self.manifest)
            mutate(manifest)
            with self.subTest(manifest=manifest), self.assertRaises(ValueError):
                replay.validate_manifest(manifest)

    def test_repeat_observation_preserves_version_and_own_accounting(self):
        self.manifest["observations"][1] = dict(self.manifest["observations"][0], observation_id="o2", available_at=self.t2, observed_at=self.t2)
        report = self.run_replay()
        self.assertEqual(report["status"], "completed")
        self.assertEqual(len(report["prefixes"][1]["source_accounting"]), 2)

    def test_malformed_output_is_preserved_and_does_not_activate_stale_success(self):
        def candidate(context):
            return response(output(context) if context["prefix_id"] == "p1" else {"broken": "retain me"})
        report = self.run_replay(candidate)
        self.assertEqual(report["status"], "incomplete")
        self.assertIsNone(report["active"])
        self.assertEqual(report["history"][1]["output"], {"broken": "retain me"})
        self.assertEqual(json.loads((self.path / "call-0002.json").read_text())["response"]["output"], {"broken": "retain me"})
        self.assertEqual(report["prefixes"][1]["source_accounting"][0]["status"], "pending")
        self.assertEqual(report["accounting"]["known_tokens"], 10)

    def test_predeclared_recovery_keeps_failure_and_consumes_both_calls(self):
        self.plan["recovery_prefixes"] = ["p1"]
        def candidate(context):
            return response({"broken": True} if context["prefix_id"] == "p1" and not context["recovery"] else output(context))
        report = self.run_replay(candidate)
        self.assertEqual(report["status"], "completed")
        self.assertEqual([row["status"] for row in report["history"]], ["failed", "success", "success"])
        self.assertEqual(report["accounting"]["recovery_calls"], 1)
        self.assertEqual(report["accounting"]["calls"], 3)

    def test_unknown_usage_and_exception_stop_further_calls_even_with_recovery(self):
        self.plan["recovery_prefixes"] = ["p1"]
        def exception(context):
            raise RuntimeError("offline failure")
        for candidate in [lambda c: response(output(c), dict(input_tokens=2, output_tokens=None)), exception,
                          lambda c: [], lambda c: {"usage": {"input_tokens": "bad", "output_tokens": 1}}]:
            with self.subTest(candidate=candidate):
                report = self.run_replay(candidate)
                self.assertEqual(report["accounting"]["calls"], 1)
                self.assertEqual(report["accounting"]["unknown_usage_calls"], 1)
                self.assertIsNone(report["active"])
                self.assertEqual(report["prefixes"][1]["status"], "budget_stopped")

    def test_bad_envelope_still_charges_valid_usage(self):
        report = self.run_replay(lambda c: {"usage": dict(input_tokens=8, output_tokens=9), "wrong": True})
        self.assertEqual(report["accounting"]["known_tokens"], 34)
        self.assertEqual(report["accounting"]["unknown_usage_calls"], 0)

    def test_finite_call_token_runtime_and_recovery_limits(self):
        for budget_key, limit, expected_calls in [("calls", 1, 1), ("tokens", 99, 0), ("seconds", 0, 0)]:
            with self.subTest(budget_key=budget_key):
                plan = copy.deepcopy(self.plan)
                self.plan["budget"][budget_key] = limit
                report = self.run_replay()
                self.assertEqual(report["accounting"]["calls"], expected_calls)
                self.assertEqual(report["status"], "incomplete")
                self.assertIsNone(report["active"])
                self.plan = plan
        self.plan["recovery_prefixes"] = ["p1"]
        self.plan["budget"]["recovery_calls"] = 0
        report = self.run_replay(lambda c: response({}))
        self.assertEqual(report["accounting"]["calls"], 2)
        self.assertEqual(report["accounting"]["recovery_calls"], 0)

    def test_token_overshoot_is_recorded_and_rejected(self):
        report = self.run_replay(lambda c: response(output(c), dict(input_tokens=70, output_tokens=50)))
        self.assertEqual(report["accounting"]["known_tokens"], 120)
        self.assertEqual(report["accounting"]["calls"], 1)
        self.assertEqual(report["prefixes"][0]["error"], "token_overshoot")

    def test_partial_usage_is_known_component_and_unknown_total(self):
        report = self.run_replay(lambda c: response(output(c), dict(input_tokens=7, output_tokens=None)))
        self.assertEqual(report["accounting"]["known_tokens"], 7)
        self.assertIsNone(report["accounting"]["total_tokens"])

    def test_started_attempt_survives_interrupt_and_usage_remains_unknown(self):
        def interrupt(context):
            started = json.loads((self.path / "call-0001-started.json").read_text())
            self.assertEqual(started["status"], "started")
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.run_replay(interrupt)
        report = json.loads((self.path / "report.json").read_text())
        self.assertEqual(report["status"], "interrupted")
        self.assertEqual(report["accounting"]["calls"], 1)
        self.assertEqual(report["accounting"]["unknown_usage_calls"], 1)
        self.assertIsNone(report["active"])
        self.assertEqual(json.loads((self.path / "call-0001.json").read_text())["status"], "interrupted")

    def test_non_json_response_has_diagnostic_and_valid_usage_still_counts(self):
        for invalid in (float("nan"), object()):
            report = self.run_replay(lambda c: response({"invalid": invalid}))
            self.assertEqual(report["status"], "incomplete")
            self.assertEqual(report["accounting"]["known_tokens"], 10)
            self.assertEqual(report["accounting"]["unknown_usage_calls"], 0)
            self.assertIn("response_diagnostic", report["calls"][0])
            self.assertIn("non-JSON", report["calls"][0]["error"])

    def test_recovery_counts_only_actual_dispatch_including_comparison(self):
        self.plan["recovery_prefixes"] = ["p1"]
        self.plan["budget"]["calls"] = 1
        blocked = self.run_replay(lambda c: response({}))
        self.assertEqual(blocked["accounting"]["recovery_calls"], 0)
        self.plan["budget"]["calls"] = 10
        self.plan["delta_comparison"] = True
        def candidate(context):
            return response({} if context["prefix_id"] == "p1" and not context["recovery"] else output(context))
        recovered = self.run_replay(candidate, delta_compare=lambda c: response({"deltas": []}))
        self.assertEqual(recovered["status"], "completed")
        self.assertEqual(recovered["accounting"]["recovery_calls"], 2)

    def test_json_container_types_and_boolean_integer_aliases_are_rejected(self):
        for key in ("relations", "analysis", "deltas", "questions"):
            value = output(self.context())
            value[key] = {}
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "arrays"):
                replay.validate_output(value, self.context())
        for mutate in [lambda value: value.update(schema_version=True),
                       lambda value: value["source_accounting"][0].update(contribution_ids="c-o1"),
                       lambda value: value.update(deltas=[dict(kind="new_occurrence", contribution_ids="c-o1")]),
                       lambda value: value.update(analysis=[dict(text="text", evidence_contribution_ids="c-o1")])]:
            value = output(self.context())
            mutate(value)
            with self.assertRaises(ValueError):
                replay.validate_output(value, self.context())
        self.manifest["schema_version"] = True
        self.assertEqual(self.run_replay()["status"], "invalid")
        self.manifest["schema_version"] = 1
        self.plan["schema_version"] = True
        self.assertEqual(self.run_replay()["status"], "invalid")
        self.plan["schema_version"] = 1
        self.add_search()
        self.manifest["search_events"][0]["usage"]["tool_calls"] = True
        self.assertEqual(self.run_replay()["status"], "invalid")

    def test_material_question_opening_is_representable_without_semantic_judgment(self):
        value = output(self.context())
        value["contributions"][0]["kind"] = "question_opened"
        value["deltas"] = [dict(kind="question_opened", contribution_ids=["c-o1"])]
        replay.validate_output(value, self.context())

    def test_reconstruction_arms_never_receive_prior_interpretations(self):
        contaminated = output(self.context())
        contaminated["contributions"][0]["story_id"] = "wrong-but-structurally-valid"
        for arm in ("D", "E", "R"):
            self.plan["arm"] = arm
            artifacts = {} if arm == "D" else self.artifacts(arm)
            seen = []
            def candidate(context):
                seen.append(copy.deepcopy(context))
                return response(output(context))
            seeded = self.run_replay(candidate, initial_state=contaminated, artifacts=artifacts)
            clean = self.run_replay(candidate, artifacts=artifacts)
            self.assertEqual(seeded["history"][0]["output"], clean["history"][0]["output"])
            self.assertTrue(all("prior_state" not in context for context in seen))
            self.assertIsNotNone(seeded["history"][0]["supersedes"])

    def test_incremental_receives_only_versioned_seed_and_can_replace_it(self):
        self.plan["arm"] = "I"
        contaminated = output(self.context())
        contaminated["contributions"][0]["story_id"] = "wrong-but-structurally-valid"
        seen = []
        def candidate(context):
            seen.append(context["prior_state"])
            value = output(context)
            value["repair"] = dict(reason="Scripted reconstruction probe", supersedes=context["prior_state"]["version"])
            return response(value)
        report = self.run_replay(candidate, initial_state=contaminated, artifacts=self.artifacts("I"))
        self.assertEqual(report["status"], "completed")
        self.assertEqual(set(seen[0]), {"version", "at", "output", "origin"})
        self.assertEqual(seen[0]["output"], contaminated)
        self.assertIsNone(report["history"][0]["output"]["contributions"][0]["story_id"])
        self.assertEqual(report["history"][0]["output"]["deltas"], [])
        self.assertEqual(seen[1]["version"], report["history"][0]["version"])

    def test_future_seed_and_future_or_incomplete_source_artifacts_never_reach_candidate(self):
        future_seed = output(self.context(1))
        self.assertEqual(self.run_replay(initial_state=future_seed)["status"], "invalid")
        self.plan["arm"] = "R"
        for mutation in [lambda a: a["p1"]["index"].update(cutoff=self.t2),
                         lambda a: a["p1"]["index"]["source_versions"].update(v2="future"),
                         lambda a: a["p1"]["extraction"].update(source_versions={}),
                         lambda a: a["p1"]["index"].update(source_only=False)]:
            artifacts = self.artifacts("R")
            mutation(artifacts)
            report = self.run_replay(artifacts=artifacts)
            self.assertEqual(report["prefixes"][0]["status"], "failed")
            self.assertEqual([call["prefix_id"] for call in report["calls"]], ["p2"])

    def test_artifact_mapping_types_and_own_cutoff_are_checked(self):
        self.assertEqual(self.run_replay(artifacts=[])["status"], "invalid")
        report = self.run_replay(artifacts={"p1": []})
        self.assertEqual(report["prefixes"][0]["status"], "failed")
        self.assertEqual(report["accounting"]["calls"], 1)
        self.plan["arm"] = "E"
        artifacts = self.artifacts("E")
        artifacts["p2"]["extraction"]["cutoff"] = self.t1
        report = self.run_replay(artifacts=artifacts)
        self.assertEqual(report["prefixes"][1]["status"], "failed")
        self.assertIn("future to artifact", report["prefixes"][1]["error"])

    def test_delta_comparison_alone_can_read_previous_published_view(self):
        self.plan["delta_comparison"] = True
        seen = []
        def compare(context):
            seen.append(copy.deepcopy(context))
            if context["previous_published"]:
                context["previous_published"]["output"]["contributions"].clear()
            return response({"deltas": []})
        report = self.run_replay(delta_compare=compare)
        self.assertEqual(report["status"], "completed")
        self.assertIsNone(seen[0]["previous_published"])
        self.assertEqual(seen[1]["previous_published"]["version"], report["history"][0]["version"])
        self.assertEqual(len(report["history"][0]["output"]["contributions"]), 1)
        self.assertEqual(report["accounting"]["calls"], 4)
        bad = self.run_replay(delta_compare=lambda c: response({"deltas": [], "contributions": []}))
        self.assertEqual(bad["status"], "incomplete")

    def test_baseline_is_only_separately_pinned_contract(self):
        self.plan["arm"] = "B"
        self.assertEqual(self.run_replay()["status"], "invalid")
        self.plan["adapter"] = dict(baseline_revision=replay.BASELINE, adapter_sha256=replay.digest("adapter contract"))
        seen = []
        report = self.run_replay(lambda c: (seen.append(c) or response(output(c))))
        self.assertEqual(report["status"], "completed")
        self.assertEqual(seen[0]["adapter"], self.plan["adapter"])

    def add_search(self):
        row = source(3, self.t2, "Fetched text.")
        row["search_event_id"] = "fetch-1"
        self.manifest["observations"].append(row)
        self.manifest["search_events"] = [dict(event_id="fetch-1", kind="fetch", observed_at=self.t2,
            request={"command": "never execute this", "url": "https://example.invalid/source"}, response={"body": "Fetched text."},
            observation_ids=["o3"], status="ok", usage=dict(tool_calls=1, elapsed_ms=None, cost=None, model_tokens=None))]

    def test_search_is_separate_same_arm_enrichment_and_opaque_events_never_dispatch(self):
        self.add_search()
        seen = []
        candidate = lambda c: (seen.append(copy.deepcopy(c)) or response(output(c)))
        off = self.run_replay(candidate)
        self.assertTrue(all(not c["search_events"] for c in seen))
        self.assertEqual(len(seen[-1]["observations"]), 2)
        self.assertEqual(off["accounting"]["tool_calls"], 0)
        self.plan["enrichment"] = True
        self.manifest["boundaries"].append(dict(prefix_id="p3", day="2026-01-03", at="2026-01-03T12:00:00Z"))
        on = self.run_replay(candidate)
        self.assertEqual(on["status"], "completed")
        self.assertEqual(on["accounting"]["tool_calls"], 1)
        self.assertIsNone(on["search_events"][0]["usage"]["cost"])
        self.assertEqual(len(seen[-1]["observations"]), 3)

    def test_future_search_link_snippet_admission_and_tool_budget_fail(self):
        self.add_search()
        self.plan["enrichment"] = True
        self.manifest["search_events"][0]["observed_at"] = self.t1
        report = self.run_replay()
        self.assertEqual(report["status"], "invalid")
        self.assertEqual(report["accounting"]["calls"], 0)
        self.manifest["search_events"][0]["observed_at"] = self.t2
        self.manifest["search_events"][0]["kind"] = "search"
        self.assertEqual(self.run_replay()["status"], "invalid")
        self.manifest["search_events"][0]["kind"] = "fetch"
        self.plan["budget"]["tool_calls"] = 0
        report = self.run_replay()
        self.assertEqual(report["prefixes"][1]["error"], "tool_budget_exhausted")
        self.assertEqual(report["accounting"]["calls"], 1)
        self.assertIsNone(report["active"])

    def test_frozen_repository_fixture_manifests_and_recovery_states(self):
        root = Path(__file__).resolve().parents[1] / "replay-fixtures"
        for name in ("synthetic-mixed-v1.json", "synthetic-recovery-prefix-v1.json", "synthetic-search-clock-v1.json"):
            manifest = json.loads((root / name).read_text())
            replay.validate_manifest(manifest)
        self.manifest = json.loads((root / "synthetic-recovery-prefix-v1.json").read_text())
        context = self.context()
        clean, contaminated, repaired = [json.loads((root / "scorer" / name).read_text()) for name in
            ("clean-state-p04-v2.json", "contaminated-state-p04-v2.json", "repaired-state-p04-v2.json")]
        for state in (clean, contaminated, repaired):
            replay.validate_output(state, context)
        invalid = json.loads((root / "scorer/invalid-accounting-state-p04-v2.json").read_text())
        with self.assertRaisesRegex(ValueError, "Inconsistent"):
            replay.validate_output(invalid, context)
        seen = []
        def fixed_response(candidate_context):
            seen.append(candidate_context)
            return response(repaired)
        report = self.run_replay(fixed_response, initial_state=contaminated)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["history"][0]["output"]["deltas"], [])
        self.assertNotIn("prior_state", seen[0])
        self.assertNotIn("expected", seen[0])
        self.assertNotIn("defect_ids", seen[0])


class MaterializerTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "replay-fixtures/materialize_observed.py"
        module_spec = importlib.util.spec_from_file_location("materialize_observed", path)
        self.exporter = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(self.exporter)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        at = "2026-01-01T12:00:00Z"
        observation = source(1, at)
        observation["provenance"] = dict(archive="synthetic", file="input.json", row_index=0)
        observation["story_label"] = "must not leak"
        self.packet = dict(chronology_mode="captured_observation", observations=[observation], case_id="curated")
        self.locator = dict(reference_pins=[], fixture_id="materializer-test", boundaries=[dict(prefix_id="p1", day="2026-01-01", at=at)],
            coverage=dict(scope="Synthetic", gaps=[], source_grouping="must not leak"), observations=[dict(
                packet=dict(path="packet.json", sha256="", observation_index=0), original_observation_id="o1", original_source_version_id="v1",
                source_sha256=observation["source_sha256"], observed_at=at, published_at_utc=at, archive_locator=observation["provenance"],
                available_at=at, observation_id="neutral-1", source_version_id="neutral-version-1")])
        self.repin()

    def repin(self):
        raw = json.dumps(self.packet).encode()
        (self.root / "packet.json").write_bytes(raw)
        self.locator["observations"][0]["packet"]["sha256"] = self.exporter.sha(raw)

    def materialize(self):
        return self.exporter.materialize(self.root, self.root, self.locator)

    def test_only_allowlisted_ungrouped_sources_reach_candidate_manifest(self):
        manifest = self.materialize()
        replay.validate_manifest(manifest)
        self.assertEqual(manifest["observations"][0]["observation_id"], "neutral-1")
        self.assertEqual(set(manifest["coverage"]), {"scope", "gaps"})
        self.assertNotIn("story_label", manifest["observations"][0])
        self.assertNotIn("case_id", manifest)

    def test_packet_hash_path_clock_and_provenance_failures(self):
        for key, value, message in [("available_at", "2026-01-02T12:00:00Z", "availability"),
                                    ("original_observation_id", "wrong", "provenance"),
                                    ("archive_locator", {}, "provenance")]:
            before = copy.deepcopy(self.locator)
            self.locator["observations"][0][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, message):
                self.materialize()
            self.locator = before
        self.locator["observations"][0]["packet"]["path"] = "../escape.json"
        with self.assertRaisesRegex(ValueError, "escapes"):
            self.materialize()
        self.locator["observations"][0]["packet"]["path"] = "packet.json"
        (self.root / "packet.json").write_text("changed")
        with self.assertRaisesRegex(ValueError, "hash"):
            self.materialize()

    def test_repinning_does_not_hide_changed_source_schema_or_chronology(self):
        original = copy.deepcopy(self.packet)
        self.packet["chronology_mode"] = "publication_order_simulation"
        self.repin()
        with self.assertRaisesRegex(ValueError, "Publication"):
            self.materialize()
        self.packet = copy.deepcopy(original)
        self.packet["observations"][0]["fields"]["story_id"] = "generated"
        self.repin()
        with self.assertRaisesRegex(ValueError, "source field"):
            self.materialize()
        self.packet = copy.deepcopy(original)
        self.packet["observations"][0]["fields"]["text"] = "changed while source hash retained"
        self.repin()
        with self.assertRaisesRegex(ValueError, "field hash"):
            self.materialize()


if __name__ == "__main__":
    unittest.main()
