import json
import sqlite3

import pytest

from evals import historical


def article(number=1):
    return {
        "id": f"a{number}",
        "occurrence_id": f"o{number}",
        "source": "Archive News",
        "url": f"https://example.test/{number}",
        "published_at": "Tue, 21 Jul 2026 08:00:00 GMT",
        "title": "A bridge <b>closes</b>",
        "description": "Inspectors found &amp; reported damage.",
        "text": "LATER FULL BODY MUST NOT LEAK",
        "story_label": "MODEL CLASSIFICATION MUST NOT LEAK",
        "theme": "Politics",
        "importance": 9,
    }


def case():
    return {
        "case_id": "follow-up",
        "layer": "story",
        "today_date": "2026-07-22",
        "today_article_id": "current",
        "candidate_date": "2026-07-21",
        "candidate_article_id": "prior",
        "candidate_article_ids": ["alias"],
        "expected_accepted": True,
        "review_note": "Same bridge closure",
    }


def test_export_uses_only_captured_rss_and_normalizes_timestamp():
    result = historical.snapshot_article(article())
    assert set(result) == {"id", "source", "url", "published_at", "title", "text"}
    assert result["published_at"] == "2026-07-21T08:00:00+00:00"
    assert result["text"] == "A bridge closes\n\nInspectors found & reported damage."
    assert "MUST NOT LEAK" not in json.dumps(result)


def test_prepare_preserves_every_article_in_bounded_ordered_batches(tmp_path):
    archive, destination = tmp_path / "archive", tmp_path / "prepared"
    raw = [article(n) for n in range(78)]
    historical.write(archive / "data/daily/2026-07-21/articles.json", raw)
    manifest = historical.prepare(archive, destination)
    assert [batch["articles"] for batch in manifest["batches"]] == [50, 28]
    exported = [
        item["id"]
        for batch in manifest["batches"]
        for item in json.loads((destination / batch["file"]).read_text())["articles"]
    ]
    assert exported == [item["id"] for item in raw]
    with pytest.raises(ValueError, match="already exists"):
        historical.prepare(archive, destination)


def test_invalid_article_fails_without_partial_export(tmp_path):
    broken = article(2)
    broken["published_at"] = "2026-07-23T00:00:00Z"
    historical.write(tmp_path / "data/daily/2026-07-21/articles.json", [article(), broken])
    with pytest.raises(ValueError, match="after the snapshot"):
        historical.prepare(tmp_path, tmp_path / "prepared")
    assert not (tmp_path / "prepared").exists()


def test_comparison_accepts_alias_but_missing_candidate_cannot_pass():
    assignments = {
        ("2026-07-22", "current"): "e-2",
        ("2026-07-21", "prior"): "e-1",
        ("2026-07-21", "alias"): "e-2",
    }
    assert historical.compare(assignments, [case()])[0]["correct"]
    del assignments[("2026-07-21", "alias")]
    result = historical.compare(assignments, [case()])[0]
    assert result["missing_assignment"]
    assert result["accepted"] is None
    assert not result["correct"]


def test_baseline_uses_history_and_rejects_ambiguous_assignments(tmp_path):
    historical.write(tmp_path / "data/daily/2026-07-21/articles.json", [article()])
    with sqlite3.connect(tmp_path / "source-archive.db") as db:
        db.executescript("""
            CREATE TABLE occurrence_assignment_history
                (occurrence_id TEXT, run_id INTEGER, story_id INTEGER);
            CREATE TABLE runs (run_id INTEGER, run_date TEXT, git_sha TEXT, status TEXT);
            CREATE TABLE occurrence_assignments (occurrence_id TEXT, story_id INTEGER);
            INSERT INTO occurrence_assignment_history VALUES ('o1', 33, 100);
            INSERT INTO occurrence_assignments VALUES ('o1', 999);
            INSERT INTO runs VALUES (33, '2026-07-21', 'original-sha', 'ok');
        """)
    review = case() | {
        "today_date": "2026-07-21",
        "today_article_id": "a1",
        "candidate_article_id": "a1",
        "candidate_article_ids": [],
    }
    baseline = historical.historical_baseline(tmp_path, [review])
    assert baseline["scored_cases"][0]["current_event"] == "100"
    assert baseline["runs"][0]["git_sha"] == "original-sha"
    with sqlite3.connect(tmp_path / "source-archive.db") as db:
        db.execute("UPDATE occurrence_assignment_history SET story_id=NULL")
    with pytest.raises(ValueError, match="no story assignment"):
        historical.historical_baseline(tmp_path, [review])
    with sqlite3.connect(tmp_path / "source-archive.db") as db:
        db.execute("UPDATE occurrence_assignment_history SET story_id=100")
        db.execute("INSERT INTO occurrence_assignment_history VALUES ('o1', 34, 200)")
    with pytest.raises(ValueError, match="ambiguous or missing"):
        historical.historical_baseline(tmp_path, [review])


def test_budget_rejected_before_model_calls(tmp_path, monkeypatch):
    historical.write(tmp_path / "prepared/manifest.json", {"batches": [{}, {}]})
    monkeypatch.setattr(historical, "run", lambda *a, **kw: pytest.fail("spent a model call"))
    with pytest.raises(ValueError, match="call budget"):
        historical.evaluate(tmp_path, tmp_path / "prepared", tmp_path / "out", max_calls=1)
    assert not (tmp_path / "out").exists()
