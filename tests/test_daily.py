"""Offline operational tests: real journal, frozen queues, simulated feeds/models."""

import copy
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from news import daily, trajectory
from news.cli import main


@pytest.fixture(autouse=True)
def simulated_diagnostics(fake_model, monkeypatch):
    normal = trajectory.run_task

    def call(task, payload, directory, **kwargs):
        directory.mkdir(exist_ok=True)
        path = directory / "metadata.json"
        if not path.exists():
            path.write_text(
                json.dumps({"process_started": False, "usage": None, "duration_seconds": 0})
            )
        return normal(task, payload, directory, **kwargs)

    monkeypatch.setattr(trajectory, "run_task", call)


@pytest.fixture
def clock(monkeypatch):
    current = [datetime(2026, 10, 1, 16, tzinfo=UTC)]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return current[0].astimezone(tz)

    monkeypatch.setattr(daily, "datetime", Clock)

    def advance(day):
        current[0] = datetime.fromisoformat(day + "T16:00:00+00:00")

    return advance


@pytest.fixture
def poll(snapshot, monkeypatch, clock):
    current = {
        "articles": copy.deepcopy(snapshot["articles"]),
        "coverage": {"status": "complete", "feed_errors": 0, "invalid": 0, "feeds": []},
        "calls": 0,
    }

    def collect(config, day, directory):
        current["calls"] += 1
        (directory / "000.xml").write_text("<rss/>")
        return copy.deepcopy(current["articles"]), dict(current["coverage"], day=day)

    monkeypatch.setattr(daily.feeds, "collect", collect)
    return current


def article(base, number):
    return dict(base, id=f"article-{number}", url=f"https://example.test/{number}")


def manifests(state):
    return [
        json.loads(path.read_text())
        for path in sorted((state / "captures").glob("*/manifest.json"))
    ]


def assert_local_links_resolve(path):
    text = path.read_text()
    for target in re.findall(r"\]\(([^)]+)\)", text):
        if not target.startswith(("https:", "http:", "<")):
            assert (path.parent / target).exists(), target


def test_real_journal_briefing_and_repeat_without_model_calls(poll, fake_model, tmp_path):
    first = daily.run([], tmp_path)
    assert first["status"] == "complete"
    assert first["accepted_batches"] == 1
    assert first["pending_batches"] == 0
    assert "Brook bridge" in Path(first["briefing"]).read_text()
    assert_local_links_resolve(Path(first["briefing"]))
    assert_local_links_resolve(tmp_path / "index.md")
    assert_local_links_resolve(tmp_path / "latest.md")
    (tmp_path / "feedback.md").write_text("Reader-owned notes")

    second = daily.run([], tmp_path)
    assert second["status"] == "complete"
    assert second["accepted_batches"] == second["model_invocations"] == 0
    assert len(fake_model) == 1
    assert len(manifests(tmp_path)) == 2
    assert manifests(tmp_path)[1]["new_versions"] == 0
    assert (tmp_path / "feedback.md").read_text() == "Reader-owned notes"
    assert Path(first["report"]).is_file()


def test_reversion_is_retained_and_unchanged_next_day_is_skipped(poll, fake_model, clock, tmp_path):
    original = copy.deepcopy(poll["articles"])
    daily.run([], tmp_path)
    clock("2026-10-02")
    poll["articles"][0]["text"] = "The Brook bridge reopened."
    daily.run([], tmp_path)
    clock("2026-10-03")
    poll["articles"] = original
    daily.run([], tmp_path)
    clock("2026-10-04")
    daily.run([], tmp_path)
    assert [item["day"] for item in fake_model] == ["2026-10-01", "2026-10-02", "2026-10-03"]
    assert [item["new_versions"] for item in manifests(tmp_path)] == [1, 1, 1, 0]


def test_simultaneous_versions_and_sources_do_not_ping_pong(poll, fake_model, tmp_path, clock):
    base = poll["articles"][0]
    poll["articles"] = [
        base,
        dict(base, text="Alternative source wording."),
        dict(base, source="Other feed"),
    ]
    first = daily.run([], tmp_path)
    assert first["accepted_batches"] == 3  # repeated URL requires separate frozen batches
    clock("2026-10-02")
    second = daily.run([], tmp_path)
    assert second["accepted_batches"] == 0
    assert len(fake_model) == 3


