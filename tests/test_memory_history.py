from copy import deepcopy

import pytest

from news import pipeline


def isolated_events(task, payload, directory, **kwargs):
    return {
        "events": [
            {
                "title": article["title"],
                "article_ids": [article["id"]],
                "previous_event_id": None,
                "evidence": [{"article_id": article["id"], "quote": article["text"]}],
            }
            for article in payload["articles"]
        ]
    }


def many_articles(snapshot, count, prefix, text="A distinct captured report."):
    return {
        "day": snapshot["day"],
        "articles": [
            dict(
                snapshot["articles"][0],
                id=f"{prefix}-{n}",
                url=f"https://example.test/{prefix}/{n}",
                text=text,
            )
            for n in range(count)
        ],
    }


def test_all_recent_events_survive_more_than_thirty_observations(snapshot, monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "run_task", isolated_events)
    result, _ = pipeline.run(many_articles(snapshot, 40, "event"), tmp_path)
    with pipeline.connect(tmp_path / "memory.sqlite3") as db:
        memory = pipeline.memory(db, snapshot["day"])
    assert {event["id"] for event in memory} == {event["id"] for event in result["events"]}
    assert len(memory) == 40


def test_history_keeps_old_anchor_without_changing_latest_quote_count(
    snapshot, fake_model, tmp_path
):
    original = deepcopy(snapshot)
    pipeline.run(snapshot, tmp_path)
    snapshot["day"] = "2026-10-02"
    snapshot["articles"][0]["text"] = "Crowds gathered near the bridge."
    pipeline.run(snapshot, tmp_path)
    snapshot["day"] = "2026-10-03"
    snapshot["articles"][0]["text"] = original["articles"][0]["text"]
    result, _ = pipeline.run(snapshot, tmp_path)
    prior = fake_model[-1]["memory"][0]
    assert prior["evidence"][0]["quote"] == "Crowds gathered near the bridge."
    assert prior["history"][0]["quote"] == original["articles"][0]["text"]
    assert prior["history"][0]["observed_on"] == "2026-10-01"
    assert prior["history"][0]["url"] == original["articles"][0]["url"]
    # The quote existed earlier, but differs from the immediately previous observation.
    assert result["events"][0]["new_quote_count"] == 1


def test_reused_article_id_and_equal_words_keep_distinct_source_provenance(
    snapshot, fake_model, tmp_path
):
    snapshot["articles"][0]["url"] = "https://one.test/article"
    pipeline.run(snapshot, tmp_path)
    snapshot["articles"][0]["url"] = "https://two.test/article"
    pipeline.run(snapshot, tmp_path)
    snapshot["articles"][0]["url"] = "https://three.test/article"
    snapshot["articles"][0]["text"] = "A later observation."
    pipeline.run(snapshot, tmp_path)
    with pipeline.connect(tmp_path / "memory.sqlite3") as db:
        history = pipeline.memory(db, snapshot["day"])[0]["history"]
    assert {item["url"] for item in history} == {
        "https://one.test/article",
        "https://two.test/article",
    }
    assert len({item["article_id"] for item in history}) == 1


def test_repeated_source_quote_is_not_duplicated_in_history(snapshot, fake_model, tmp_path):
    for day in ("2026-10-01", "2026-10-02", "2026-10-03"):
        snapshot["day"] = day
        pipeline.run(snapshot, tmp_path)
    with pipeline.connect(tmp_path / "memory.sqlite3") as db:
        assert pipeline.memory(db, snapshot["day"])[0]["history"] == []
    snapshot["day"] = "2026-10-04"
    snapshot["articles"][0]["text"] = "A new observation."
    pipeline.run(snapshot, tmp_path)
    with pipeline.connect(tmp_path / "memory.sqlite3") as db:
        history = pipeline.memory(db, snapshot["day"])[0]["history"]
    assert len(history) == 1
    assert history[0]["observed_on"] == "2026-10-01"


def test_window_applies_to_observations_including_history(snapshot, fake_model, tmp_path):
    first, _ = pipeline.run(snapshot, tmp_path)
    snapshot["day"] = "2026-10-02"
    snapshot["articles"][0]["text"] = "Second observation."
    pipeline.run(snapshot, tmp_path)
    snapshot["day"] = "2026-10-14"
    snapshot["articles"][0]["text"] = "Most recent observation."
    pipeline.run(snapshot, tmp_path)
    with pipeline.connect(tmp_path / "memory.sqlite3") as db:
        memory = pipeline.memory(db, "2026-10-16")[0]
    assert memory["id"] == first["events"][0]["id"]
    assert [item["quote"] for item in memory["history"]] == ["Second observation."]
    assert memory["history"][0]["observed_on"] == "2026-10-02"


def test_oversized_real_history_fails_before_call_without_losing_accepted_runs(
    snapshot, monkeypatch, tmp_path
):
    calls = []

    def model(*args, **kwargs):
        calls.append(1)
        return isolated_events(*args, **kwargs)

    monkeypatch.setattr(pipeline, "run_task", model)
    pipeline.run(many_articles(snapshot, 50, "first", "x" * 1500), tmp_path)
    pipeline.run(many_articles(snapshot, 50, "second", "x" * 1500), tmp_path)
    with pytest.raises(ValueError, match="articles plus memory exceed"):
        pipeline.run(many_articles(snapshot, 50, "third", "x" * 1500), tmp_path)
    assert len(calls) == 2
    with pipeline.connect(tmp_path / "memory.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 2
        assert len(pipeline.memory(db, snapshot["day"])) == 100
    assert len(list((tmp_path / "runs").glob("*/failure.json"))) == 1
