import json
import sqlite3

import src.llm_response_cache as llm_response_cache
import src.observability as observability
import src.story_matching as story_matching
import src.tracker as tracker
import src.sources as sources_module
from fakes import FakeLLMClient


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
    return FakeLLMClient(payload)


def _fake_tracker_client_sequence(payloads, captured=None):
    return FakeLLMClient(payloads, capture=captured)


def test_track_is_idempotent_for_same_day(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    data_dir = tmp_path / "daily"
    monkeypatch.setattr(tracker, "DB_PATH", db_path)
    monkeypatch.setattr(tracker, "DATA_DIR", data_dir)

    articles = [_article(1, "First title"), _article(2, "Second title")]

    first = tracker.track(articles, today="2026-04-18", verify_story_matches=False)
    second = tracker.track(articles, today="2026-04-18", verify_story_matches=False)

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

    tracker.track([_article(1, "First title")], today="2026-04-18", verify_story_matches=False)

    conn = sqlite3.connect(db_path)
    row = conn.execute("""
        SELECT a.source_id, s.name
        FROM articles a
        JOIN sources s ON s.source_id = a.source_id
    """).fetchone()
    conn.close()

    assert row == (1, "Test Source")


def test_story_arc_schema_backfills_legacy_stories(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    monkeypatch.setattr(tracker, "DB_PATH", db_path)

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript("""
            CREATE TABLE stories (
                story_id INTEGER PRIMARY KEY AUTOINCREMENT,
                canonical_label TEXT NOT NULL,
                theme TEXT,
                first_seen DATE NOT NULL,
                last_seen DATE NOT NULL
            );
            INSERT INTO stories (canonical_label, theme, first_seen, last_seen)
            VALUES ('Legacy Story', 'Tech', '2026-05-01', '2026-05-02');
        """)
        conn.commit()
    finally:
        conn.close()

    conn = tracker._get_db()
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(stories)").fetchall()}
        row = conn.execute("""
            SELECT s.arc_id, a.canonical_label, a.first_seen, a.last_seen
            FROM stories s
            JOIN story_arcs a ON a.arc_id = s.arc_id
            WHERE s.canonical_label = 'Legacy Story'
        """).fetchone()
        arc_count = conn.execute("SELECT COUNT(*) FROM story_arcs").fetchone()[0]
    finally:
        conn.close()

    assert {"arc_id", "parent_story_id"} <= columns
    assert tuple(row) == (1, "Legacy Story", "2026-05-01", "2026-05-02")
    assert arc_count == 1


def test_track_quarantines_uncategorized_memory_before_matching(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    data_dir = tmp_path / "daily"
    monkeypatch.setattr(tracker, "DB_PATH", db_path)
    monkeypatch.setattr(tracker, "DATA_DIR", data_dir)

    conn = tracker._get_db()
    try:
        with conn:
            arc_id = tracker._create_story_arc(
                conn,
                "Uncategorized",
                "Other",
                "2026-05-01",
                "2026-05-01",
            )
            story_id = conn.execute(
                """
                INSERT INTO stories (
                    arc_id, parent_story_id, canonical_label,
                    theme, first_seen, last_seen
                )
                VALUES (?, NULL, ?, ?, ?, ?)
                """,
                (arc_id, "Uncategorized", "Other", "2026-05-01", "2026-05-01"),
            ).lastrowid
            conn.execute(
                """
                INSERT INTO story_daily (story_id, date, source_count, importance_avg, labels_seen)
                VALUES (?, ?, ?, ?, ?)
                """,
                (story_id, "2026-05-01", 10, 1.0, '["Uncategorized"]'),
            )
    finally:
        conn.close()

    captured = {}

    def fake_match(labels, recent, today=None):
        captured["recent"] = dict(recent)
        return {label: "NEW" for label in labels}

    monkeypatch.setattr(tracker, "_match_labels", fake_match)

    tracker.track(
        [_article(2, "Fresh story", "Fresh Story")],
        today="2026-05-02",
        verify_story_matches=False,
    )

    assert "Uncategorized" not in captured["recent"]
    assert tracker.tracker_store.QUARANTINED_STORY_LABEL not in captured["recent"]

    conn = sqlite3.connect(db_path)
    try:
        labels = conn.execute("""
            SELECT canonical_label FROM stories ORDER BY story_id
        """).fetchall()
        arc_labels = conn.execute("""
            SELECT canonical_label FROM story_arcs ORDER BY arc_id
        """).fetchall()
    finally:
        conn.close()

    assert labels[0] == (tracker.tracker_store.QUARANTINED_STORY_LABEL,)
    assert arc_labels[0] == (tracker.tracker_store.QUARANTINED_STORY_LABEL,)


def test_track_replaces_same_day_article_story_assignment(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    data_dir = tmp_path / "daily"
    monkeypatch.setattr(tracker, "DB_PATH", db_path)
    monkeypatch.setattr(tracker, "DATA_DIR", data_dir)

    tracker.track(
        [_article(1, "First title", story_label="Old Story")],
        today="2026-04-18",
        verify_story_matches=False,
    )
    tracker.track(
        [_article(1, "First title", story_label="New Story")],
        today="2026-04-18",
        verify_story_matches=False,
    )

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

    first = tracker.track(
        [_article(1, "First title")],
        today="2026-04-18",
        verify_story_matches=False,
    )
    tracker.save_observation_memory([{
        "observation_id": first[0]["observation_id"],
        "summary": "Earlier summary.",
        "delta_summary": "Earlier change.",
    }])

    second = tracker.track(
        [_article(2, "Second title")],
        today="2026-04-19",
        verify_story_matches=False,
    )

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
        {
            "assignments": [{
                "today_label": "Israel Detention Abuse",
                "arc_id": "NEW_ARC",
                "parent_story_id": None,
                "relationship": "uncertain",
                "confidence": "low",
                "continuity_evidence": [],
                "reject_reason": "The detention abuse coverage is not part of the flotilla arc.",
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


def test_rejected_parent_arc_match_saves_new_child_development(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    data_dir = tmp_path / "daily"
    client = _fake_tracker_client_sequence([
        {
            "matches": [{
                "today_label": "Mali rebel offensive",
                "canonical_label": "Mali attacks",
            }]
        },
        {
            "decisions": [{
                "today_label": "Mali rebel offensive",
                "canonical_label": "Mali attacks",
                "same_event": False,
                "relationship": "adjacent_topic",
                "confidence": "medium",
                "article_dates": ["2026-05-15"],
                "candidate_last_seen": "2026-05-13",
                "continuity_evidence": [
                    "Shared country/context: Mali security crisis and rebel violence"
                ],
                "reject_reason": (
                    "The airstrikes are a distinct development from the earlier "
                    "mass-casualty attacks."
                ),
            }]
        },
        {
            "assignments": [{
                "today_label": "Mali rebel offensive",
                "arc_id": 1,
                "parent_story_id": 1,
                "relationship": "same_arc",
                "confidence": "medium",
                "continuity_evidence": [
                    "Both stories concern Mali's security crisis and rebel violence."
                ],
                "reject_reason": "",
            }]
        },
    ])
    monkeypatch.setattr(tracker, "DB_PATH", db_path)
    monkeypatch.setattr(tracker, "DATA_DIR", data_dir)
    monkeypatch.setattr(tracker, "get_openai_client", lambda: client)

    first = tracker.track(
        [_article(1, "Militants attack towns in Mali", "Mali attacks")],
        today="2026-05-13",
    )
    tracker.save_observation_memory([{
        "observation_id": first[0]["observation_id"],
        "summary": "Mali's junta faced rebel and jihadist attacks with Russian backing under strain.",
        "delta_summary": "Rebel pressure on Mali's junta continued.",
    }])

    article = _article(
        2,
        "Mali forces launch airstrikes against rebel alliance",
        "Mali rebel offensive",
    )
    article["published_at"] = "Fri, 15 May 2026 12:00:00 GMT"
    tracked = tracker.track([article], today="2026-05-15", verify_story_matches=True)

    assert tracked[0]["canonical_label"] == "Mali rebel offensive"
    assert tracked[0]["arc_label"] == "Mali attacks"
    assert tracked[0]["parent_label"] == "Mali attacks"
    assert tracked[0]["development_label"] == "Mali rebel offensive"
    assert tracked[0]["development_status"] == "new_child"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        story_count = conn.execute("SELECT COUNT(*) FROM stories").fetchone()[0]
        arc_count = conn.execute("SELECT COUNT(*) FROM story_arcs").fetchone()[0]
        development = dict(conn.execute("""
            SELECT s.canonical_label, a.canonical_label AS arc_label,
                   p.canonical_label AS parent_label, d.development_label,
                   d.development_status, d.parent_relationship,
                   d.parent_confidence
            FROM story_developments d
            JOIN stories s ON s.story_id = d.story_id
            JOIN story_arcs a ON a.arc_id = s.arc_id
            LEFT JOIN stories p ON p.story_id = s.parent_story_id
            WHERE d.date = ?
        """, ("2026-05-15",)).fetchone())
    finally:
        conn.close()

    assert story_count == 2
    assert arc_count == 1
    assert development == {
        "canonical_label": "Mali rebel offensive",
        "arc_label": "Mali attacks",
        "parent_label": "Mali attacks",
        "development_label": "Mali rebel offensive",
        "development_status": "new_child",
        "parent_relationship": "same_arc",
        "parent_confidence": "medium",
    }


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
    monkeypatch.setattr(observability, "DB_PATH", db_path)
    monkeypatch.setattr(llm_response_cache, "DB_PATH", db_path)
    monkeypatch.setattr(tracker, "get_openai_client", lambda: client)
    monkeypatch.setattr(
        tracker,
        "_fetch_article_text_for_match",
        lambda url: "Full article text about the latest Iran nuclear talks proposal.",
    )

    run_id = observability.start_run({"test": "story-match-text"}, run_date="2026-05-02")
    observability.set_current_run_id(run_id)
    try:
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

        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute("""
                SELECT article_text_fetch_successes, article_text_fetch_failures
                FROM runs
                WHERE run_id = ?
            """, (run_id,)).fetchone()
        finally:
            conn.close()
        assert row == (1, 0)
    finally:
        observability.clear_current_run_id()


def test_arc_assignment_uses_mini_model_and_supplied_arc_candidates(monkeypatch):
    captured = []
    client = _fake_tracker_client_sequence([
        {
            "assignments": [{
                "today_label": "Mali rebel offensive",
                "arc_id": 7,
                "parent_story_id": 3,
                "relationship": "same_arc",
                "confidence": "high",
                "continuity_evidence": ["Mali rebel violence continues inside the same security arc."],
                "reject_reason": "",
            }]
        }
    ], captured=captured)
    monkeypatch.setattr(tracker, "get_openai_client", lambda: client)

    assignments = tracker._assign_story_arcs(
        {"Mali rebel offensive"},
        {
            7: {
                "arc_id": 7,
                "canonical_label": "Mali attacks",
                "theme": "Geopolitics & War",
                "last_seen": "2026-05-13",
                "active_days": 2,
                "recent_stories": [{
                    "story_id": 3,
                    "canonical_label": "Mali attacks",
                    "last_seen": "2026-05-13",
                    "summary": "Mali rebel violence continued.",
                }],
            }
        },
        {"Mali rebel offensive": [_article(2, "Mali rebels launch offensive", "Mali rebel offensive")]},
        today="2026-05-15",
    )

    assert captured[0]["model"] == "gpt-5.4-mini"
    payload = json.loads(captured[0]["messages"][1]["content"])
    assert payload["cases"][0]["candidate_arcs"][0]["arc_id"] == 7
    assert assignments["Mali rebel offensive"]["accepted"] is True
    assert assignments["Mali rebel offensive"]["arc_id"] == 7
    assert assignments["Mali rebel offensive"]["parent_story_id"] == 3


def test_arc_assignment_rejects_adjacent_and_broader_relationships():
    expected_case = {
        "today_label": "Mali rebel offensive",
        "candidate_arcs": [{
            "arc_id": 7,
            "recent_stories": [{
                "story_id": 3,
                "canonical_label": "Mali attacks",
            }],
        }],
    }

    for relationship in ("adjacent_topic", "broader_context"):
        assignment = tracker.story_matching.arc_assignment_from_model(
            {
                "today_label": "Mali rebel offensive",
                "arc_id": 7,
                "parent_story_id": 3,
                "relationship": relationship,
                "confidence": "high",
                "continuity_evidence": ["Shared Mali security context."],
                "reject_reason": "",
            },
            expected_case,
            "test-model",
        )

        assert assignment["accepted"] is False
        assert assignment["arc_id"] is None
        assert assignment["parent_story_id"] is None
        assert assignment["relationship"] == relationship
        assert assignment["reject_reason"] == "Arc assignment did not accept an existing arc."
        assert assignment["proposed_arc_id"] == 7
        assert assignment["proposed_parent_story_id"] == 3


def test_arc_assignment_cases_keep_audit_scores_out_of_prompt():
    arcs = {
        7: {
            "arc_id": 7,
            "canonical_label": "Mali attacks",
            "theme": "Geopolitics & War",
            "last_seen": "2026-06-01",
            "active_days": 2,
            "recent_stories": [{
                "story_id": 3,
                "canonical_label": "Mali attacks",
                "last_seen": "2026-06-01",
            }],
        }
    }
    story_groups = {
        "Mali rebel offensive": [_article(1, "Mali rebels launch offensive", "Mali rebel offensive")],
    }

    cases, candidate_audit = tracker.story_matching.arc_assignment_cases_for_prompt(
        {"Mali rebel offensive"},
        arcs,
        story_groups,
        today="2026-06-02",
    )

    assert [case["today_label"] for case in cases] == ["Mali rebel offensive"]
    assert set(cases[0].keys()) == {"today_label", "run_date", "current_articles", "candidate_arcs"}
    for option in cases[0]["candidate_arcs"]:
        assert "score" not in option
        assert "arc_label" not in option
    audit_entries = candidate_audit["Mali rebel offensive"]
    assert audit_entries[0]["arc_id"] == 7
    assert audit_entries[0]["arc_label"] == "Mali attacks"
    assert audit_entries[0]["score"] > 0


def test_arc_decisions_persisted_for_accept_and_reject(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    data_dir = tmp_path / "daily"
    monkeypatch.setattr(tracker, "DB_PATH", db_path)
    monkeypatch.setattr(tracker, "DATA_DIR", data_dir)
    monkeypatch.setattr(tracker, "_consolidate_today", lambda groups: groups)

    tracker.track(
        [
            _article(1, "Mali rebels strike base", "Mali attacks"),
            _article(2, "Paris museum theft investigated", "Paris museum theft investigation"),
        ],
        today="2026-06-01",
        verify_story_matches=False,
    )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        day_one_stories = {
            row["canonical_label"]: dict(row)
            for row in conn.execute("SELECT story_id, canonical_label, arc_id FROM stories")
        }
    finally:
        conn.close()
    mali_story = day_one_stories["Mali attacks"]
    paris_story = day_one_stories["Paris museum theft investigation"]

    captured = []
    client = _fake_tracker_client_sequence([
        {
            "assignments": [
                {
                    "today_label": "Mali rebel offensive",
                    "arc_id": mali_story["arc_id"],
                    "parent_story_id": mali_story["story_id"],
                    "relationship": "same_arc",
                    "confidence": "high",
                    "continuity_evidence": ["Same Mali rebel campaign continues."],
                    "reject_reason": "",
                },
                {
                    "today_label": "Paris museum heist suspects",
                    "arc_id": paris_story["arc_id"],
                    "parent_story_id": None,
                    "relationship": "adjacent_topic",
                    "confidence": "high",
                    "continuity_evidence": ["Both involve Paris museums."],
                    "reject_reason": "",
                },
            ]
        }
    ], captured=captured)
    monkeypatch.setattr(tracker, "get_openai_client", lambda: client)
    monkeypatch.setattr(
        tracker,
        "_match_labels",
        lambda labels, recent, today=None: {label: "NEW" for label in labels},
    )

    tracker.track(
        [
            _article(3, "Mali rebels launch offensive", "Mali rebel offensive"),
            _article(4, "Police name museum heist suspects", "Paris museum heist suspects"),
        ],
        today="2026-06-02",
        verify_story_matches=False,
    )

    conn = tracker.tracker_store.get_db(db_path)
    try:
        decisions = tracker.tracker_store.get_story_arc_decisions(conn, run_date="2026-06-02")
        day_two_stories = {
            row["canonical_label"]: dict(row)
            for row in conn.execute(
                "SELECT story_id, canonical_label, arc_id, parent_story_id FROM stories"
            )
        }
    finally:
        conn.close()

    by_label = {decision["today_label"]: decision for decision in decisions}
    assert set(by_label) == {"Mali rebel offensive", "Paris museum heist suspects"}

    accepted = by_label["Mali rebel offensive"]
    assert accepted["accepted"] == 1
    assert accepted["arc_id"] == mali_story["arc_id"]
    assert accepted["parent_story_id"] == mali_story["story_id"]
    assert accepted["relationship"] == "same_arc"
    assert accepted["assignment_model"] == tracker.ARC_ASSIGNMENT_MODEL
    assert accepted["prompt_version"] == tracker.story_matching.ARC_ASSIGNMENT_PROMPT_VERSION
    assert json.loads(accepted["continuity_evidence"]) == ["Same Mali rebel campaign continues."]
    accepted_candidates = json.loads(accepted["candidates"])
    assert len(accepted_candidates) == 1
    assert accepted_candidates[0]["arc_id"] == mali_story["arc_id"]
    assert accepted_candidates[0]["arc_label"] == "Mali attacks"
    assert accepted_candidates[0]["score"] > 0

    mali_child = day_two_stories["Mali rebel offensive"]
    assert accepted["story_id"] == mali_child["story_id"]
    assert mali_child["arc_id"] == mali_story["arc_id"]
    assert mali_child["parent_story_id"] == mali_story["story_id"]

    rejected = by_label["Paris museum heist suspects"]
    assert rejected["accepted"] == 0
    assert rejected["arc_id"] == paris_story["arc_id"]
    assert rejected["parent_story_id"] is None
    assert rejected["reject_reason"] == "Arc assignment did not accept an existing arc."
    rejected_candidates = json.loads(rejected["candidates"])
    assert [option["arc_id"] for option in rejected_candidates] == [paris_story["arc_id"]]

    paris_new = day_two_stories["Paris museum heist suspects"]
    assert rejected["story_id"] == paris_new["story_id"]
    assert paris_new["arc_id"] != paris_story["arc_id"]

    payload = json.loads(captured[0]["messages"][1]["content"])
    for case in payload["cases"]:
        assert set(case.keys()) == {"today_label", "run_date", "current_articles", "candidate_arcs"}
        for option in case["candidate_arcs"]:
            assert "score" not in option
            assert "arc_label" not in option


def test_multiple_today_labels_under_one_parent_do_not_overwrite_articles(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    data_dir = tmp_path / "daily"
    monkeypatch.setattr(tracker, "DB_PATH", db_path)
    monkeypatch.setattr(tracker, "DATA_DIR", data_dir)
    monkeypatch.setattr(
        tracker,
        "_match_labels",
        lambda labels, recent, today=None: {
            label: "Iran conflict" if "Iran conflict" in recent else "NEW"
            for label in labels
        },
    )
    monkeypatch.setattr(
        tracker,
        "_consolidate_today",
        lambda groups: groups,
    )

    tracker.track(
        [_article(1, "Iran conflict continues", "Iran conflict")],
        today="2026-05-14",
        verify_story_matches=False,
    )
    articles = [
        _article(2, "Iran talks stall", "Iran talks"),
        _article(3, "Hormuz costs hit trade", "Iran trade fallout"),
    ]
    articles[1]["source"] = "Second Source"

    tracked = tracker.track(articles, today="2026-05-15", verify_story_matches=False)

    assert {article["canonical_label"] for article in tracked} == {"Iran conflict"}
    assert {article["development_label"] for article in tracked} == {
        "Iran talks",
        "Iran trade fallout",
    }

    conn = sqlite3.connect(db_path)
    try:
        article_count = conn.execute(
            "SELECT COUNT(*) FROM articles WHERE date = ?",
            ("2026-05-15",),
        ).fetchone()[0]
        development_count = conn.execute(
            "SELECT COUNT(*) FROM story_developments WHERE date = ?",
            ("2026-05-15",),
        ).fetchone()[0]
        daily = conn.execute(
            "SELECT source_count, labels_seen FROM story_daily WHERE date = ?",
            ("2026-05-15",),
        ).fetchone()
    finally:
        conn.close()

    assert article_count == 2
    assert development_count == 2
    assert daily[0] == 2
    assert set(json.loads(daily[1])) == {"Iran talks", "Iran trade fallout"}


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
    captured = []
    client = FakeLLMClient({
        "matches": [{
            "today_label": "Iran Peace Proposal",
            "canonical_label": "Iran Nuclear Talks",
        }]
    }, capture=captured)
    monkeypatch.setattr(tracker, "get_openai_client", lambda: client)

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

    assert captured[0]["model"] == "gpt-5.4-mini"
    payload = json.loads(captured[0]["messages"][1]["content"])
    match_case = payload["match_cases"][0]
    assert match_case["today_label"] == "Iran Peace Proposal"
    recent = match_case["candidates"][0]
    assert recent["canonical_label"] == "Iran Nuclear Talks"
    assert recent["last_delta"] == "Iran sent a proposal but the US response remained unclear."
    assert recent["summary"] == "Negotiations continued under military pressure."
    assert recent["recent_titles"] == ["Iran sends new peace proposal"]


def test_match_labels_batches_crossday_cases(monkeypatch):
    monkeypatch.setattr(tracker.story_matching, "MATCH_CASES_PER_CALL", 2)
    captured_batches = []

    def batch_response(kwargs):
        payload = json.loads(kwargs["messages"][1]["content"])
        batch = payload["match_cases"]
        captured_batches.append([case["today_label"] for case in batch])
        return {
            "matches": [
                {
                    "today_label": case["today_label"],
                    "canonical_label": case["candidates"][0]["canonical_label"],
                }
                for case in batch
            ]
        }

    client = FakeLLMClient(batch_response)
    monkeypatch.setattr(tracker, "get_openai_client", lambda: client)
    labels = {
        "Alpha Event",
        "Bravo Event",
        "Charlie Event",
        "Delta Event",
        "Echo Event",
    }
    recent = {
        label: {
            "story_id": index,
            "canonical_label": label,
            "last_seen": "2026-05-01",
            "summary": f"{label} continued yesterday.",
        }
        for index, label in enumerate(sorted(labels), start=1)
    }

    matches = tracker._match_labels(labels, recent, today="2026-05-02")

    assert captured_batches == [
        ["Alpha Event", "Bravo Event"],
        ["Charlie Event", "Delta Event"],
        ["Echo Event"],
    ]
    assert matches == {label: label for label in labels}


def test_match_labels_uses_exact_response_cache_inside_run(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    monkeypatch.setattr(llm_response_cache, "DB_PATH", db_path)
    monkeypatch.setattr(observability, "DB_PATH", db_path)
    run_id = observability.start_run({"today": "2026-05-04"}, run_date="2026-05-04")
    observability.set_current_run_id(run_id)

    client = FakeLLMClient({
        "matches": [{
            "today_label": "Iran Peace Proposal",
            "canonical_label": "Iran Nuclear Talks",
        }]
    })
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
    assert client.calls == 1

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


def test_verifier_rejection_blocks_exact_label_story_reuse(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    data_dir = tmp_path / "daily"
    client = _fake_tracker_client_sequence([
        {
            "matches": [{
                "today_label": "Border clash",
                "canonical_label": "Border clash",
            }]
        },
        {
            "decisions": [{
                "today_label": "Border clash",
                "canonical_label": "Border clash",
                "same_event": False,
                "relationship": "adjacent_topic",
                "confidence": "high",
                "article_dates": ["2026-06-03"],
                "candidate_last_seen": "2026-06-01",
                "continuity_evidence": [],
                "reject_reason": "Different countries and a different border incident.",
            }]
        },
        {
            "assignments": [{
                "today_label": "Border clash",
                "arc_id": "NEW_ARC",
                "parent_story_id": None,
                "relationship": "uncertain",
                "confidence": "low",
                "continuity_evidence": [],
                "reject_reason": "Unrelated to the earlier border clash.",
            }]
        },
    ])
    monkeypatch.setattr(tracker, "DB_PATH", db_path)
    monkeypatch.setattr(tracker, "DATA_DIR", data_dir)
    monkeypatch.setattr(llm_response_cache, "DB_PATH", db_path)
    monkeypatch.setattr(tracker, "get_openai_client", lambda: client)

    first_article = _article(1, "Thai and Cambodian troops exchange fire", "Border clash")
    first_article["text"] = "Thai and Cambodian troops exchanged fire near a disputed temple."
    first = tracker.track([first_article], today="2026-06-01")

    second_article = _article(2, "Kyrgyz-Tajik border clash wounds dozens", "Border clash")
    second_article["text"] = "Clashes broke out on the Kyrgyz-Tajik border over a water dispute."
    tracked = tracker.track([second_article], today="2026-06-03")

    assert tracked[0]["story_id"] != first[0]["story_id"]
    assert tracked[0]["development_status"] == "new_parent"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        story_count = conn.execute(
            "SELECT COUNT(*) FROM stories WHERE canonical_label = ?",
            ("Border clash",),
        ).fetchone()[0]
        linked_story_id = conn.execute(
            "SELECT story_id FROM articles WHERE id = ?", ("2",)
        ).fetchone()["story_id"]
    finally:
        conn.close()

    assert story_count == 2
    assert linked_story_id == tracked[0]["story_id"]


def test_generic_label_is_not_reused_across_days(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    data_dir = tmp_path / "daily"
    match_payload = {
        "matches": [{
            "today_label": "Stabbing attack",
            "canonical_label": "NEW",
        }]
    }
    arc_payload = {
        "assignments": [{
            "today_label": "Stabbing attack",
            "arc_id": "NEW_ARC",
            "parent_story_id": None,
            "relationship": "uncertain",
            "confidence": "low",
            "continuity_evidence": [],
            "reject_reason": "Unrelated incidents in different cities.",
        }]
    }
    # No observability run is active in tests, so the LLM response cache is
    # off and the same-day rerun consumes a second match + arc payload pair.
    client = _fake_tracker_client_sequence(
        [match_payload, arc_payload, match_payload, arc_payload]
    )
    monkeypatch.setattr(tracker, "DB_PATH", db_path)
    monkeypatch.setattr(tracker, "DATA_DIR", data_dir)
    monkeypatch.setattr(llm_response_cache, "DB_PATH", db_path)
    monkeypatch.setattr(tracker, "get_openai_client", lambda: client)

    first = tracker.track(
        [_article(1, "Knife attack at Hamburg station", "Stabbing attack")],
        today="2026-06-01",
    )
    tracked = tracker.track(
        [_article(2, "Stabbing at Sydney mall", "Stabbing attack")],
        today="2026-06-03",
    )

    assert tracked[0]["story_id"] != first[0]["story_id"]

    # A same-day rerun must reuse today's own story row, not create a third.
    rerun = tracker.track(
        [_article(2, "Stabbing at Sydney mall", "Stabbing attack")],
        today="2026-06-03",
    )
    assert rerun[0]["story_id"] == tracked[0]["story_id"]

    conn = sqlite3.connect(db_path)
    story_count = conn.execute(
        "SELECT COUNT(*) FROM stories WHERE canonical_label = ?",
        ("Stabbing attack",),
    ).fetchone()[0]
    conn.close()
    assert story_count == 2


def test_exact_label_reuse_allowed():
    assert story_matching.exact_label_reuse_allowed("Border clash")
    assert story_matching.exact_label_reuse_allowed("Paris stabbing attack")
    assert not story_matching.exact_label_reuse_allowed("Stabbing attack")
    assert not story_matching.exact_label_reuse_allowed("Protest violence")
