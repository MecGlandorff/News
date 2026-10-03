import copy
from pathlib import Path

import pytest

from evals import replay


def article(aid, day):
    return {
        "id": aid,
        "title": aid,
        "text": f"Source evidence for {aid}.",
        "source": "Synthetic source",
        "url": f"https://example.test/{aid}",
        "published_at": f"{day}T10:00:00Z",
    }


@pytest.fixture
def bundle(tmp_path):
    prepared, labels = tmp_path / "prepared", tmp_path / "labels.json"
    snapshots = [
        {
            "day": "2026-05-09",
            "articles": [article("a1", "2026-05-09"), article("a2", "2026-05-09")],
        },
        {"day": "2026-05-10", "articles": [article("a3", "2026-05-10")]},
        {"day": "2026-05-10", "articles": [article("a4", "2026-05-10")]},
    ]
    batches = []
    for number, snapshot in enumerate(snapshots, 1):
        name = f"{number:02d}-{snapshot['day']}.json"
        replay.write(prepared / name, snapshot)
        batches.append(
            {"file": name, "day": snapshot["day"], "articles": len(snapshot["articles"])}
        )
    replay.write(prepared / "manifest.json", {"batches": batches})
    cases = []
    for cid, day, aid, prior_day, prior, expected in [
        ("followup", "2026-05-10", "a3", "2026-05-09", "a1", True),
        ("distinct", "2026-05-10", "a3", "2026-05-09", "a2", False),
        ("later-candidate", "2026-05-10", "a3", "2026-05-10", "a4", False),
        ("same-batch", "2026-05-09", "a1", "2026-05-09", "a2", False),
    ]:
        cases.append(
            {
                "case_id": cid,
                "layer": "same_day" if day == prior_day else "story",
                "today_date": day,
                "today_article_id": aid,
                "candidate_date": prior_day,
                "candidate_article_id": prior,
                "expected_accepted": expected,
                "review_note": "Synthetic independently specified relation",
            }
        )
    replay.write(labels, {"cases": cases, "methodology": "Synthetic test labels"})
    return prepared, labels, tmp_path / "output"


def fake_pipeline(monkeypatch, *, failure=None, events=None):
    calls, states = [], {}
    event_ids = events or {"a1": "e1", "a2": "e2", "a3": "e1", "a4": "e4"}

    def run(snapshot, state, *, strategy, timeout):
        state_calls = states.setdefault(state, [])
        index = len(state_calls) + 1
        state_calls.append(snapshot)
        calls.append((copy.deepcopy(snapshot), state, strategy, timeout))
        memory = (
            []
            if index == 1
            else [
                {
                    "id": "e1",
                    "evidence": [{"article_id": "a3" if index == 3 else "recent"}],
                    "history": [{"article_id": "a1"}],
                },
                {"id": "e2", "evidence": [{"article_id": "different-source"}], "history": []},
            ]
        )
        run_id = f"run-{index}"
        directory = state / "runs" / run_id
        replay.write(directory / "input.json", dict(snapshot, memory=memory))
        error = failure(state, index) if failure else None
        replay.write(
            directory / "single/metadata.json",
            {
                "status": "failed" if error else "ok",
                "duration_seconds": 0.1,
                "usage": None if error else {"input_tokens": 10, "output_tokens": 2},
            },
        )
        if error:
            replay.write(directory / "failure.json", {"error": str(error)})
            raise error
        return {
            "run_id": run_id,
            "events": [
                {"id": event_ids[a["id"]], "article_ids": [a["id"]]} for a in snapshot["articles"]
            ],
        }, False

    monkeypatch.setattr(replay, "run", run)
    return calls


