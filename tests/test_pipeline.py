import json
import sqlite3
from copy import deepcopy

import pytest

from news import pipeline


def test_run_is_persistent_replayable_and_idempotent(snapshot, fake_model, tmp_path):
    first, reused = pipeline.run(snapshot, tmp_path)
    assert not reused
    second, reused = pipeline.run(snapshot, tmp_path)
    assert reused and second == first
    assert len(fake_model) == 1
    saved = tmp_path / "runs" / first["run_id"]
    assert json.loads((saved / "input.json").read_text())["articles"] == snapshot["articles"]
    assert pipeline.replay(tmp_path, first["run_id"]) == (saved / "briefing.md").read_text()
    with pipeline.connect(tmp_path / "memory.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1


def test_changed_article_becomes_new_observation_of_same_event(snapshot, fake_model, tmp_path):
    first, _ = pipeline.run(snapshot, tmp_path)
    snapshot["day"] = "2026-10-02"
    snapshot["articles"][0]["text"] = "The Brook bridge reopened on Friday after the collision."
    second, reused = pipeline.run(snapshot, tmp_path)
    assert not reused
    assert len(fake_model) == 2
    assert second["events"][0]["id"] == first["events"][0]["id"]
    assert second["events"][0]["first_seen"] == "2026-10-01"
    assert second["events"][0]["last_seen"] == "2026-10-02"
    assert second["events"][0]["new_quote_count"] == 1
    assert "Continuing event" in pipeline.replay(tmp_path, second["run_id"])


def test_failed_validation_leaves_memory_unchanged(snapshot, fake_model, monkeypatch, tmp_path):
    first, _ = pipeline.run(snapshot, tmp_path)
    snapshot["day"] = "2026-10-02"
    monkeypatch.setattr(pipeline, "run_task", lambda *args, **kwargs: {"events": []})
    with pytest.raises(ValueError):
        pipeline.run(snapshot, tmp_path)
    with pipeline.connect(tmp_path / "memory.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
        assert pipeline.memory(db, "2026-10-02")[0]["id"] == first["events"][0]["id"]
    failures = list((tmp_path / "runs").glob("*/failure.json"))
    assert len(failures) == 1
    assert "exactly once" in failures[0].read_text()


def test_model_failure_is_saved_and_can_be_retried(snapshot, fake_model, monkeypatch, tmp_path):
    original = pipeline.run_task

    def fail(*args, **kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(pipeline, "run_task", fail)
    with pytest.raises(RuntimeError):
        pipeline.run(snapshot, tmp_path)
    monkeypatch.setattr(pipeline, "run_task", original)
    result, reused = pipeline.run(snapshot, tmp_path)
    assert not reused
    assert result["events"]
    assert len(list((tmp_path / "runs").glob("*/input.json"))) == 2


def test_backward_run_is_rejected_before_model(snapshot, fake_model, tmp_path):
    later = deepcopy(snapshot)
    later["day"] = "2026-10-02"
    pipeline.run(later, tmp_path)
    with pytest.raises(ValueError, match="chronological"):
        pipeline.run(snapshot, tmp_path)
    assert len(fake_model) == 1


def test_old_exact_run_still_replays_after_newer_runs(snapshot, fake_model, tmp_path):
    first, _ = pipeline.run(snapshot, tmp_path)
    newer = deepcopy(snapshot)
    newer["day"] = "2026-10-02"
    pipeline.run(newer, tmp_path)
    result, reused = pipeline.run(snapshot, tmp_path)
    assert reused and result == first
    assert len(fake_model) == 2


def test_state_lock_fails_before_model(snapshot, fake_model, tmp_path):
    with pipeline.state_lock(tmp_path):
        with pytest.raises(ValueError, match="another run"):
            pipeline.run(snapshot, tmp_path)
    assert fake_model == []


def test_legacy_database_is_untouched(snapshot, fake_model, tmp_path):
    path = tmp_path / "memory.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE private_data (value TEXT)")
        db.execute("INSERT INTO private_data VALUES ('keep')")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="not a News"):
        pipeline.run(snapshot, tmp_path)
    assert path.read_bytes() == before
    assert not fake_model


def test_failed_artifact_write_never_commits(snapshot, fake_model, monkeypatch, tmp_path):
    original = pipeline._write_json

    def broken(path, value):
        if path.name == "result.json":
            raise OSError("disk full")
        original(path, value)

    monkeypatch.setattr(pipeline, "_write_json", broken)
    with pytest.raises(OSError, match="disk full"):
        pipeline.run(snapshot, tmp_path)
    with pipeline.connect(tmp_path / "memory.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def test_memory_expires_after_window(snapshot, fake_model, tmp_path):
    pipeline.run(snapshot, tmp_path)
    snapshot["day"] = "2026-10-20"
    result, _ = pipeline.run(snapshot, tmp_path)
    assert fake_model[-1]["memory"] == []
    assert result["events"][0]["previous_event_id"] is None


def test_replay_missing_state_does_not_create_files(tmp_path):
    with pytest.raises(ValueError, match="no News state"):
        pipeline.replay(tmp_path, "missing")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("timeout", [0, -1, 1801, float("nan"), float("inf")])
def test_invalid_timeout_never_calls_model(snapshot, fake_model, tmp_path, timeout):
    with pytest.raises(ValueError):
        pipeline.run(snapshot, tmp_path, timeout=timeout)
    assert not fake_model
