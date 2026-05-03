import json
import sqlite3

import src.tracker as tracker


def _article(article_id, title, story_label="Test Story"):
    return {
        "id": article_id,
        "source": "Test Source",
        "language": "en",
        "title": title,
        "description": "Description",
        "url": f"https://example.com/{article_id}",
        "published_at": "Sat, 18 Apr 2026 12:00:00 GMT",
        "text": "",
        "theme": "Tech",
        "story_label": story_label,
        "importance": 3,
    }


def _fake_tracker_client(payload):
    class Message:
        content = json.dumps(payload)

    class Choice:
        message = Message()

    class Response:
        choices = [Choice()]

    class Completions:
        def create(self, **kwargs):
            return Response()

    class Chat:
        completions = Completions()

    class Client:
        chat = Chat()

    return Client()


def test_track_is_idempotent_for_same_day(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    data_dir = tmp_path / "daily"
    monkeypatch.setattr(tracker, "DB_PATH", db_path)
    monkeypatch.setattr(tracker, "DATA_DIR", data_dir)

    articles = [_article(1, "First title"), _article(2, "Second title")]

    first = tracker.track(articles, today="2026-04-18")
    second = tracker.track(articles, today="2026-04-18")

    assert len(first) == 2
    assert len(second) == 2

    conn = sqlite3.connect(db_path)
    story_count = conn.execute("SELECT COUNT(*) FROM stories").fetchone()[0]
    daily_count = conn.execute("SELECT COUNT(*) FROM story_daily").fetchone()[0]
    observation_count = conn.execute("SELECT COUNT(*) FROM story_observations").fetchone()[0]
    link_count = conn.execute("SELECT COUNT(*) FROM article_story_links").fetchone()[0]
    article_count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    conn.close()

    assert story_count == 1
    assert daily_count == 1
    assert observation_count == 1
    assert link_count == 2
    assert article_count == 2


def test_track_replaces_same_day_article_story_assignment(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    data_dir = tmp_path / "daily"
    monkeypatch.setattr(tracker, "DB_PATH", db_path)
    monkeypatch.setattr(tracker, "DATA_DIR", data_dir)

    tracker.track([_article(1, "First title", story_label="Old Story")], today="2026-04-18")
    tracker.track([_article(1, "First title", story_label="New Story")], today="2026-04-18")

    conn = sqlite3.connect(db_path)
    labels = conn.execute("""
        SELECT s.canonical_label
        FROM articles a
        JOIN stories s ON s.story_id = a.story_id
        WHERE a.date = ?
    """, ("2026-04-18",)).fetchall()
    story_count = conn.execute("SELECT COUNT(*) FROM stories").fetchone()[0]
    daily_count = conn.execute("SELECT COUNT(*) FROM story_daily").fetchone()[0]
    observation_count = conn.execute("SELECT COUNT(*) FROM story_observations").fetchone()[0]
    link_count = conn.execute("SELECT COUNT(*) FROM article_story_links").fetchone()[0]
    article_count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    conn.close()

    assert labels == [("New Story",)]
    assert story_count == 1
    assert daily_count == 1
    assert observation_count == 1
    assert link_count == 1
    assert article_count == 1


def test_track_attaches_previous_story_context(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    data_dir = tmp_path / "daily"
    monkeypatch.setattr(tracker, "DB_PATH", db_path)
    monkeypatch.setattr(tracker, "DATA_DIR", data_dir)
    monkeypatch.setattr(
        tracker,
        "_match_labels",
        lambda labels, recent: {label: label if label in recent else "NEW" for label in labels},
    )

    first = tracker.track([_article(1, "First title")], today="2026-04-18")
    tracker.save_observation_memory([{
        "observation_id": first[0]["observation_id"],
        "summary": "Earlier summary.",
        "delta_summary": "Earlier change.",
    }])

    second = tracker.track([_article(2, "Second title")], today="2026-04-19")

    context = second[0]["previous_context"]
    assert context["last_observed"] == "2026-04-18"
    assert context["summary"] == "Earlier summary."
    assert context["delta_summary"] == "Earlier change."
    assert context["recent_articles"][0]["title"] == "First title"
    assert context["recent_articles"][0]["description"] == "Description"


def test_consolidate_today_rejects_unrelated_generic_accidents(monkeypatch):
    monkeypatch.setattr(
        tracker,
        "get_openai_client",
        lambda: _fake_tracker_client({
            "groups": [{
                "canonical_label": "Fair Ride Accident",
                "labels": ["Molen Accident", "E-Motorcycle Manslaughter"],
            }],
        }),
    )

    groups = {
        "Molen Accident": [_article(1, "Child injured by windmill sail", "Molen Accident")],
        "E-Motorcycle Manslaughter": [_article(2, "E-motorcycle crash kills man", "E-Motorcycle Manslaughter")],
    }

    consolidated = tracker._consolidate_today(groups)

    assert set(consolidated) == {"Molen Accident", "E-Motorcycle Manslaughter"}
    assert len(consolidated["Molen Accident"]) == 1
    assert len(consolidated["E-Motorcycle Manslaughter"]) == 1


def test_consolidate_today_allows_shared_distinctive_incident(monkeypatch):
    monkeypatch.setattr(
        tracker,
        "get_openai_client",
        lambda: _fake_tracker_client({
            "groups": [{
                "canonical_label": "Train Collision",
                "labels": ["Train Crash", "Train Collision"],
            }],
        }),
    )

    groups = {
        "Train Crash": [_article(1, "Two trains crash", "Train Crash")],
        "Train Collision": [_article(2, "Train collision injures passengers", "Train Collision")],
    }

    consolidated = tracker._consolidate_today(groups)

    assert list(consolidated) == ["Train Collision"]
    assert len(consolidated["Train Collision"]) == 2


def test_match_labels_rejects_unrelated_generic_accident(monkeypatch):
    monkeypatch.setattr(
        tracker,
        "get_openai_client",
        lambda: _fake_tracker_client({
            "matches": [
                {
                    "today_label": "Molen Accident",
                    "canonical_label": "Fair Ride Accident",
                },
                {
                    "today_label": "Train Crash",
                    "canonical_label": "Train Collision",
                },
            ],
        }),
    )

    matches = tracker._match_labels(
        {"Molen Accident", "Train Crash"},
        {"Fair Ride Accident": 1, "Train Collision": 2},
    )

    assert matches["Molen Accident"] == "NEW"
    assert matches["Train Crash"] == "Train Collision"


def test_trend_uses_latest_prior_day(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    monkeypatch.setattr(tracker, "DB_PATH", db_path)
    conn = tracker._get_db()
    cur = conn.execute(
        "INSERT INTO stories (canonical_label, theme, first_seen, last_seen) VALUES (?, ?, ?, ?)",
        ("Test Story", "Tech", "2026-04-15", "2026-04-18"),
    )
    story_id = cur.lastrowid
    conn.execute(
        """
        INSERT INTO story_daily (story_id, date, source_count, importance_avg, labels_seen)
        VALUES (?, ?, ?, ?, ?)
        """,
        (story_id, "2026-04-16", 1, 3.0, "[]"),
    )
    conn.execute(
        """
        INSERT INTO story_daily (story_id, date, source_count, importance_avg, labels_seen)
        VALUES (?, ?, ?, ?, ?)
        """,
        (story_id, "2026-04-17", 4, 3.0, "[]"),
    )

    assert tracker._trend(story_id, 1, conn, "2026-04-18") == "down"
    conn.close()


def test_recent_story_lookup_uses_newest_duplicate_label(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    monkeypatch.setattr(tracker, "DB_PATH", db_path)
    conn = tracker._get_db()

    old = conn.execute(
        "INSERT INTO stories (canonical_label, theme, first_seen, last_seen) VALUES (?, ?, ?, ?)",
        ("Duplicate Label", "Tech", "2026-04-18", "2026-04-18"),
    ).lastrowid
    new = conn.execute(
        "INSERT INTO stories (canonical_label, theme, first_seen, last_seen) VALUES (?, ?, ?, ?)",
        ("Duplicate Label", "Tech", "2026-04-20", "2026-04-20"),
    ).lastrowid
    conn.execute(
        """
        INSERT INTO story_daily (story_id, date, source_count, importance_avg, labels_seen)
        VALUES (?, ?, ?, ?, ?)
        """,
        (old, "2026-04-18", 1, 3.0, "[]"),
    )
    conn.execute(
        """
        INSERT INTO story_daily (story_id, date, source_count, importance_avg, labels_seen)
        VALUES (?, ?, ?, ?, ?)
        """,
        (new, "2026-04-20", 1, 3.0, "[]"),
    )

    recent = tracker._get_recent_stories(conn, "2026-04-21")
    conn.close()

    assert recent["Duplicate Label"] == new