def test_success_uses_fresh_states_records_usage_and_observed_context(bundle, monkeypatch):
    calls = fake_pipeline(monkeypatch)
    report = replay.evaluate(*bundle, repeats=2, max_calls=6, timeout=23)
    assert report["completed"]
    assert len(calls) == 6
    assert {call[1].name for call in calls} == {"replay-1", "replay-2"}
    assert all(call[2:] == ("single", 23) for call in calls)
    first = report["replays"][0]
    assert first["summary"] == {
        "correct_pairs": 4,
        "incorrect_merges": 0,
        "missed_positive_connections": 0,
        "unavailable_pairs": 0,
        "unprocessed_pairs": 0,
        "calls": 3,
        "calls_with_usage": 3,
        "reported_usage": {"input_tokens": 30, "output_tokens": 6},
    }
    contexts = {row["case_id"]: row["candidate_context"][0] for row in first["scored_cases"]}
    assert contexts["followup"]["presence"] == "past_event_memory"
    assert contexts["followup"]["source_article_id_present"]  # Present only in history.
    assert contexts["distinct"]["event_id_present"]
    assert not contexts["distinct"]["source_article_id_present"]
    assert contexts["later-candidate"]["observed_at"]["article_id"] == "a4"
    assert contexts["later-candidate"]["target"]["article_id"] == "a3"
    assert contexts["later-candidate"]["presence"] == "past_event_memory"
    assert contexts["same-batch"]["presence"] == "same_batch"
    assert [batch["memory_event_count"] for batch in first["batches"]] == [0, 2, 2]
    assert [batch["history_quote_count"] for batch in first["batches"]] == [0, 1, 1]
    for batch in first["batches"]:
        payload = replay.read(bundle[2] / batch["artifacts"][0] / "input.json")
        assert batch["request_chars"] == len(replay.canonical(payload))
    manifest = replay.read(bundle[2] / "manifest.json")
    assert manifest["labels_sha256"] == replay.sha256(bundle[1])
    assert manifest["runtime"]["planned_calls"] == 6
    assert "news/pipeline.py" in manifest["source_files"]
    assert "news/tasks/single.md" in manifest["source_files"]
    assert replay.read(bundle[2] / "report.json") == report


def test_failed_repeat_preserves_unknown_pairs_and_continues_fresh_repeat(bundle, monkeypatch):
    calls = fake_pipeline(
        monkeypatch,
        failure=lambda state, index: (
            RuntimeError("model rejected") if state.name == "replay-1" and index == 2 else None
        ),
    )
    report = replay.evaluate(*bundle, repeats=2, max_calls=6)
    assert not report["completed"]
    failed, succeeded = report["replays"]
    assert not failed["completed"] and succeeded["completed"]
    assert len(calls) == 5  # Failed repetition stops; no retry of its failed batch.
    assert failed["summary"]["unavailable_pairs"] == 2
    assert failed["summary"]["unprocessed_pairs"] == 1
    assert failed["summary"]["missed_positive_connections"] == 0
    assert failed["summary"]["incorrect_merges"] == 0
    assert failed["summary"]["calls_with_usage"] == 1
    assert failed["calls"][1]["usage"] is None
    assert "model rejected" in failed["failures"][0]["error"]
    assert (bundle[2] / failed["batches"][1]["artifacts"][0] / "failure.json").is_file()


def test_actual_wrong_connections_are_separate_from_unavailable_pairs(bundle, monkeypatch):
    fake_pipeline(monkeypatch, events={"a1": "e1", "a2": "e2", "a3": "e2", "a4": "e4"})
    summary = replay.evaluate(*bundle, max_calls=3)["replays"][0]["summary"]
    assert summary["incorrect_merges"] == 1
    assert summary["missed_positive_connections"] == 1
    assert summary["unavailable_pairs"] == summary["unprocessed_pairs"] == 0


@pytest.mark.parametrize(
    "problem",
    [
        "late-invalid-input",
        "nonchronological",
        "duplicate-article",
        "unknown-reference",
        "unknown-alias",
        "nonboolean",
        "duplicate-case",
        "wrong-layer",
        "bad-budget",
        "path-escape",
    ],
)
def test_all_preflight_failures_happen_before_any_pipeline_call(bundle, monkeypatch, problem):
    prepared, labels, output = bundle
    document, manifest = replay.read(labels), replay.read(prepared / "manifest.json")
    if problem == "late-invalid-input":
        path = prepared / manifest["batches"][-1]["file"]
        snapshot = replay.read(path)
        snapshot["articles"][0]["url"] = "not-a-url"
        replay.write(path, snapshot)
    elif problem == "nonchronological":
        manifest["batches"].reverse()
    elif problem == "duplicate-article":
        path = prepared / manifest["batches"][-1]["file"]
        snapshot = replay.read(path)
        snapshot["articles"][0]["id"] = "a3"
        replay.write(path, snapshot)
    elif problem == "unknown-reference":
        document["cases"][-1]["candidate_article_id"] = "unknown"
    elif problem == "unknown-alias":
        document["cases"][-1]["candidate_article_ids"] = ["unknown"]
    elif problem == "nonboolean":
        document["cases"][-1]["expected_accepted"] = 1
    elif problem == "duplicate-case":
        document["cases"].append(document["cases"][0])
    elif problem == "wrong-layer":
        document["cases"][-1]["layer"] = "story"
    elif problem == "path-escape":
        manifest["batches"][-1]["file"] = "../outside.json"
    replay.write(prepared / "manifest.json", manifest)
    replay.write(labels, document)
    monkeypatch.setattr(replay, "run", lambda *a, **kw: pytest.fail("spent a model call"))
    with pytest.raises(ValueError):
        replay.evaluate(*bundle, max_calls=1 if problem == "bad-budget" else 3)
    assert not output.exists()


