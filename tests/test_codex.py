"""Real subprocess contract tests; never use the network or installed Codex."""

import json
import os
import signal
import sys
import time
from copy import deepcopy
from pathlib import Path

import pytest

from news import codex

RESULT = {
    "stories": [
        {
            "story_id": None,
            "title": "Bridge closure",
            "events": [
                {
                    "event_id": None,
                    "title": "Bridge closure",
                    "identity_uncertain": False,
                    "continuity_evidence": [],
                    "observations": [
                        {
                            "change": "new_development",
                            "summary": "The bridge closed.",
                            "unresolved": None,
                            "article_ids": ["a1"],
                            "evidence": [{"capture_id": "c-a1", "quote": "The bridge closed."}],
                            "comparison_evidence": [],
                        }
                    ],
                }
            ],
        }
    ]
}
PAYLOAD = {
    "day": "2026-10-01",
    "articles": [
        {
            "id": "a1",
            "source": "Daily News",
            "url": "https://example.test/a1",
            "published_at": "2026-10-01T12:00:00Z",
            "title": "Bridge closure",
            "text": "The bridge closed.",
            "capture_id": "c-a1",
            "observed_on": "2026-10-01",
        }
    ],
    "stories": [],
    "prior_sources": [],
}


@pytest.fixture
def fake_codex(tmp_path):
    def make(body):
        executable = tmp_path / "fake codex"
        executable.write_text(
            f"#!{sys.executable}\n"
            "import json, os, signal, subprocess, sys, time\n"
            "from pathlib import Path\n"
            "final = Path(sys.argv[sys.argv.index('--output-last-message') + 1])\n"
            "prompt = sys.stdin.read()\n"
            "(final.parent / 'received.json').write_text(json.dumps({"
            "'argv': sys.argv, 'prompt': prompt, 'cwd': os.getcwd()}))\n" + body + "\n",
            encoding="utf-8",
        )
        executable.chmod(0o700)
        return str(executable)

    return make


def write_result(result=RESULT):
    return f"final.write_text({json.dumps(json.dumps(result))}, encoding='utf-8')\n"


def metadata(directory):
    return json.loads((directory / "metadata.json").read_text())


def test_success_sends_stdin_and_archives_configuration(tmp_path, fake_codex):
    executable = fake_codex(
        write_result()
        + "print(json.dumps({'type': 'thread.started', 'thread_id': 'thread1'}))\n"
        + "print(json.dumps({'type': 'turn.completed', 'usage': "
        + "{'input_tokens': 120, 'cached_input_tokens': 20, 'output_tokens': 40}}))\n"
    )
    directory = tmp_path / "call"
    result = codex.run_task("trajectory", PAYLOAD, directory, executable=executable)

    assert result == RESULT
    assert json.loads((directory / "input.json").read_text()) == PAYLOAD
    received = json.loads((directory / "received.json").read_text())
    assert received["prompt"] == (directory / "prompt.md").read_text()
    assert received["argv"][-1] == "-"
    assert "--ignore-user-config" in received["argv"]
    assert "--ignore-rules" in received["argv"]
    assert "--strict-config" in received["argv"]
    assert "--ephemeral" in received["argv"]
    assert received["argv"][received["argv"].index("--model") + 1] == "gpt-6-astra"
    assert received["argv"][received["argv"].index("--sandbox") + 1] == "read-only"
    assert 'model_reasoning_effort="medium"' in received["argv"]
    assert 'web_search="disabled"' in received["argv"]
    assert "features.shell_tool=false" in received["argv"]
    assert "features.apps=false" in received["argv"]
    assert "features.plugins=false" in received["argv"]
    assert "project_doc_max_bytes=0" in received["argv"]
    assert received["cwd"] != str(Path.cwd())
    assert not Path(received["cwd"]).exists()
    assert (directory / "schema.json").read_text() == (
        codex.TASKS_DIR / "trajectory.schema.json"
    ).read_text()
    saved = metadata(directory)
    assert saved["status"] == "ok"
    assert saved["exit_code"] == 0
    assert saved["process_started"] is True
    assert saved["error"] is None
    assert saved["duration_seconds"] > 0
    assert saved["usage"] == {
        "input_tokens": 120,
        "cached_input_tokens": 20,
        "output_tokens": 40,
    }
    assert saved["thread_id"] == "thread1"


def test_article_content_never_becomes_a_shell_command(tmp_path, fake_codex):
    marker = tmp_path / "must-not-exist"
    payload = {"article": f"$(touch {marker}) `touch {marker}`; --output-last-message bad; café"}
    executable = fake_codex(write_result())
    directory = tmp_path / "call with spaces"
    codex.run_task("trajectory", payload, directory, executable=executable)
    received = json.loads((directory / "received.json").read_text())
    assert json.dumps(payload, ensure_ascii=False) in received["prompt"]
    assert payload["article"] not in received["argv"]
    assert not marker.exists()


