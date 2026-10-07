import contextlib
import sqlite3

import pytest

from news import trajectory
from news.domain import canonical


@pytest.fixture
def indexed_state(monkeypatch, tmp_path, supported_coherence):
    articles = [
        {
            "id": f"source-{number}",
            "source": "Example News",
            "url": f"https://example.test/{number}",
            "published_at": "2026-01-01T08:00:00Z",
            "title": f"Archive marker{number}",
            "text": f"Marker{number} report. "
            + " ".join(f"term{number}{word:04d}" for word in range(500)),
        }
        for number in range(3)
    ]

    def fake_model(task, payload, directory, **options):
        if task == "coherence":
            return supported_coherence(payload)
        return {
            "stories": [
                {
                    "story_id": None,
                    "title": article["title"],
                    "events": [
                        {
                            "event_id": None,
                            "title": article["title"],
                            "identity_uncertain": False,
                            "continuity_evidence": [],
                            "observations": [
                                {
                                    "change": "unclear",
                                    "summary": article["text"].split(". ")[0] + ".",
                                    "unresolved": None,
                                    "article_ids": [article["id"]],
                                    "evidence": [
                                        {
                                            "capture_id": article["capture_id"],
                                            "quote": article["text"].split(". ")[0] + ".",
                                        }
                                    ],
                                    "comparison_evidence": [],
                                }
                            ],
                        }
                    ],
                }
                for article in payload["articles"]
            ]
        }

    monkeypatch.setattr(trajectory, "run_task", fake_model)
    trajectory.run({"day": "2026-01-01", "articles": articles}, tmp_path)
    query = {
        "day": "2026-02-01",
        "articles": [dict(articles[0], id="query", url="https://example.test/query")],
    }
    with contextlib.closing(trajectory.connect(tmp_path / "journal.sqlite3")) as db:
        trajectory.retrieve(db, query)
    return tmp_path / "journal.sqlite3", query


def test_repeated_rebuilds_keep_one_index_segment_and_the_same_source_context(indexed_state):
    path, query = indexed_state
    with contextlib.closing(trajectory.connect(path)) as db:
        journal = db.execute("SELECT input_json, result_json FROM runs").fetchall()
        expected = None
        for _ in range(5):
            payload, diagnostics = trajectory.retrieve(db, query)
            actual = canonical([payload, diagnostics])
            if expected is None:
                expected = actual
            assert actual == expected
            assert db.execute("SELECT COUNT(*) FROM source_search").fetchone()[0] == 3
            # FTS5 optimize merges the index into one tree. Inspect its real
            # storage rather than asserting that a particular SQL call occurred.
            assert (
                db.execute("SELECT COUNT(DISTINCT segid) FROM source_search_idx").fetchone()[0] == 1
            )
        source = next(item for item in payload["prior_sources"] if item["id"] == "source-0")
        assert source["text"] == query["articles"][0]["text"]
        assert db.execute("SELECT input_json, result_json FROM runs").fetchall() == journal


def test_compaction_failure_rolls_back_the_derived_index_without_changing_journal(indexed_state):
    path, query = indexed_state

    class FailingCompaction(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if sql.startswith("INSERT INTO source_search(") and "optimize" in sql:
                raise sqlite3.OperationalError("simulated compaction failure")
            return super().execute(sql, parameters)

    with contextlib.closing(sqlite3.connect(path, factory=FailingCompaction)) as db:
        before = db.execute("SELECT * FROM source_search ORDER BY capture_id").fetchall()
        journal = db.execute("SELECT input_json, result_json FROM runs").fetchall()
        # This as-of projection would clear every indexed row. A failed
        # compaction must roll that deletion back with the rebuild transaction.
        earlier = dict(query, day="2025-12-31")
        with pytest.raises(sqlite3.OperationalError, match="compaction failure"):
            trajectory.retrieve(db, earlier)
        assert db.execute("SELECT * FROM source_search ORDER BY capture_id").fetchall() == before
        assert (
            db.execute(
                "SELECT COUNT(*) FROM source_search WHERE source_search MATCH 'archive'"
            ).fetchone()[0]
            == 3
        )
        assert db.execute("SELECT input_json, result_json FROM runs").fetchall() == journal
