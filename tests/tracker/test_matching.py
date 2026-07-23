import json
import sqlite3

import src.llm_response_cache as llm_response_cache
import src.observability as observability
import src.tracker as tracker
from src.config import (
    CROSSDAY_MATCH_MODEL,
    DEFAULT_LOOKBACK_DAYS,
    MATCHING_REASONING_EFFORT,
    TRACKER_MODEL,
)
from src.tracker import matching as story_matching
from tests.fakes import FakeLLMClient
from tests.tracker.support import _article, _fake_tracker_client, _fake_tracker_client_sequence


def test_matching_reasoning_effort_uses_reconstruction_selection():
    assert MATCHING_REASONING_EFFORT == "low"


def _consolidate(groups, client):
    return story_matching.consolidate_today(
        groups,
        get_client=lambda: client,
        model=TRACKER_MODEL,
    )


def _match(labels, recent, *, client=None, today=None):
    def get_client():
        if client is None:
            raise AssertionError("matching should not call the LLM for this case")
        return client

    return story_matching.match_labels(
        labels,
        recent,
        get_client=get_client,
        model=CROSSDAY_MATCH_MODEL,
        today=today,
        default_days=DEFAULT_LOOKBACK_DAYS,
    )


def test_consolidate_today_rejects_unrelated_generic_accidents():
    client = _fake_tracker_client({
            "groups": [{
                "canonical_label": "Fair Ride Accident",
                "labels": ["Molen Accident", "E-Motorcycle Manslaughter"],
            }],
        })

    groups = {
        "Molen Accident": [_article(1, "Child injured by windmill sail", "Molen Accident")],
        "E-Motorcycle Manslaughter": [_article(2, "E-motorcycle crash kills man", "E-Motorcycle Manslaughter")],
    }

    consolidated = _consolidate(groups, client)

    assert set(consolidated) == {"Molen Accident", "E-Motorcycle Manslaughter"}
    assert len(consolidated["Molen Accident"]) == 1
    assert len(consolidated["E-Motorcycle Manslaughter"]) == 1


def test_consolidate_today_allows_shared_distinctive_incident():
    client = _fake_tracker_client({
            "groups": [{
                "canonical_label": "Train Collision",
                "labels": ["Train Crash", "Train Collision"],
            }],
        })

    groups = {
        "Train Crash": [_article(1, "Two trains crash", "Train Crash")],
        "Train Collision": [_article(2, "Train collision injures passengers", "Train Collision")],
    }

    consolidated = _consolidate(groups, client)

    assert list(consolidated) == ["Train Collision"]
    assert len(consolidated["Train Collision"]) == 2


def test_consolidate_today_rejects_label_repeated_across_groups():
    client = _fake_tracker_client({
            "groups": [
                {"canonical_label": "First", "labels": ["Label A"]},
                {"canonical_label": "Second", "labels": ["Label A", "Label B"]},
            ],
        })
    groups = {
        "Label A": [_article(1, "First")],
        "Label B": [_article(2, "Second")],
    }

    consolidated = _consolidate(groups, client)

    assert consolidated is groups


def test_consolidate_today_rejects_duplicate_canonical_labels():
    client = _fake_tracker_client({
            "groups": [
                {"canonical_label": "Shared", "labels": ["Label A"]},
                {"canonical_label": "Shared", "labels": ["Label B"]},
            ],
        })
    groups = {
        "Label A": [_article(1, "First")],
        "Label B": [_article(2, "Second")],
    }

    consolidated = _consolidate(groups, client)

    assert consolidated is groups


def test_consolidate_today_falls_back_on_invalid_json():
    groups = {
        "Label A": [_article(1, "First")],
        "Label B": [_article(2, "Second")],
    }

    consolidated = _consolidate(groups, FakeLLMClient("not-json"))

    assert consolidated is groups


def test_match_labels_rejects_unrelated_generic_accident():
    client = _fake_tracker_client({
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
        })

    matches = _match(
        {"Molen Accident", "Train Crash"},
        {"Fair Ride Accident": 1, "Train Collision": 2},
        client=client,
    )

    assert matches["Molen Accident"] == "NEW"
    assert matches["Train Crash"] == "Train Collision"


