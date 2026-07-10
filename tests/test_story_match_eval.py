import json

import pytest

from evals import run_story_match_eval as match_eval


def _story_case(case_id, observed, expected):
    return {
        "case_id": case_id,
        "case_type": "story_match",
        "today_label": f"today {case_id}",
        "candidate_label": f"candidate {case_id}",
        "observed_decision": {
            "accepted": observed,
            "relationship": "same_event" if observed else "uncertain",
            "confidence": "high" if observed else "low",
        },
        "expected_decision": {"accepted": expected},
    }


def _arc_case(case_id, observed, expected):
    return {
        "case_id": case_id,
        "case_type": "arc_assignment",
        "today_label": f"today {case_id}",
        "candidate_arc_label": f"arc {case_id}",
        "observed_decision": {
            "accepted": observed,
            "relationship": "same_arc" if observed else "uncertain",
            "confidence": "high" if observed else "low",
        },
        "expected_decision": {"accepted": expected},
    }


def test_story_match_eval_scores_false_merge_split_and_false_arc():
    report = match_eval.run_eval(
        [
            _story_case("correct-match", True, True),
            _story_case("correct-new", False, False),
            _story_case("false-merge", True, False),
            _story_case("false-split", False, True),
        ],
        [
            _arc_case("correct-arc", True, True),
            _arc_case("false-arc", True, False),
            _arc_case("missed-arc", False, True),
        ],
    )

    story = report["summary"]["story_match"]
    arc = report["summary"]["arc_assignment"]

    assert story["cases"] == 4
    assert story["false_merges"] == 1
    assert story["false_splits"] == 1
    assert story["false_merge_rate"] == pytest.approx(1 / 2)
    assert story["false_split_rate"] == pytest.approx(1 / 2)
    assert arc["false_arcs"] == 1
    assert arc["missed_arcs"] == 1
    assert arc["false_arc_rate"] == pytest.approx(1 / 2)
    assert arc["missed_arc_rate"] == pytest.approx(1 / 2)


def test_story_match_eval_loads_default_datasets():
    story_cases = match_eval.load_cases(match_eval.DEFAULT_STORY_DATASET, "story_match")
    arc_cases = match_eval.load_cases(match_eval.DEFAULT_ARC_DATASET, "arc_assignment")

    assert len(story_cases) == 10
    assert len(arc_cases) == 10
    assert {case["case_type"] for case in story_cases} == {"story_match"}
    assert {case["case_type"] for case in arc_cases} == {"arc_assignment"}


def test_story_match_eval_rejects_invalid_case(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text(
        json.dumps({
            "case_id": "bad",
            "case_type": "story_match",
            "today_label": "Today",
            "candidate_label": "Candidate",
            "observed_decision": {"accepted": "yes"},
            "expected_decision": {"accepted": False},
        }) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="observed_decision.accepted"):
        match_eval.load_cases(path, "story_match")


def test_story_match_eval_writes_report(tmp_path):
    report = match_eval.run_eval([_story_case("ok", True, True)], [])
    output_path = match_eval.write_report(report, tmp_path / "story_report.json")

    assert output_path.exists()
    loaded = json.loads(output_path.read_text(encoding="utf-8"))
    assert loaded["mode"] == "executable_acceptance_gate_replay"
    assert loaded["summary"]["story_match"]["cases"] == 1


def test_story_match_eval_summary_names_representative_failures():
    report = match_eval.run_eval(
        [_story_case("false-merge", True, False)],
        [_arc_case("false-arc", True, False)],
    )

    summary = match_eval.format_summary(report)

    assert "false merge rate" in summary
    assert "false arc rate" in summary
    assert "false-merge [false_merge]" in summary
    assert "false-arc [false_arc]" in summary


def test_story_match_eval_cli_no_write(tmp_path, capsys):
    story_path = tmp_path / "story.jsonl"
    arc_path = tmp_path / "arc.jsonl"
    story_path.write_text(json.dumps(_story_case("story", True, True)) + "\n", encoding="utf-8")
    arc_path.write_text(json.dumps(_arc_case("arc", True, False)) + "\n", encoding="utf-8")

    report = match_eval.main([
        "--story-dataset",
        str(story_path),
        "--arc-dataset",
        str(arc_path),
        "--no-write",
    ])

    output = capsys.readouterr().out
    assert "Story matching eval" in output
    assert "Report written:" not in output
    assert report["case_count"] == 2