def test_same_day_reversion_gets_its_own_capture_without_altering_source_fields(
    poll, fake_model, tmp_path
):
    original = copy.deepcopy(poll["articles"])
    daily.run([], tmp_path)
    poll["articles"][0]["text"] = "The bridge reopened."
    daily.run([], tmp_path)
    poll["articles"] = original
    third = daily.run([], tmp_path)
    assert third["accepted_batches"] == 1 and len(fake_model) == 3
    assert len({payload["articles"][0]["capture_id"] for payload in fake_model}) == 3
    for manifest in manifests(tmp_path):
        for raw in manifest["articles"]:
            processing_id = manifest["processing_ids"][daily.digest(raw)]
            matching = [
                a for payload in fake_model for a in payload["articles"] if a["id"] == processing_id
            ]
            assert len(matching) == 1
            assert {key: matching[0][key] for key in raw if key != "id"} == {
                key: value for key, value in raw.items() if key != "id"
            }


def test_capture_only_is_offline_from_model_and_resume_never_fetches(poll, fake_model, tmp_path):
    first = daily.run([], tmp_path, collect_only=True)
    assert first["accepted_batches"] == 0
    assert first["pending_batches"] == 1
    assert fake_model == []
    assert not (tmp_path / "memory" / "journal.sqlite3").exists()
    second = daily.run(None, tmp_path, resume_only=True)
    assert second["status"] == "complete"
    assert second["accepted_batches"] == 1
    assert poll["calls"] == 1


def test_backlog_keeps_observation_dates_and_each_runs_as_known_links(
    poll, fake_model, tmp_path, clock
):
    daily.run([], tmp_path, collect_only=True)
    clock("2026-10-02")
    poll["articles"][0]["text"] = "The bridge reopened."
    daily.run([], tmp_path, collect_only=True)
    clock("2026-10-03")
    report = daily.run(None, tmp_path, resume_only=True)
    text = Path(report["briefing"]).read_text()
    assert "run on 2026-10-03" in text
    assert "observed on 2026-10-01" in text and "observed on 2026-10-02" in text
    assert "observed on 2026-10-03" not in text
    results = list(daily._accepted(tmp_path / "memory").values())
    results[1]["stories"][0]["id"] = results[0]["stories"][0]["id"]
    text = daily._briefing(report, results)
    for result in results:
        assert (
            f"../../memory/runs/{result['run_id']}/stories/{result['stories'][0]['id']}.md" in text
        )
    assert_local_links_resolve(Path(report["briefing"]))


def test_budget_keeps_fifo_across_capture_days(poll, fake_model, tmp_path, clock):
    base = poll["articles"][0]
    poll["articles"] = [article(base, number) for number in range(3)]
    first = daily.run([], tmp_path, batch_size=1, max_batches=1)
    frozen = [
        (path, path.read_bytes()) for path in (tmp_path / "captures").glob("*/batches/*.json")
    ]
    assert first["pending_batches"] == 2 and first["status"] == "partial"
    clock("2026-10-02")
    poll["articles"] = [article(base, 4)]
    second = daily.run([], tmp_path, batch_size=1, max_batches=3)
    assert second["status"] == "complete"
    assert [payload["day"] for payload in fake_model] == ["2026-10-01"] * 3 + ["2026-10-02"]
    assert all(path.read_bytes() == content for path, content in frozen)
    assert_local_links_resolve(Path(second["briefing"]))