def test_nonzero_exit_rejects_even_a_valid_final_and_retains_diagnostics(tmp_path, fake_codex):
    executable = fake_codex(
        write_result() + "print('service failed', file=sys.stderr)\nsys.exit(7)"
    )
    directory = tmp_path / "call"
    with pytest.raises(codex.CodexError, match="status 7"):
        codex.run_task("trajectory", PAYLOAD, directory, executable=executable)
    assert "service failed" in (directory / "stderr.txt").read_text()
    assert json.loads((directory / "final.json").read_text()) == RESULT
    assert metadata(directory)["status"] == "failed"
    assert metadata(directory)["exit_code"] == 7


def test_missing_executable_still_has_request_and_failure_artifacts(tmp_path):
    directory = tmp_path / "call"
    with pytest.raises(codex.CodexError, match="executable not found"):
        codex.run_task("trajectory", PAYLOAD, directory, executable=str(tmp_path / "missing"))
    assert (directory / "prompt.md").is_file()
    assert (directory / "schema.json").is_file()
    assert (directory / "config.json").is_file()
    assert (directory / "events.jsonl").is_file()
    assert (directory / "stderr.txt").is_file()
    saved = metadata(directory)
    assert saved["status"] == "failed"
    assert saved["usage"] is None
    assert saved["exit_code"] is None
    assert saved["process_started"] is False


