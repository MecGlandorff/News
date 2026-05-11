import json
import sqlite3

import src.llm_response_cache as llm_response_cache
import src.observability as observability
import src.tracker as tracker
import src.sources as sources_module


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


def _fake_tracker_client_sequence(payloads, captured=None):
    class Message:
        def __init__(self, content):
            self.content = content

    class Choice:
        def __init__(self, content):
            self.message = Message(content)

    class Response:
        def __init__(self, payload):
            self.choices = [Choice(json.dumps(payload))]

    class Completions:
        def __init__(self):
            self.payloads = list(payloads)

        def create(self, **kwargs):
            if captured is not None:
                captured.append(kwargs)
            return Response(self.payloads.pop(0))

    class Chat:
        def __init__(self):
            self.completions = Completions()

    class Client:
        def __init__(self):
            self.chat = Chat()

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


def test_track_populates_source_id_when_source_metadata_exists(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    data_dir = tmp_path / "daily"
    monkeypatch.setattr(tracker, "DB_PATH", db_path)
    monkeypatch.setattr(tracker, "DATA_DIR", data_dir)
    monkeypatch.setattr(sources_module, "DB_PATH", db_path)
    sources_module.seed_sources([("Test Source", "en", "https://example.com/rss")])

    tracker.track([_article(1, "First title")], today="2026-04-18")

    conn = sqlite3.connect(db_path)
    row = conn.execute("""
        SELECT a.source_id, s.name
        FROM articles a
        JOIN sources s ON s.source_id = a.source_id
    """).fetchone()
    conn.close()

    assert row == (1, "Test Source")


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
        lambda labels, recent, today=None: {label: label if label in recent else "NEW" for label in labels},
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


def test_match_labels_rejects_known_shooting_false_merge(monkeypatch):
    matches = tracker._match_labels(
        {"White House Shooting"},
        {
            "OpenAI Shooter Lawsuit": {
                "story_id": 1,
                "canonical_label": "OpenAI Shooter Lawsuit",
                "last_seen": "2026-05-01",
                "summary": "Families sued OpenAI over alleged ChatGPT use before a school shooting.",
                "recent_articles": [{
                    "date": "2026-05-01",
                    "source": "Example News",
                    "title": "OpenAI faces negligence lawsuit after school shooting",
                }],
            }
        },
    )

    assert matches["White House Shooting"] == "NEW"


def test_story_match_verifier_rejects_gaza_detention_false_merge(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    data_dir = tmp_path / "daily"
    client = _fake_tracker_client_sequence([
        {
            "matches": [{
                "today_label": "Israel Detention Abuse",
                "canonical_label": "Gaza flotilla raid",
            }]
        },
        {
            "decisions": [{
                "today_label": "Israel Detention Abuse",
                "canonical_label": "Gaza flotilla raid",
                "same_event": False,
                "relationship": "adjacent_topic",
                "confidence": "high",
                "article_dates": ["2026-05-07"],
                "candidate_last_seen": "2026-05-04",
                "continuity_evidence": [],
                "reject_reason": (
                    "The article concerns Palestinian detainees generally, "
                    "not the flotilla raid or detained flotilla activists."
                ),
            }]
        },
    ])
    monkeypatch.setattr(tracker, "DB_PATH", db_path)
    monkeypatch.setattr(tracker, "DATA_DIR", data_dir)
    monkeypatch.setattr(tracker, "get_openai_client", lambda: client)

    first = tracker.track(
        [_article(1, "Israel intercepts Gaza-bound flotilla", "Gaza flotilla raid")],
        today="2026-05-04",
    )
    tracker.save_observation_memory([{
        "observation_id": first[0]["observation_id"],
        "summary": "Israel intercepted a Gaza-bound aid flotilla and detained activists.",
        "delta_summary": "British Gaza flotilla activists alleged abuse after detention.",
    }])

    article = _article(
        2,
        "Palestinians expose torture and sexual violence in Israeli detention",
        "Israel Detention Abuse",
    )
    article["source"] = "Al Jazeera"
    article["description"] = (
        "Palestinian detainees and rights groups share disturbing accounts of rape, "
        "sexual violence and physical abuse."
    )
    article["text"] = (
        "Palestinian detainees and rights groups share disturbing accounts of rape, "
        "sexual violence and physical abuse in Israeli detention."
    )

    tracked = tracker.track([article], today="2026-05-07", verify_story_matches=True)

    assert tracked[0]["canonical_label"] == "Israel Detention Abuse"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        decision = dict(conn.execute(
            """
            SELECT today_label, candidate_label, accepted, same_event,
                   relationship, reject_reason
            FROM story_match_decisions
            """
        ).fetchone())
        story_rows = conn.execute("""
            SELECT s.canonical_label
            FROM articles a
            JOIN stories s ON s.story_id = a.story_id
            WHERE a.id = ?
        """, ("2",)).fetchall()
    finally:
        conn.close()

    assert decision["today_label"] == "Israel Detention Abuse"
    assert decision["candidate_label"] == "Gaza flotilla raid"
    assert decision["accepted"] == 0
    assert decision["same_event"] == 0
    assert decision["relationship"] == "adjacent_topic"
    assert "not the flotilla raid" in decision["reject_reason"]
    assert [row["canonical_label"] for row in story_rows] == ["Israel Detention Abuse"]


def test_story_match_verifier_fetches_full_text_for_candidate_match(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    data_dir = tmp_path / "daily"
    captured = []
    client = _fake_tracker_client_sequence([
        {
            "matches": [{
                "today_label": "Iran Peace Proposal",
                "canonical_label": "Iran Nuclear Talks",
            }]
        },
        {
            "decisions": [{
                "today_label": "Iran Peace Proposal",
                "canonical_label": "Iran Nuclear Talks",
                "same_event": True,
                "relationship": "direct_follow_up",
                "confidence": "high",
                "article_dates": ["2026-05-02"],
                "candidate_last_seen": "2026-05-01",
                "continuity_evidence": ["The article reports a new proposal in the same nuclear talks."],
                "reject_reason": "",
            }]
        },
    ], captured=captured)
    monkeypatch.setattr(tracker, "DB_PATH", db_path)
    monkeypatch.setattr(tracker, "DATA_DIR", data_dir)
    monkeypatch.setattr(tracker, "get_openai_client", lambda: client)
    monkeypatch.setattr(
        tracker,
        "_fetch_article_text_for_match",
        lambda url: "Full article text about the latest Iran nuclear talks proposal.",
    )

    first = tracker.track(
        [_article(1, "Iran sends proposal through mediators", "Iran Nuclear Talks")],
        today="2026-05-01",
    )
    tracker.save_observation_memory([{
        "observation_id": first[0]["observation_id"],
        "summary": "US-Iran nuclear negotiations continued through mediators.",
        "delta_summary": "Iran sent a proposal but the US response remained unclear.",
    }])

    article = _article(2, "Iran sends revised peace proposal", "Iran Peace Proposal")
    article["published_at"] = "Sat, 02 May 2026 12:00:00 GMT"
    article["text"] = ""

    tracked = tracker.track([article], today="2026-05-02", verify_story_matches=True)

    assert tracked[0]["canonical_label"] == "Iran Nuclear Talks"
    verifier_payload = json.loads(captured[1]["messages"][1]["content"])
    current_article = verifier_payload["cases"][0]["current_articles"][0]
    assert current_article["article_date"] == "2026-05-02"
    assert current_article["article_text"] == "Full article text about the latest Iran nuclear talks proposal."


def test_match_labels_allows_ongoing_story_rewording(monkeypatch):
    monkeypatch.setattr(
        tracker,
        "get_openai_client",
        lambda: _fake_tracker_client({
            "matches": [{
                "today_label": "Iran Peace Proposal",
                "canonical_label": "Iran Nuclear Talks",
            }],
        }),
    )

    matches = tracker._match_labels(
        {"Iran Peace Proposal"},
        {
            "Iran Nuclear Talks": {
                "story_id": 2,
                "canonical_label": "Iran Nuclear Talks",
                "last_seen": "2026-05-01",
                "summary": "US-Iran nuclear negotiations continued through mediators.",
                "recent_articles": [{
                    "date": "2026-05-01",
                    "source": "Example News",
                    "title": "Iran sends new peace proposal through mediators",
                }],
            }
        },
    )

    assert matches["Iran Peace Proposal"] == "Iran Nuclear Talks"


def test_match_labels_sends_per_label_candidate_memory(monkeypatch):
    captured = {}

    class Message:
        content = json.dumps({
            "matches": [{
                "today_label": "Iran Peace Proposal",
                "canonical_label": "Iran Nuclear Talks",
            }]
        })

    class Choice:
        message = Message()

    class Response:
        choices = [Choice()]

    class Completions:
        def create(self, **kwargs):
            captured["payload"] = json.loads(kwargs["messages"][1]["content"])
            return Response()

    class Chat:
        completions = Completions()

    class Client:
        chat = Chat()

    monkeypatch.setattr(tracker, "get_openai_client", lambda: Client())

    tracker._match_labels(
        {"Iran Peace Proposal"},
        {
            "Iran Nuclear Talks": {
                "story_id": 2,
                "canonical_label": "Iran Nuclear Talks",
                "last_seen": "2026-05-01",
                "delta_summary": "Iran sent a proposal but the US response remained unclear.",
                "summary": "Negotiations continued under military pressure.",
                "recent_articles": [{
                    "date": "2026-05-01",
                    "source": "Example News",
                    "title": "Iran sends new peace proposal",
                }],
            }
        },
    )

    match_case = captured["payload"]["match_cases"][0]
    assert match_case["today_label"] == "Iran Peace Proposal"
    recent = match_case["candidates"][0]
    assert recent["canonical_label"] == "Iran Nuclear Talks"
    assert recent["last_delta"] == "Iran sent a proposal but the US response remained unclear."
    assert recent["summary"] == "Negotiations continued under military pressure."
    assert recent["recent_titles"] == ["Iran sends new peace proposal"]


def test_match_labels_uses_exact_response_cache_inside_run(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    monkeypatch.setattr(llm_response_cache, "DB_PATH", db_path)
    monkeypatch.setattr(observability, "DB_PATH", db_path)
    run_id = observability.start_run({"today": "2026-05-04"}, run_date="2026-05-04")
    observability.set_current_run_id(run_id)

    class Message:
        content = json.dumps({
            "matches": [{
                "today_label": "Iran Peace Proposal",
                "canonical_label": "Iran Nuclear Talks",
            }]
        })

    class Choice:
        message = Message()

    class Response:
        choices = [Choice()]

    class Completions:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            return Response()

    class Chat:
        def __init__(self):
            self.completions = Completions()

    class Client:
        def __init__(self):
            self.chat = Chat()

    client = Client()
    monkeypatch.setattr(tracker, "get_openai_client", lambda: client)
    recent = {
        "Iran Nuclear Talks": {
            "story_id": 2,
            "canonical_label": "Iran Nuclear Talks",
            "last_seen": "2026-05-03",
            "summary": "US-Iran nuclear negotiations continued through mediators.",
            "recent_articles": [{
                "date": "2026-05-03",
                "source": "Example News",
                "title": "Iran sends new peace proposal through mediators",
            }],
        }
    }

    try:
        first = tracker._match_labels({"Iran Peace Proposal"}, recent, today="2026-05-04")
        second = tracker._match_labels({"Iran Peace Proposal"}, recent, today="2026-05-04")
        observability.finish_run(run_id, status="ok")
    finally:
        observability.clear_current_run_id()

    assert first == second == {"Iran Peace Proposal": "Iran Nuclear Talks"}
    assert client.chat.completions.calls == 1

    conn = sqlite3.connect(db_path)
    try:
        run = conn.execute(
            "SELECT llm_calls_count, llm_cache_hits FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        call_count = conn.execute(
            "SELECT COUNT(*) FROM llm_calls WHERE run_id = ?",
            (run_id,),
        ).fetchone()[0]
    finally:
        conn.close()

    assert run == (1, 1)
    assert call_count == 1


def test_match_labels_rejects_model_match_outside_label_candidates(monkeypatch):
    monkeypatch.setattr(
        tracker,
        "get_openai_client",
        lambda: _fake_tracker_client({
            "matches": [{
                "today_label": "Iran Peace Proposal",
                "canonical_label": "Unrelated Story",
            }],
        }),
    )

    matches = tracker._match_labels(
        {"Iran Peace Proposal"},
        {
            "Iran Nuclear Talks": {
                "story_id": 2,
                "canonical_label": "Iran Nuclear Talks",
                "last_seen": "2026-05-01",
                "summary": "US-Iran nuclear negotiations continued through mediators.",
                "recent_articles": [{
                    "date": "2026-05-01",
                    "source": "Example News",
                    "title": "Iran sends new peace proposal through mediators",
                }],
            },
            "Unrelated Story": {
                "story_id": 3,
                "canonical_label": "Unrelated Story",
                "last_seen": "2026-05-01",
                "summary": "A separate story about unrelated domestic politics.",
                "recent_articles": [],
            },
        },
    )

    assert matches["Iran Peace Proposal"] == "NEW"


def test_candidate_cases_are_capped_and_truncated():
    long_summary = " ".join(["summary"] * 120)
    long_delta = " ".join(["delta"] * 80)
    long_title = " ".join(["title"] * 80)
    recent = {}
    for index in range(20):
        label = f"Iran Nuclear Talks {index}"
        recent[label] = {
            "story_id": index,
            "canonical_label": label,
            "last_seen": "2026-05-03",
            "summary": long_summary,
            "delta_summary": long_delta,
            "recent_articles": [
                {"title": long_title},
                {"title": "Second relevant title"},
                {"title": "Third title should be omitted"},
            ],
        }

    cases = tracker._candidate_cases_for_prompt(
        {"Iran Nuclear Talks"},
        recent,
        today="2026-05-04",
        limit=3,
    )

    candidates = cases[0]["candidates"]
    assert len(candidates) == 3
    assert all(len(candidate["summary"]) <= tracker.SUMMARY_CHAR_LIMIT + 3 for candidate in candidates)
    assert all(len(candidate["last_delta"]) <= tracker.DELTA_CHAR_LIMIT + 3 for candidate in candidates)
    assert all(len(candidate["recent_titles"]) == 2 for candidate in candidates)
    assert all(len(candidate["recent_titles"][0]) <= tracker.TITLE_CHAR_LIMIT + 3 for candidate in candidates)


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