def test_match_labels_rejects_known_shooting_false_merge():
    matches = _match(
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


def test_story_match_verifier_rejects_gaza_detention_false_merge(tmp_path):
    db_path = tmp_path / "stories.db"
    data_dir = tmp_path / "daily"

    def story_rejection(kwargs):
        case = json.loads(kwargs["messages"][1]["content"])["cases"][0]
        return {
            "decisions": [{
                "case_id": case["case_id"],
                "same_story": False,
                "relationship": "related_context",
                "confidence": "high",
                "shared_anchors": [],
                "conflicts": [],
                "reject_reason": (
                    "The article concerns Palestinian detainees generally, "
                    "not the flotilla raid or detained flotilla activists."
                ),
            }]
        }

    def arc_rejection(kwargs):
        case = json.loads(kwargs["messages"][1]["content"])["cases"][0]
        return {
            "decisions": [{
                "case_id": case["case_id"],
                "belongs_to_arc": False,
                "container_type": "broad_topic",
                "relationship": "related_context",
                "confidence": "high",
                "shared_anchors": [],
                "conflicts": [],
                "parent_story_id": None,
                "proposed_arc_label": "Gaza flotilla raid",
                "reject_reason": (
                    "The detention abuse coverage is not part of the flotilla arc."
                ),
            }]
        }

    client = _fake_tracker_client_sequence([story_rejection, arc_rejection])
    first = tracker.track(
        [_article(1, "Israel intercepts Gaza-bound flotilla", "Gaza flotilla raid")],
        today="2026-05-04",
        db_path=db_path,
        data_dir=data_dir,
        client_factory=lambda: client,
    )
    tracker.save_observation_memory([{
        "observation_id": first[0]["observation_id"],
        "summary": "Israel intercepted a Gaza-bound aid flotilla and detained activists.",
        "delta_summary": "British Gaza flotilla activists alleged abuse after detention.",
    }], db_path=db_path)

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

    tracked = tracker.track(
        [article],
        today="2026-05-07",
        verify_story_matches=True,
        db_path=db_path,
        data_dir=data_dir,
        client_factory=lambda: client,
    )

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
    assert decision["relationship"] == "related_context"
    assert "not the flotilla raid" in decision["reject_reason"]
    assert [row["canonical_label"] for row in story_rows] == ["Israel Detention Abuse"]


def test_match_labels_allows_ongoing_story_rewording():
    client = _fake_tracker_client({
            "matches": [{
                "today_label": "Iran Peace Proposal",
                "canonical_label": "Iran Nuclear Talks",
            }],
        })

    matches = _match(
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
        client=client,
    )

    assert matches["Iran Peace Proposal"] == "Iran Nuclear Talks"


def test_match_labels_sends_per_label_candidate_memory():
    captured = []
    client = FakeLLMClient({
        "matches": [{
            "today_label": "Iran Peace Proposal",
            "canonical_label": "Iran Nuclear Talks",
        }]
    }, capture=captured)
    _match(
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
        client=client,
    )

    assert captured[0]["model"] == CROSSDAY_MATCH_MODEL
    payload = json.loads(captured[0]["messages"][1]["content"])
    match_case = payload["match_cases"][0]
    assert match_case["today_label"] == "Iran Peace Proposal"
    recent = match_case["candidates"][0]
    assert recent["canonical_label"] == "Iran Nuclear Talks"
    assert recent["last_delta"] == "Iran sent a proposal but the US response remained unclear."
    assert recent["summary"] == "Negotiations continued under military pressure."
    assert recent["recent_titles"] == ["Iran sends new peace proposal"]


def test_match_labels_batches_crossday_cases(monkeypatch):
    monkeypatch.setattr(story_matching.verification, "MATCH_CASES_PER_CALL", 2)
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

    matches = _match(labels, recent, client=client, today="2026-05-02")

    assert captured_batches == [
        ["Alpha Event", "Bravo Event"],
        ["Charlie Event", "Delta Event"],
        ["Echo Event"],
    ]
    assert matches == {label: label for label in labels}


def test_match_labels_uses_exact_response_cache_inside_run(tmp_path, monkeypatch):
    db_path = tmp_path / "stories.db"
    monkeypatch.setattr(llm_response_cache, "DB_PATH", db_path)
    run_id = observability.start_run(
        {"today": "2026-05-04"},
        run_date="2026-05-04",
        db_path=db_path,
    )
    observability.set_current_run_id(run_id, db_path=db_path)

    client = FakeLLMClient({
        "matches": [{
            "today_label": "Iran Peace Proposal",
            "canonical_label": "Iran Nuclear Talks",
        }]
    })
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
        first = _match(
            {"Iran Peace Proposal"},
            recent,
            client=client,
            today="2026-05-04",
        )
        second = _match(
            {"Iran Peace Proposal"},
            recent,
            client=client,
            today="2026-05-04",
        )
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


def test_match_labels_rejects_model_match_outside_label_candidates():
    client = _fake_tracker_client({
            "matches": [{
                "today_label": "Iran Peace Proposal",
                "canonical_label": "Unrelated Story",
            }],
        })

    matches = _match(
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
        client=client,
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

    cases = story_matching.candidate_cases_for_prompt(
        {"Iran Nuclear Talks"},
        recent,
        today="2026-05-04",
        limit=3,
        default_days=DEFAULT_LOOKBACK_DAYS,
    )

    candidates = cases[0]["candidates"]
    assert len(candidates) == 3
    assert all(
        len(candidate["summary"]) <= story_matching.SUMMARY_CHAR_LIMIT + 3
        for candidate in candidates
    )
    assert all(
        len(candidate["last_delta"]) <= story_matching.DELTA_CHAR_LIMIT + 3
        for candidate in candidates
    )
    assert all(len(candidate["recent_titles"]) == 2 for candidate in candidates)
    assert all(
        len(candidate["recent_titles"][0]) <= story_matching.TITLE_CHAR_LIMIT + 3
        for candidate in candidates
    )


def test_exact_label_reuse_allowed():
    assert story_matching.exact_label_reuse_allowed("Border clash")
    assert story_matching.exact_label_reuse_allowed("Paris stabbing attack")
    assert not story_matching.exact_label_reuse_allowed("Stabbing attack")
    assert not story_matching.exact_label_reuse_allowed("Protest violence")