def test_os_launch_failure_is_not_counted_as_a_started_model(tmp_path, monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError("simulated launch denial")

    monkeypatch.setattr(codex.subprocess, "Popen", denied)
    directory = tmp_path / "call"
    with pytest.raises(codex.CodexError, match="launch denial"):
        codex.run_task("trajectory", PAYLOAD, directory, executable=sys.executable)
    saved = metadata(directory)
    assert "argv" in saved and saved["process_started"] is False
    assert saved["usage"] is None


@pytest.mark.parametrize("body", ["pass", "final.touch()"])
def test_missing_or_empty_final_is_a_failure(tmp_path, fake_codex, body):
    directory = tmp_path / "call"
    with pytest.raises(codex.CodexError, match="no final output"):
        codex.run_task("trajectory", PAYLOAD, directory, executable=fake_codex(body))
    assert metadata(directory)["status"] == "failed"


@pytest.mark.parametrize(
    "body",
    [
        "final.write_text('not JSON')",
        "final.write_text('{} trailing')",
        "final.write_bytes(bytes([255, 254]))",
    ],
)
def test_malformed_json_is_rejected_and_preserved(tmp_path, fake_codex, body):
    directory = tmp_path / "call"
    with pytest.raises(codex.CodexError, match="not valid UTF-8 JSON"):
        codex.run_task("trajectory", PAYLOAD, directory, executable=fake_codex(body))
    assert (directory / "final.json").stat().st_size > 0
    assert metadata(directory)["status"] == "failed"


@pytest.mark.parametrize(
    "result",
    [
        [],
        {},
        {"stories": "wrong type"},
        {"stories": [], "extra": True},
        {"stories": [{"title": "Missing fields"}]},
        {"stories": [{**RESULT["stories"][0], "story_id": 5}]},
        {"stories": [{**RESULT["stories"][0], "events": []}]},
        {"stories": [{**RESULT["stories"][0], "title": ""}]},
    ],
)
def test_schema_mismatch_is_rejected(tmp_path, fake_codex, result):
    directory = tmp_path / "call"
    with pytest.raises(codex.CodexError, match="violates schema"):
        codex.run_task(
            "trajectory", PAYLOAD, directory, executable=fake_codex(write_result(result))
        )
    assert metadata(directory)["status"] == "failed"


def test_empty_batch_response_is_allowed(tmp_path, fake_codex):
    result = codex.run_task(
        "trajectory",
        {"articles": [], "stories": [], "prior_sources": []},
        tmp_path / "call",
        executable=fake_codex(write_result({"stories": []})),
    )
    assert result == {"stories": []}


def test_shape_validation_does_not_claim_source_validation(tmp_path, fake_codex):
    # Semantic validation belongs to the caller, which retains original articles.
    invented = deepcopy(RESULT)
    invented["stories"][0]["events"][0]["observations"][0]["article_ids"] = ["unknown"]
    result = codex.run_task(
        "trajectory",
        PAYLOAD,
        tmp_path / "call",
        executable=fake_codex(write_result(invented)),
    )
    assert result == invented


def test_existing_artifacts_are_never_reused_or_overwritten(tmp_path, fake_codex):
    directory = tmp_path / "call"
    directory.mkdir()
    (directory / "final.json").write_text("old result")
    with pytest.raises(FileExistsError):
        codex.run_task("trajectory", PAYLOAD, directory, executable=fake_codex(write_result()))
    assert (directory / "final.json").read_text() == "old result"
    assert not (directory / "received.json").exists()


@pytest.mark.parametrize(
    "task", ["../trajectory", "", "unknown", "trajectory.md", "single", "extract", "group"]
)
def test_only_known_task_names_are_allowed(tmp_path, task):
    with pytest.raises(ValueError, match="Unknown task"):
        codex.run_task(task, PAYLOAD, tmp_path / "call")
    assert not (tmp_path / "call").exists()


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_timeout_must_be_finite_and_positive(tmp_path, timeout):
    with pytest.raises(ValueError, match="finite positive"):
        codex.run_task("trajectory", PAYLOAD, tmp_path / "call", timeout=timeout)
    assert not (tmp_path / "call").exists()


def test_unknown_usage_is_not_reported_as_zero(tmp_path, fake_codex):
    directory = tmp_path / "call"
    executable = fake_codex(write_result() + "print('partial non-JSON')\nprint('[]')")
    codex.run_task("trajectory", PAYLOAD, directory, executable=executable)
    assert metadata(directory)["usage"] is None
    assert metadata(directory)["turn_usage"] == []
    assert "partial non-JSON" in (directory / "events.jsonl").read_text()


def test_usage_sums_completed_turns_and_preserves_original_records(tmp_path, fake_codex):
    records = [
        {"input_tokens": 12, "output_tokens": 4, "cached_input_tokens": 2},
        {"input_tokens": 3, "output_tokens": 2, "new_field": "unknown"},
    ]
    body = write_result() + "\n".join(
        f"print({json.dumps(json.dumps({'type': 'turn.completed', 'usage': record}))})"
        for record in records
    )
    directory = tmp_path / "call"
    codex.run_task("trajectory", PAYLOAD, directory, executable=fake_codex(body))
    saved = metadata(directory)
    assert saved["turn_usage"] == records
    assert saved["usage"] == {"input_tokens": 15, "output_tokens": 6, "cached_input_tokens": 2}


def test_missing_task_asset_is_recorded_as_failed_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(codex, "TASKS_DIR", tmp_path / "missing-tasks")
    directory = tmp_path / "call"
    with pytest.raises(codex.CodexError, match="task failed"):
        codex.run_task("trajectory", PAYLOAD, directory)
    assert metadata(directory)["status"] == "failed"
    assert (directory / "input.json").is_file()


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group behavior")
def test_timeout_kills_descendants_and_retains_partial_output(tmp_path, fake_codex):
    child_code = (
        "import signal, time; from pathlib import Path; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "time.sleep(1.5); Path('escaped-child').write_text('bad'); time.sleep(10)"
    )
    executable = fake_codex(
        "child = subprocess.Popen([sys.executable, '-c', " + repr(child_code) + "], "
        "cwd=final.parent)\n"
        "(final.parent / 'child.pid').write_text(str(child.pid))\n"
        "print('partial event', flush=True)\n"
        "print('waiting', file=sys.stderr, flush=True)\n"
        "time.sleep(30)"
    )
    directory = tmp_path / "call"
    with pytest.raises(codex.CodexError, match="timed out"):
        codex.run_task("trajectory", PAYLOAD, directory, timeout=0.6, executable=executable)
    saved = metadata(directory)
    assert saved["status"] == "failed"
    assert saved["exit_code"] == -signal.SIGTERM
    assert saved["duration_seconds"] < 5
    assert "partial event" in (directory / "events.jsonl").read_text()
    assert "waiting" in (directory / "stderr.txt").read_text()
    # A child that ignores SIGTERM would write this marker if the group were not
    # also killed after the direct parent exits.
    time.sleep(1.1)
    assert not (directory / "escaped-child").exists()


def test_timeout_escalates_when_direct_process_ignores_sigterm(tmp_path, fake_codex):
    executable = fake_codex("signal.signal(signal.SIGTERM, signal.SIG_IGN)\ntime.sleep(30)")
    directory = tmp_path / "call"
    with pytest.raises(codex.CodexError, match="timed out"):
        codex.run_task("trajectory", PAYLOAD, directory, timeout=0.4, executable=executable)
    assert metadata(directory)["duration_seconds"] < 5
    assert metadata(directory)["exit_code"] != 0