def test_failure_stops_queue_and_next_invocation_preserves_failed_artifacts(
    poll, fake_model, tmp_path, monkeypatch
):
    base = poll["articles"][0]
    poll["articles"] = [article(base, number) for number in range(3)]
    normal = trajectory.run_task
    calls = []

    def fail_second(task, payload, directory, **kwargs):
        calls.append(task)
        failing = task == "trajectory" and calls.count("trajectory") == 2
        directory.mkdir()
        metadata = {
            "process_started": True,
            "duration_seconds": 1,
            "usage": None if failing else {"input_tokens": 100, "output_tokens": 20},
        }
        (directory / "metadata.json").write_text(json.dumps(metadata))
        if failing:
            raise RuntimeError("simulated connection failure")
        return normal(task, payload, directory, **kwargs)

    monkeypatch.setattr(trajectory, "run_task", fail_second)
    first = daily.run([], tmp_path, batch_size=1)
    assert first["status"] == "failed"
    assert first["accepted_batches"] == 1 and first["pending_batches"] == 2
    assert len(first["attempts"]) == 2
    assert first["model_invocations"] == 3
    assert first["unknown_usage_invocations"] == 1
    assert first["known_usage"] == {"input_tokens": 200, "output_tokens": 40}
    failed = list((tmp_path / "memory" / "runs").glob("*/failure.json"))
    assert len(failed) == 1
    failure_bytes = failed[0].read_bytes()
    second = daily.run(None, tmp_path, resume_only=True)
    assert second["status"] == "complete" and second["accepted_batches"] == 2
    assert len(calls) == 7  # failed batch retried once, then two proposal/review pairs
    assert failed[0].read_bytes() == failure_bytes
    assert len(fake_model) == 3


def test_journal_recovers_after_receipt_failure_even_if_code_changes(
    poll, fake_model, tmp_path, monkeypatch
):
    write = daily._write

    def fail_receipt(path, value):
        if path.name == "report.json":
            raise OSError("simulated disk error after acceptance")
        write(path, value)

    monkeypatch.setattr(daily, "_write", fail_receipt)
    with pytest.raises(OSError, match="disk error"):
        daily.run([], tmp_path)
    assert len(fake_model) == 1
    monkeypatch.setattr(daily, "_write", write)
    monkeypatch.setattr(daily, "_protocol", lambda: {"version": "changed code"})
    monkeypatch.setattr(trajectory, "run", lambda *a, **kw: pytest.fail("accepted input replayed"))
    report = daily.run(None, tmp_path, resume_only=True)
    assert report["status"] == "partial"
    assert len(report["incomplete_reports"]) == 1
    assert report["recovered_batches"] == 1 and report["model_invocations"] == 0
    assert "Brook bridge" in Path(report["briefing"]).read_text()
    assert_local_links_resolve(Path(report["briefing"]))


def test_tampered_batch_is_not_sent_to_model(poll, fake_model, tmp_path):
    daily.run([], tmp_path, collect_only=True)
    path = next((tmp_path / "captures").glob("*/batches/*.json"))
    data = json.loads(path.read_text())
    data["articles"][0]["text"] = "Changed frozen evidence."
    path.write_text(json.dumps(data))
    result = daily.run(None, tmp_path, resume_only=True)
    assert result["status"] == "failed" and "frozen batch changed" in result["error"]
    assert fake_model == []


def test_partial_feed_coverage_is_visible_after_successful_processing(poll, fake_model, tmp_path):
    poll["coverage"].update(status="partial", feed_errors=1, invalid=2)
    result = daily.run([], tmp_path)
    assert result["status"] == "partial" and result["accepted_batches"] == 1
    assert "1 failed feeds; 2 invalid items" in Path(result["briefing"]).read_text()
    assert result["coverage"][0]["feed_errors"] == 1


def test_empty_feeds_are_not_model_calls(poll, fake_model, tmp_path):
    poll["articles"] = []
    report = daily.run([], tmp_path)
    assert report["status"] == "complete"
    assert report["model_invocations"] == report["accepted_batches"] == 0
    assert "does not mean no news" in Path(report["briefing"]).read_text()
    assert fake_model == []


def test_orphan_raw_capture_remains_visible(poll, fake_model, tmp_path):
    orphan = tmp_path / "captures" / "interrupted" / "feeds"
    orphan.mkdir(parents=True)
    (orphan / "000.xml").write_text("<rss/>")
    result = daily.run([], tmp_path)
    assert result["status"] == "partial"
    assert result["incomplete_captures"] == ["captures/interrupted"]
    assert (orphan / "000.xml").read_text() == "<rss/>"


