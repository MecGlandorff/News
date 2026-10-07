import json
from pathlib import Path

import pytest

from news.cli import main


def test_cli_run_and_offline_story(snapshot, fake_model, tmp_path, capsys):
    source = tmp_path / "articles.json"
    source.write_text(json.dumps(snapshot))
    state = tmp_path / "state"
    assert main(["run", "--input", str(source), "--state", str(state)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert len(result["stories"]) == 1 and not result["reused"]
    assert Path(result["briefing"]).is_file()
    assert main(["story", result["stories"][0], "--state", str(state)]) == 0
    assert "Brook bridge" in capsys.readouterr().out
    assert main(["run", "--input", str(source), "--state", str(state)]) == 0
    assert json.loads(capsys.readouterr().out)["reused"]
    assert len(fake_model) == 1

    assert (
        main(["story", result["stories"][0], "--state", str(state), "--as-of", "2026-09-30"]) == 1
    )
    assert "unknown story ID at this observation date" in capsys.readouterr().err
    assert len(fake_model) == 1


@pytest.mark.parametrize("content", ["not json", "{}", '{"day": null, "articles": []}'])
def test_cli_malformed_input_returns_clean_error(content, tmp_path, capsys):
    source = tmp_path / "bad.json"
    source.write_text(content)
    assert main(["run", "--input", str(source), "--state", str(tmp_path / "state")]) == 1
    output = capsys.readouterr()
    assert output.err.startswith("news:")
    assert "Traceback" not in output.err
    assert not (tmp_path / "state").exists()


def test_cli_invalid_url_type_is_a_clean_error(snapshot, tmp_path, capsys):
    snapshot["articles"][0]["url"] = []
    source = tmp_path / "bad.json"
    source.write_text(json.dumps(snapshot))
    assert main(["run", "--input", str(source), "--state", str(tmp_path / "state")]) == 1
    assert "URL must" in capsys.readouterr().err


def test_fetch_never_overwrites_snapshot(tmp_path, monkeypatch, capsys):
    output = tmp_path / "saved.json"
    output.write_text("keep")
    monkeypatch.setattr("news.cli.feeds.fetch", lambda *args, **kwargs: pytest.fail("network used"))
    assert main(["fetch", "--output", str(output)]) == 1
    assert output.read_text() == "keep"
    assert "already exists" in capsys.readouterr().err


def test_capture_is_separate_from_ai(snapshot, monkeypatch, tmp_path, capsys):
    config = tmp_path / "feeds.json"
    config.write_text("[]")
    output = tmp_path / "capture.json"
    monkeypatch.setattr("news.cli.feeds.fetch", lambda *args, **kwargs: (snapshot, {"feeds": []}))
    monkeypatch.setattr(
        "news.trajectory.run_task", lambda *args, **kwargs: pytest.fail("model used")
    )
    assert main(["fetch", "--feeds", str(config), "--output", str(output)]) == 0
    assert json.loads(output.read_text()) == snapshot
    assert "feeds" in capsys.readouterr().err


def test_cli_missing_input_file(tmp_path, capsys):
    assert main(["run", "--input", str(tmp_path / "missing")]) == 1
    assert "No such file" in capsys.readouterr().err


def test_model_failure_points_to_preserved_artifacts(snapshot, tmp_path, monkeypatch, capsys):
    source = tmp_path / "articles.json"
    source.write_text(json.dumps(snapshot))

    def fail(*args, **kwargs):
        raise RuntimeError("service unavailable")

    monkeypatch.setattr("news.trajectory.run_task", fail)
    assert main(["run", "--input", str(source), "--state", str(tmp_path / "state")]) == 1
    output = capsys.readouterr().err
    assert "service unavailable" in output
    assert "Run artifacts:" in output
    assert list((tmp_path / "state" / "runs").glob("*/failure.json"))


@pytest.mark.parametrize(
    "arguments",
    [["story-run"], ["replay", "old-run"], ["run", "--input", "unused", "--strategy", "staged"]],
)
def test_retired_workflows_are_not_public_commands(arguments):
    with pytest.raises(SystemExit) as exc:
        main(arguments)
    assert exc.value.code == 2
