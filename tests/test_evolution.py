import copy
from types import SimpleNamespace

import pytest

from evals import evolution
from evals.historical import write
from evals.replay import read, sha256


@pytest.fixture
def corpus(tmp_path):
    prepared, rubric, review = (
        tmp_path / "prepared",
        tmp_path / "rubric.json",
        tmp_path / "review.json",
    )
    batches = []
    for number, day in enumerate(("2026-05-01", "2026-05-20"), 1):
        name = f"{number:02d}-{day}.json"
        write(
            prepared / name,
            {
                "day": day,
                "articles": [
                    {
                        "id": "article",
                        "title": "Bridge permit",
                        "text": f"Permit report observed {day}.",
                        "source": "Synthetic",
                        "url": "https://example.test/permit",
                        "published_at": day + "T10:00:00Z",
                    }
                ],
            },
        )
        batches.append({"file": name, "day": day, "articles": 1, "sha256": sha256(prepared / name)})
    write(prepared / "manifest.json", {"batches": batches})
    write(
        rubric,
        {
            "prepared_manifest_sha256": sha256(prepared / "manifest.json"),
            "applicable_original_questions": [
                {
                    "id": "retained-origin",
                    "required_article_refs": [
                        {"day": "2026-05-01", "article_id": "article"},
                        {"day": "2026-05-20", "article_id": "article"},
                    ],
                }
            ],
        },
    )
    write(
        review,
        {
            "original_hashes": {
                "rubric": sha256(rubric),
                "manifest": sha256(prepared / "manifest.json"),
            }
        },
    )
    return prepared, rubric, review, tmp_path / "output"


def fake_model(monkeypatch, *, fail_at=None, interruption=False):
    calls = []
    monkeypatch.setattr(
        evolution.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="codex test")
    )

    def run(engine, snapshot, state, timeout):
        calls.append((engine, copy.deepcopy(snapshot), timeout))
        directory = state / "runs" / f"run-{len(calls)}"
        write(directory / "input.json", dict(snapshot, memory=[]))
        failed = len(calls) == fail_at
        write(
            directory / "model/metadata.json",
            {
                "status": "failed" if failed else "ok",
                "usage": None if failed else {"input_tokens": 100, "output_tokens": 20},
            },
        )
        if failed:
            raise KeyboardInterrupt() if interruption else RuntimeError("failed model call")
        (directory / "briefing.md").write_text(f"# Observed {snapshot['day']}\n", encoding="utf-8")
        return {"run_id": directory.name, "stories": [{"id": "s-bridge"}]}, False

    monkeypatch.setattr(evolution, "execute", run)
    monkeypatch.setattr(
        evolution, "render_story", lambda *a: "# Bridge\nBoth dated developments.\n"
    )
    return calls


def test_replay_freezes_provenance_and_reader_outputs_without_rubric_leak(corpus, monkeypatch):
    calls = fake_model(monkeypatch)
    report = evolution.evaluate(*corpus, engine="stories", max_calls=2, timeout=23)
    assert report["completed"] and report["assigned_records"] == 2
    assert len(calls) == 2 and all(set(c[1]) == {"day", "articles"} for c in calls)
    assert [c[1]["day"] for c in calls] == ["2026-05-01", "2026-05-20"]
    assert all(c[0] == "stories" and c[2] == 23 for c in calls)
    assert report["reported_usage"] == {"input_tokens": 200, "output_tokens": 40}
    assert report["calls_without_usage"] == 0
    assert report["semantic_review"].startswith("Pending")
    assert report["reader_outputs"] == ["daily-briefings.md", "timelines/s-bridge.md"]
    for name, digest in report["reader_output_sha256"].items():
        assert sha256(corpus[3] / name) == digest
    manifest = read(corpus[3] / "manifest.json")
    assert manifest["rubric_sha256"] == sha256(corpus[1])
    assert manifest["review_sha256"] == sha256(corpus[2])


def test_failure_preserves_partial_run_and_unknown_usage_without_retry(corpus, monkeypatch):
    calls = fake_model(monkeypatch, fail_at=2)
    report = evolution.evaluate(*corpus, engine="stories", max_calls=2)
    assert not report["completed"] and len(calls) == 2
    assert report["assigned_records"] == 1
    assert len(report["failures"]) == 1
    assert report["calls_without_usage"] == 1
    assert report["reported_usage"] == {"input_tokens": 100, "output_tokens": 20}
    assert "2026-05-01" in (corpus[3] / "daily-briefings.md").read_text()


def test_interrupt_writes_partial_report_then_propagates(corpus, monkeypatch):
    fake_model(monkeypatch, fail_at=1, interruption=True)
    with pytest.raises(KeyboardInterrupt):
        evolution.evaluate(*corpus, engine="stories", max_calls=2)
    report = read(corpus[3] / "report.json")
    assert not report["completed"] and report["assigned_records"] == 0
    assert report["failures"][0]["error"].startswith("KeyboardInterrupt")


@pytest.mark.parametrize(
    "invalid", ["budget", "source_hash", "rubric_hash", "review_hash", "reference", "chronology"]
)
def test_invalid_preflight_never_calls_model_or_creates_output(corpus, monkeypatch, invalid):
    calls = fake_model(monkeypatch)
    prepared, rubric, review, output = corpus
    if invalid == "source_hash":
        path = prepared / read(prepared / "manifest.json")["batches"][0]["file"]
        path.write_text(path.read_text() + " ")
    elif invalid == "rubric_hash":
        write(prepared / "manifest.json", {"batches": []})
    elif invalid == "review_hash":
        write(review, {"original_hashes": {}})
    elif invalid == "reference":
        document = read(rubric)
        document["applicable_original_questions"][0]["required_article_refs"][0]["article_id"] = (
            "absent"
        )
        write(rubric, document)
        write(
            review,
            {
                "original_hashes": {
                    "rubric": sha256(rubric),
                    "manifest": sha256(prepared / "manifest.json"),
                }
            },
        )
    elif invalid == "chronology":
        document = read(prepared / "manifest.json")
        document["batches"].reverse()
        write(prepared / "manifest.json", document)
        criteria = read(rubric)
        criteria["prepared_manifest_sha256"] = sha256(prepared / "manifest.json")
        write(rubric, criteria)
        write(
            review,
            {
                "original_hashes": {
                    "rubric": sha256(rubric),
                    "manifest": sha256(prepared / "manifest.json"),
                }
            },
        )
    with pytest.raises(ValueError):
        evolution.evaluate(*corpus, engine="stories", max_calls=1 if invalid == "budget" else 2)
    assert not calls and not output.exists()


def test_reader_export_error_is_preserved_as_failure(corpus, monkeypatch):
    fake_model(monkeypatch)

    def unavailable(*args):
        raise ValueError("cannot render accepted story")

    monkeypatch.setattr(evolution, "render_story", unavailable)
    report = evolution.evaluate(*corpus, engine="stories", max_calls=2)
    assert not report["completed"]
    assert report["failures"][-1]["phase"] == "timeline_export"
    assert report["assigned_records"] == 2
