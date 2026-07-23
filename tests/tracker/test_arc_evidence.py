import json
import sqlite3

import src.llm_response_cache as llm_response_cache
import src.observability as observability
import src.tracker as tracker
from src.tracker.matching.arc_evidence import (
    assign_story_arcs_evidence,
    is_recurring_content_format,
    material_arc_conflicts,
)
from tests.fakes import FakeLLMClient
from tests.tracker.support import _article


MODEL = "gpt-5.4-mini-2026-03-17"


def _arc(
    *,
    arc_id=7,
    label="Tour de France crash",
    story_label="Tour de France crash",
):
    return {
        "arc_id": arc_id,
        "canonical_label": label,
        "theme": "Sport",
        "last_seen": "2026-07-22",
        "active_days": 1,
        "recent_stories": [
            {
                "story_id": 3,
                "canonical_label": story_label,
                "last_seen": "2026-07-22",
                "summary": "The Tour de France 2026 race continued.",
            }
        ],
    }


def _payload(
    *,
    accepted=True,
    relationship="same_arc",
    anchors=None,
    parent_story_id=None,
    proposed_label="Tour de France 2026",
):
    def response(kwargs):
        cases = json.loads(kwargs["messages"][1]["content"])["cases"]
        return {
            "decisions": [
                {
                    "case_id": case["case_id"],
                    "belongs_to_arc": accepted,
                    "container_type": "named_event",
                    "relationship": relationship,
                    "confidence": "high",
                    "shared_anchors": anchors or ["Tour de France", "2026 race"],
                    "conflicts": [],
                    "parent_story_id": parent_story_id,
                    "proposed_arc_label": proposed_label,
                    "reject_reason": "" if accepted else "Different arc.",
                }
                for case in cases
            ]
        }

    return response


def test_same_arc_clears_parent_and_promotes_one_story_arc_label():
    article = {
        **_article(
            "new",
            "Tour de France 2026 stage changes standings",
            "Tour de France stage",
        ),
        "description": "The Tour de France 2026 race entered a new stage.",
    }
    client = FakeLLMClient(_payload(parent_story_id=3))

    assignments = assign_story_arcs_evidence(
        {"Tour de France stage"},
        {7: _arc()},
        {"Tour de France stage": [article]},
        get_client=lambda: client,
        model=MODEL,
    )

    decision = assignments["Tour de France stage"]
    assert decision["accepted"] is True
    assert decision["arc_id"] == 7
    assert decision["parent_story_id"] is None
    assert decision["proposed_parent_story_id"] == 3
    assert decision["previous_arc_label"] == "Tour de France crash"
    assert decision["final_arc_label"] == "Tour de France 2026"


def test_parent_context_requires_a_supplied_specific_story():
    article = {
        **_article(
            "new",
            "Tour organizer sued after Tour de France crash",
            "Tour crash lawsuit",
        ),
        "description": "The Tour de France crash led to a lawsuit.",
    }
    client = FakeLLMClient(
        _payload(
            relationship="parent_context",
            parent_story_id=999,
            anchors=["Tour de France", "crash"],
            proposed_label="Tour de France 2026",
        )
    )

    assignments = assign_story_arcs_evidence(
        {"Tour crash lawsuit"},
        {7: _arc()},
        {"Tour crash lawsuit": [article]},
        get_client=lambda: client,
        model=MODEL,
    )

    decision = assignments["Tour crash lawsuit"]
    assert decision["accepted"] is False
    assert decision["ambiguity_reason"] == "invalid_parent_context"


def test_recurring_content_format_is_rejected_without_model_call():
    article = {
        **_article(
            "new",
            "Bold and Beautiful spoilers for Friday",
            "Bold and Beautiful spoilers",
        ),
        "description": "Episode recap and spoilers for the soap.",
    }
    arc = _arc(
        label="Bold and Beautiful spoilers",
        story_label="Bold and Beautiful spoilers",
    )
    client = FakeLLMClient([])

    assignments = assign_story_arcs_evidence(
        {"Bold and Beautiful spoilers"},
        {7: arc},
        {"Bold and Beautiful spoilers": [article]},
        get_client=lambda: client,
        model=MODEL,
    )

    decision = assignments["Bold and Beautiful spoilers"]
    assert decision["accepted"] is False
    assert decision["decision_route"] == "deterministic"
    assert client.calls == 0


def test_reviewed_television_program_is_rejected_without_model_call():
    article = _article(
        "new",
        "Timothy valt voor Michaël in B&B Vol Liefde",
        "B&B Vol Liefde",
    )
    arc = _arc(
        label="B&B Vol Liefde",
        story_label="B&B Vol Liefde",
    )
    client = FakeLLMClient([])

    assignments = assign_story_arcs_evidence(
        {"B&B Vol Liefde"},
        {7: arc},
        {"B&B Vol Liefde": [article]},
        get_client=lambda: client,
        model=MODEL,
    )

    assert assignments["B&B Vol Liefde"]["accepted"] is False
    assert assignments["B&B Vol Liefde"]["decision_route"] == "deterministic"
    assert client.calls == 0