@pytest.mark.parametrize("style", ["april", "may"])
def test_frozen_input_hashes_reject_drift_before_calls(bundle, monkeypatch, style):
    prepared, labels, _ = bundle
    hashes = {path.name: replay.sha256(path) for path in prepared.glob("*.json")}
    declared = (
        {
            "prepared_manifest_sha256": hashes.pop("manifest.json"),
            "prepared_files": hashes,
            "raw_sources": [],
        }
        if style == "april"
        else {f"prepared/{k}": v for k, v in hashes.items()}
    )
    document = replay.read(labels)
    document["input_hashes"] = declared
    replay.write(labels, document)
    replay.preflight(prepared, labels)
    target = sorted(prepared.glob("[0-9]*.json"))[-1]
    snapshot = replay.read(target)
    snapshot["articles"][0]["text"] += " Changed source text."
    replay.write(target, snapshot)
    monkeypatch.setattr(replay, "run", lambda *a, **kw: pytest.fail("spent a model call"))
    with pytest.raises(ValueError, match="different input"):
        replay.evaluate(*bundle, max_calls=3)


def test_interrupt_preserves_partial_report_and_failed_artifacts(bundle, monkeypatch):
    fake_pipeline(
        monkeypatch, failure=lambda state, index: KeyboardInterrupt() if index == 2 else None
    )
    with pytest.raises(KeyboardInterrupt):
        replay.evaluate(*bundle, repeats=2, max_calls=6)
    report = replay.read(bundle[2] / "report.json")
    assert not report["completed"]
    assert len(report["replays"]) == 1
    assert "KeyboardInterrupt" in report["replays"][0]["failures"][0]["error"]


def test_same_id_on_different_day_is_not_same_batch():
    case = {
        "case_id": "updated-url",
        "layer": "story",
        "today_date": "2026-05-10",
        "today_article_id": "same",
        "candidate_date": "2026-05-09",
        "candidate_article_id": "same",
        "expected_accepted": True,
        "review_note": "update",
    }
    old, new = ("2026-05-09", "same"), ("2026-05-10", "same")
    row = replay.score(
        [case],
        {old: "old", new: "new"},
        {new: {"day": new[0], "articles": [{"id": "same"}], "memory": []}},
        {old: 0, new: 1},
        {old, new},
    )[0]
    assert row["candidate_context"][0]["presence"] == "omitted"
    assert not row["candidate_context"][0]["source_article_id_present"]


def test_source_id_in_an_unrelated_event_does_not_support_target_event():
    case = {
        "case_id": "wrong-event",
        "layer": "story",
        "today_date": "2026-05-10",
        "today_article_id": "new",
        "candidate_date": "2026-05-09",
        "candidate_article_id": "old",
        "expected_accepted": True,
        "review_note": "update",
    }
    old, new = ("2026-05-09", "old"), ("2026-05-10", "new")
    payload = {
        "day": new[0],
        "articles": [{"id": "new"}],
        "memory": [
            {"id": "target-event", "evidence": [{"article_id": "other"}]},
            {"id": "unrelated-event", "evidence": [], "history": [{"article_id": "old"}]},
        ],
    }
    row = replay.score(
        [case],
        {old: "target-event", new: "target-event"},
        {new: payload},
        {old: 0, new: 1},
        {old, new},
    )[0]
    context = row["candidate_context"][0]
    assert context["event_id_present"]
    assert context["presence"] == "past_event_memory"
    assert not context["source_article_id_present"]


def test_existing_destination_is_not_reused(bundle, monkeypatch):
    bundle[2].mkdir()
    monkeypatch.setattr(replay, "run", lambda *a, **kw: pytest.fail("spent a model call"))
    with pytest.raises(ValueError, match="fresh destination"):
        replay.evaluate(*bundle, max_calls=3)


def test_cli_returns_failure_for_incorrect_completed_replay(monkeypatch):
    seen = []

    def evaluate(**kwargs):
        seen.append(kwargs)
        return {"completed": True, "replays": [{"scored_cases": [{"correct": False}]}]}

    monkeypatch.setattr(replay, "evaluate", evaluate)
    assert (
        replay.main(
            [
                "--prepared",
                "prepared",
                "--labels",
                "labels.json",
                "--output",
                "out",
                "--max-calls",
                "9",
            ]
        )
        == 1
    )
    assert seen[0]["repeats"] == 1 and seen[0]["timeout"] == 180
    assert seen[0]["prepared"] == Path("prepared")