def test_capture_failure_receipt_immediately_points_to_unqueued_raw_files(
    poll, fake_model, tmp_path, monkeypatch
):
    def interrupted(config, day, directory):
        (directory / "partial.xml").write_text("raw evidence")
        raise OSError("simulated collection failure")

    monkeypatch.setattr(daily.feeds, "collect", interrupted)
    report = daily.run([], tmp_path)
    assert report["status"] == "failed" and fake_model == []
    assert len(report["incomplete_captures"]) == 1
    orphan = report["incomplete_captures"][0]
    assert (tmp_path / orphan / "feeds" / "partial.xml").read_text() == "raw evidence"
    assert orphan in Path(report["briefing"]).read_text()


@pytest.mark.parametrize("defect", ["malformed", "missing", "unreadable", "missing flag"])
@pytest.mark.parametrize("damaged_task", ["trajectory", "coherence", "both"])
def test_accepted_result_survives_unavailable_diagnostics(
    poll, fake_model, tmp_path, monkeypatch, defect, damaged_task
):
    normal, read = trajectory.run_task, daily._read
    damaged_directories = {
        "trajectory": {"model"},
        "coherence": {"review"},
        "both": {"model", "review"},
    }[damaged_task]

    def bad_diagnostics(task, payload, directory, **kwargs):
        result = normal(task, payload, directory, **kwargs)
        metadata = directory / "metadata.json"
        metadata.write_text(
            json.dumps(
                {
                    "process_started": True,
                    "usage": {"input_tokens": 100, "output_tokens": 20},
                    "duration_seconds": 1,
                }
            )
        )
        if directory.name not in damaged_directories:
            return result
        if defect == "malformed":
            metadata.write_text("{")
        elif defect == "missing":
            metadata.unlink()
        elif defect == "missing flag":
            metadata.write_text('{"usage": null}')
        return result

    def denied(path):
        if (
            defect == "unreadable"
            and path.name == "metadata.json"
            and path.parent.name in damaged_directories
        ):
            raise PermissionError("simulated diagnostic read denial")
        return read(path)

    monkeypatch.setattr(trajectory, "run_task", bad_diagnostics)
    monkeypatch.setattr(daily, "_read", denied)
    report = daily.run([], tmp_path)
    assert report["status"] == "partial" and report["accepted_batches"] == 1
    assert len(report["attempts"]) == 1
    assert report["unknown_launch_attempts"] == len(damaged_directories)
    assert report["model_invocations"] == 2 - len(damaged_directories)
    assert report["known_usage"] == (
        {} if damaged_task == "both" else {"input_tokens": 100, "output_tokens": 20}
    )
    calls = report["attempts"][0]["calls"]
    assert [call["task"] for call in calls] == ["trajectory", "coherence"]
    assert sum(call["process_started"] is None for call in calls) == len(damaged_directories)
    assert report["attempts"][0]["diagnostic_error"]
    assert "Brook bridge" in Path(report["briefing"]).read_text()
    assert len(daily._accepted(tmp_path / "memory")) == 1


def test_failed_model_keeps_attempt_when_diagnostics_are_malformed(
    poll, fake_model, tmp_path, monkeypatch
):
    def fail(task, payload, directory, **kwargs):
        directory.mkdir()
        (directory / "metadata.json").write_text("{")
        raise RuntimeError("original processing failure")

    monkeypatch.setattr(trajectory, "run_task", fail)
    report = daily.run([], tmp_path)
    assert report["status"] == "failed" and "original processing failure" in report["error"]
    assert len(report["attempts"]) == report["unknown_launch_attempts"] == 1
    assert report["pending_batches"] == 1 and report["accepted_batches"] == 0


def write_call_metadata(directory, usage, *, process_started=True):
    directory.mkdir(exist_ok=True)
    (directory / "metadata.json").write_text(
        json.dumps(
            {
                "process_started": process_started,
                "usage": usage,
                "duration_seconds": 1,
            }
        )
    )


