import json
from copy import deepcopy
from pathlib import Path

import pytest

from evals import run as experiment


@pytest.fixture
def case():
    return experiment.load_cases(Path("evals/cases.json"))[0]


def golden(case):
    articles = {a["id"]: a for a in case["input"]["articles"]}
    return {
        "events": [
            {
                "title": "Synthetic event",
                "article_ids": group,
                "previous_event_id": case["expected"]["continuations"][group[0]],
                "evidence": [{"article_id": a, "quote": articles[a]["text"]} for a in group],
            }
            for group in case["expected"]["groups"]
        ]
    }


def test_rejected_output_retains_actual_quote_errors(case, monkeypatch, tmp_path):
    response = golden(case)
    response["events"][0]["evidence"][0]["quote"] = "A fabricated quote."

    def invalid(payload, strategy, directory, **kwargs):
        (directory / "single").mkdir()
        experiment.write(directory / "single" / "final.json", response)
        raise ValueError("evidence rejected")

    monkeypatch.setattr(experiment, "analyze", invalid)
    report = experiment.run([case], ["single"], tmp_path / "run", repeats=1, max_calls=1)
    trial = report["trials"][0]
    assert "evidence rejected" in trial["error"]
    assert trial["score"]["exact_partition"]
    assert trial["score"]["evidence_quote_errors"] == 1
    assert not trial["score"]["strict_pass"]
    assert report["summary"]["single"]["evidence_quote_errors"] == 1


def test_execution_error_cannot_pass_even_if_raw_output_scores_perfectly(
    case, monkeypatch, tmp_path
):
    def invalid(payload, strategy, directory, **kwargs):
        (directory / "single").mkdir()
        experiment.write(directory / "single" / "final.json", golden(case))
        raise RuntimeError("transport reported failure after a partial response")

    monkeypatch.setattr(experiment, "analyze", invalid)
    report = experiment.run([case], ["single"], tmp_path / "run", repeats=1, max_calls=1)
    assert report["trials"][0]["score"]["valid"]
    assert not report["trials"][0]["score"]["strict_pass"]
    assert report["summary"]["single"]["errors"] == 1


def test_call_budget_rejects_before_any_execution(case, monkeypatch, tmp_path):
    monkeypatch.setattr(experiment, "analyze", lambda *args, **kwargs: pytest.fail("spent a call"))
    with pytest.raises(ValueError, match="needs at most 3 calls"):
        experiment.run([case], ["single", "staged"], tmp_path / "run", repeats=1, max_calls=2)
    assert not (tmp_path / "run").exists()


def test_repeats_and_reports_do_not_hide_failed_trials(case, monkeypatch, tmp_path):
    calls = []

    def alternate(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("rate limited")
        return golden(case)

    monkeypatch.setattr(experiment, "analyze", alternate)
    report = experiment.run([case], ["single"], tmp_path / "run", repeats=2, max_calls=2)
    assert report["completed"]
    assert report["summary"]["single"]["trials"] == 2
    assert report["summary"]["single"]["strict_passes"] == 1
    assert json.loads((tmp_path / "run" / "report.json").read_text()) == report


def test_gold_labels_are_validated_before_run(case, tmp_path):
    broken = deepcopy(case)
    broken["expected"]["groups"].append([])
    path = tmp_path / "bad.json"
    experiment.write(path, [broken])
    with pytest.raises(ValueError, match="Invalid evaluation labels"):
        experiment.load_cases(path)


def test_case_ids_cannot_escape_output_directory(case, tmp_path):
    case["id"] = "../escape"
    path = tmp_path / "bad.json"
    experiment.write(path, [case])
    with pytest.raises(ValueError, match="filesystem-safe"):
        experiment.load_cases(path)
