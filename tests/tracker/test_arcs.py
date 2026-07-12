import json
import sqlite3

import src.tracker as tracker
from tests.tracker.support import _article, _fake_tracker_client_sequence


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