def test_two_calls_are_counted_and_reusing_the_result_costs_nothing(
    poll, fake_model, tmp_path, monkeypatch
):
    normal = trajectory.run_task

    def tracked(task, payload, directory, **kwargs):
        write_call_metadata(directory, {"input_tokens": 100, "output_tokens": 20})
        return normal(task, payload, directory, **kwargs)

    monkeypatch.setattr(trajectory, "run_task", tracked)
    report = daily.run([], tmp_path)
    assert report["status"] == "complete" and report["accepted_batches"] == 1
    assert report["model_invocations"] == 2
    assert report["unknown_usage_invocations"] == report["unknown_launch_attempts"] == 0
    assert report["known_usage"] == {"input_tokens": 200, "output_tokens": 40}
    attempt = report["attempts"][0]
    assert [call["task"] for call in attempt["calls"]] == ["trajectory", "coherence"]
    assert attempt["model_seconds"] == 2
    batch = daily._queue(tmp_path, manifests(tmp_path))[0]
    result, reused = daily._attempt(batch, tmp_path, 30)
    assert result["run_id"] == attempt["run_id"] and reused["status"] == "reused"
    assert reused["model_invocations"] == 0 and reused["usage"] is None
    assert reused["calls"] == [] and len(fake_model) == 1


@pytest.mark.parametrize("damaged_task", ["trajectory", "coherence"])
def test_invalid_usage_preserves_known_launch_and_other_call_usage(
    poll, tmp_path, monkeypatch, damaged_task
):
    normal = trajectory.run_task

    def tracked(task, payload, directory, **kwargs):
        usage = {"input_tokens": -1} if task == damaged_task else {"input_tokens": 100}
        write_call_metadata(directory, usage)
        return normal(task, payload, directory, **kwargs)

    monkeypatch.setattr(trajectory, "run_task", tracked)
    report = daily.run([], tmp_path)
    assert report["status"] == "partial" and report["accepted_batches"] == 1
    assert report["model_invocations"] == 2 and report["unknown_launch_attempts"] == 0
    assert report["unknown_usage_invocations"] == 1
    assert report["known_usage"] == {"input_tokens": 100}
    assert all(call["process_started"] for call in report["attempts"][0]["calls"])


def test_rejected_review_counts_both_calls_without_accepting_the_batch(
    poll, fake_model, tmp_path, monkeypatch
):
    normal = trajectory.run_task

    def reject(task, payload, directory, **kwargs):
        write_call_metadata(directory, {"input_tokens": 100})
        result = normal(task, payload, directory, **kwargs)
        if task == "coherence":
            result["stories"][0].update(verdict="unsupported", reason="Unrelated matters.")
        return result

    monkeypatch.setattr(trajectory, "run_task", reject)
    report = daily.run([], tmp_path)
    assert report["status"] == "failed" and "coherence review rejected" in report["error"]
    assert report["accepted_batches"] == 0 and report["pending_batches"] == 1
    assert report["model_invocations"] == 2 and report["known_usage"] == {"input_tokens": 200}
    assert report["unknown_usage_invocations"] == report["unknown_launch_attempts"] == 0
    assert daily._accepted(tmp_path / "memory") == {} and len(fake_model) == 1
    artifact = tmp_path / report["attempts"][0]["artifact"]
    assert (
        json.loads((artifact / "review.json").read_text())["stories"][0]["verdict"] == "unsupported"
    )


@pytest.mark.parametrize("timeout_task", ["trajectory", "coherence"])
def test_timeout_counts_started_calls_and_preserves_available_usage(
    poll, tmp_path, monkeypatch, timeout_task
):
    normal = trajectory.run_task

    def timeout(task, payload, directory, **kwargs):
        write_call_metadata(directory, None if task == timeout_task else {"input_tokens": 100})
        if task == timeout_task:
            raise TimeoutError("simulated CLI deadline")
        return normal(task, payload, directory, **kwargs)

    monkeypatch.setattr(trajectory, "run_task", timeout)
    report = daily.run([], tmp_path)
    assert report["status"] == "failed" and "simulated CLI deadline" in report["error"]
    assert report["accepted_batches"] == 0 and report["pending_batches"] == 1
    assert report["model_invocations"] == (1 if timeout_task == "trajectory" else 2)
    assert report["unknown_usage_invocations"] == 1 and report["unknown_launch_attempts"] == 0
    assert report["known_usage"] == ({} if timeout_task == "trajectory" else {"input_tokens": 100})
    assert daily._accepted(tmp_path / "memory") == {}