def test_arc_gate_rejects_non_event_container_even_if_model_accepts():
    article = {
        **_article("new", "Contestant leaves dating show", "Dating show update"),
        "description": "A new instalment follows another contestant.",
    }
    def recurring_payload(kwargs):
        response = _payload()(kwargs)
        response["decisions"][0]["container_type"] = "recurring_format"
        return response

    client = FakeLLMClient(recurring_payload)
    assignments = assign_story_arcs_evidence(
        {"Dating show update"},
        {
            7: _arc(
                label="Dating show coverage",
                story_label="Dating show episode",
            )
        },
        {"Dating show update": [article]},
        get_client=lambda: client,
        model=MODEL,
    )

    decision = assignments["Dating show update"]
    assert decision["accepted"] is False
    assert decision["decision_route"] == "fail_closed"
    assert decision["ambiguity_reason"] == (
        "non_event_container:recurring_format"
    )


def test_arc_call_uses_strict_schema_and_effort():
    article = {
        **_article(
            "new",
            "Tour de France 2026 standings update",
            "Tour de France stage",
        ),
        "description": "Tour de France 2026 race standings changed.",
    }
    captured = []
    client = FakeLLMClient(_payload(), capture=captured)

    assign_story_arcs_evidence(
        {"Tour de France stage"},
        {7: _arc()},
        {"Tour de France stage": [article]},
        get_client=lambda: client,
        model=MODEL,
        reasoning_effort="low",
    )

    assert captured[0]["model"] == MODEL
    assert captured[0]["reasoning_effort"] == "low"
    assert captured[0]["response_format"]["type"] == "json_schema"
    assert captured[0]["response_format"]["json_schema"]["strict"] is True
    decisions_schema = captured[0]["response_format"]["json_schema"]["schema"][
        "properties"
    ]["decisions"]
    assert decisions_schema["minItems"] == 1
    assert decisions_schema["maxItems"] == 1
    item_schema = decisions_schema["items"]
    assert "container_type" in item_schema["required"]


def test_expected_distinct_arc_development_is_not_a_material_conflict():
    conflicts = [
        "Different specific development: one is a crash and one a stage victory",
        "Candidate arc label is narrowly phrased around one rider",
        "Different named tournament in another country",
    ]

    assert material_arc_conflicts(conflicts) == [
        "Different named tournament in another country"
    ]


def test_reviewed_television_program_is_a_recurring_format():
    assert is_recurring_content_format(
        "B&B Vol Liefde",
        "Timothy begint te vallen voor Michaël in B&B Vol Liefde",
    )


def test_tracker_promotes_grounded_one_story_arc_and_records_audit(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "stories.db"
    data_dir = tmp_path / "daily"
    monkeypatch.setattr(llm_response_cache, "DB_PATH", db_path)
    first = tracker.track(
        [
            {
                **_article(
                    1,
                    "Tour de France 2026 crash disrupts stage",
                    "Tour de France crash",
                ),
                "description": "A crash disrupted the Tour de France 2026 race.",
            }
        ],
        today="2026-07-22",
        db_path=db_path,
        data_dir=data_dir,
    )

    def reject_same_story(kwargs):
        case = json.loads(kwargs["messages"][1]["content"])["cases"][0]
        return {
            "decisions": [{
                "case_id": case["case_id"],
                "same_story": False,
                "relationship": "related_context",
                "confidence": "high",
                "shared_anchors": ["Tour de France", "2026"],
                "conflicts": [],
                "reject_reason": "A distinct stage development.",
            }]
        }

    def accept_arc(kwargs):
        case = json.loads(kwargs["messages"][1]["content"])["cases"][0]
        return {
            "decisions": [{
                "case_id": case["case_id"],
                "belongs_to_arc": True,
                "container_type": "named_event",
                "relationship": "same_arc",
                "confidence": "high",
                "shared_anchors": ["Tour de France", "2026"],
                "conflicts": [],
                "parent_story_id": None,
                "proposed_arc_label": "Tour de France 2026",
                "reject_reason": "",
            }]
        }

    client = FakeLLMClient([reject_same_story, accept_arc])
    run_id = observability.start_run(
        {"test": "arc-promotion"},
        run_date="2026-07-23",
        db_path=db_path,
    )
    observability.set_current_run_id(run_id, db_path=db_path)
    try:
        tracked = tracker.track(
            [
                {
                    **_article(
                        2,
                        "Tour de France 2026 stage changes standings",
                        "Tour de France stage",
                    ),
                    "description": "The Tour de France 2026 race standings changed.",
                }
            ],
            today="2026-07-23",
            db_path=db_path,
            data_dir=data_dir,
            client_factory=lambda: client,
        )
    finally:
        observability.clear_current_run_id()

    assert tracked[0]["story_id"] != first[0]["story_id"]
    assert tracked[0]["arc_label"] == "Tour de France 2026"
    assert tracked[0]["parent_story_id"] is None

    conn = sqlite3.connect(db_path)
    try:
        arc_label = conn.execute(
            "SELECT canonical_label FROM story_arcs"
        ).fetchone()[0]
        decision = conn.execute(
            """
            SELECT accepted, previous_arc_label, proposed_arc_label,
                   final_arc_label
            FROM story_arc_decisions
            WHERE run_date = '2026-07-23'
            """
        ).fetchone()
        promotions = conn.execute(
            """
            SELECT story_arc_label_promotions
            FROM runs
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()[0]
    finally:
        conn.close()

    assert arc_label == "Tour de France 2026"
    assert decision == (
        1,
        "Tour de France crash",
        "Tour de France 2026",
        "Tour de France 2026",
    )
    assert promotions == 1