def test_deadline_exhausted_before_review_does_not_count_an_unlaunched_call(
    poll, tmp_path, monkeypatch
):
    normal = trajectory.run_task

    class ModelClock:
        values = iter((100, 131))

        @staticmethod
        def monotonic():
            return next(ModelClock.values)

    def tracked(task, payload, directory, **kwargs):
        assert task == "trajectory"
        write_call_metadata(directory, {"input_tokens": 100})
        return normal(task, payload, directory, **kwargs)

    monkeypatch.setattr(trajectory, "time", ModelClock)
    monkeypatch.setattr(trajectory, "run_task", tracked)
    report = daily.run([], tmp_path, timeout=30)
    assert report["status"] == "failed" and "deadline exhausted" in report["error"]
    assert report["model_invocations"] == 1 and report["known_usage"] == {"input_tokens": 100}
    assert report["unknown_launch_attempts"] == report["unknown_usage_invocations"] == 0
    assert [call["task"] for call in report["attempts"][0]["calls"]] == ["trajectory"]


def test_clock_reversal_and_unmanaged_memory_fail_before_model(
    poll, fake_model, tmp_path, clock, snapshot
):
    daily.run([], tmp_path)
    clock("2026-09-30")
    reversal = daily.run([], tmp_path)
    assert reversal["status"] == "failed" and "clock" in reversal["error"]
    other = tmp_path / "other"
    trajectory.run(snapshot, other / "memory")
    unmanaged = daily.run(None, other, resume_only=True)
    assert unmanaged["status"] == "failed" and "unqueued" in unmanaged["error"]
    assert len(fake_model) == 2


def test_outer_lock_blocks_overlapping_routine(poll, fake_model, tmp_path):
    with trajectory.state_lock(tmp_path), pytest.raises(ValueError, match="another run"):
        daily.run([], tmp_path)
    assert poll["calls"] == 0 and fake_model == []


def test_abrupt_process_exit_preserves_intent_and_unknown_prior_attempt(poll, fake_model, tmp_path):
    daily.run([], tmp_path, collect_only=True)
    code = """
import os, sys
from pathlib import Path
from news import daily, trajectory
def abrupt(task, payload, directory, **kwargs):
    directory.mkdir()
    (directory / 'events.jsonl').write_text('partial uncompleted model output')
    os._exit(73)
trajectory.run_task = abrupt
daily.run(None, Path(sys.argv[1]), resume_only=True)
"""
    child = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)], capture_output=True, timeout=10
    )
    assert child.returncode == 73, child.stderr
    partial = list((tmp_path / "memory" / "runs").glob("*/model/events.jsonl"))
    assert len(partial) == 1
    report = daily.run(None, tmp_path, resume_only=True)
    assert report["status"] == "partial" and report["accepted_batches"] == 1
    assert len(report["incomplete_reports"]) == len(report["unfinished_prior_attempts"]) == 1
    assert (tmp_path / report["unfinished_prior_attempts"][0]).exists()
    assert "prior invocations have no final receipt" in Path(report["briefing"]).read_text()
    assert partial[0].read_text() == "partial uncompleted model output"
    assert len(fake_model) == 1


def test_char_budget_splits_before_model(poll, fake_model, tmp_path):
    base = poll["articles"][0]
    poll["articles"] = [article(dict(base, text="a" * 19_000), i) for i in range(8)]
    report = daily.run([], tmp_path, batch_size=50, collect_only=True)
    assert report["pending_batches"] == 2
    for path in (tmp_path / "captures").glob("*/batches/*.json"):
        assert len(daily.canonical(json.loads(path.read_text()))) <= daily.MAX_INPUT_CHARS
    assert fake_model == []


@pytest.mark.parametrize(
    "options",
    [
        {"batch_size": 0},
        {"max_batches": 0},
        {"timeout": float("nan")},
        {"collect_only": True, "resume_only": True},
    ],
)
def test_invalid_limits_fail_before_files_or_network(options, poll, fake_model, tmp_path):
    with pytest.raises(ValueError):
        daily.run([], tmp_path / "new", **options)
    assert not (tmp_path / "new").exists() and poll["calls"] == 0 and fake_model == []


def test_cli_resume_does_not_require_feed_config(poll, fake_model, tmp_path, capsys):
    daily.run([], tmp_path, collect_only=True)
    assert (
        main(["daily", "--resume-only", "--state", str(tmp_path), "--feeds", "does-not-exist"]) == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "complete"
    assert Path(output["briefing"]).exists()
