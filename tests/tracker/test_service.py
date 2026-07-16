import json
import sqlite3

import src.llm_response_cache as llm_response_cache
import src.observability as observability
import src.sources as sources_module
import src.tracker as tracker
from src.tracker import store as tracker_store
from tests.tracker.support import _article, _fake_tracker_client_sequence


def test_track_is_idempotent_for_same_day(tmp_path):
    db_path = tmp_path / "stories.db"
    data_dir = tmp_path / "daily"

    articles = [_article(1, "First title"), _article(2, "Second title")]

    first = tracker.track(
        articles,
        today="2026-04-18",
        verify_story_matches=False,
        db_path=db_path,
        data_dir=data_dir,
    )
    second = tracker.track(
        articles,
        today="2026-04-18",
        verify_story_matches=False,
        db_path=db_path,
        data_dir=data_dir,
    )

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
    monkeypatch.setattr(sources_module, "DB_PATH", db_path)
    sources_module.seed_sources([("Test Source", "en", "https://example.com/rss")])

    tracker.track(
        [_article(1, "First title")],
        today="2026-04-18",
        verify_story_matches=False,
        db_path=db_path,
        data_dir=data_dir,
    )

    conn = sqlite3.connect(db_path)
    row = conn.execute("""
        SELECT a.source_id, s.name
        FROM articles a
        JOIN sources s ON s.source_id = a.source_id
    """).fetchone()
    conn.close()

    assert row == (1, "Test Source")


def test_track_quarantines_uncategorized_memory_before_matching(tmp_path):
    db_path = tmp_path / "stories.db"
    data_dir = tmp_path / "daily"
    conn = tracker_store.get_db(db_path)
    try:
        with conn:
            arc_id = tracker_store.create_story_arc(
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

    tracker.track(
        [_article(2, "Fresh story", "Fresh Story")],
        today="2026-05-02",
        verify_story_matches=False,
        db_path=db_path,
        data_dir=data_dir,
        match_labels=fake_match,
    )

    assert "Uncategorized" not in captured["recent"]
    assert tracker_store.QUARANTINED_STORY_LABEL not in captured["recent"]

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

    assert labels[0] == (tracker_store.QUARANTINED_STORY_LABEL,)
    assert arc_labels[0] == (tracker_store.QUARANTINED_STORY_LABEL,)


def test_track_replaces_same_day_article_story_assignment(tmp_path):
    db_path = tmp_path / "stories.db"
    data_dir = tmp_path / "daily"
    tracker.track(
        [_article(1, "First title", story_label="Old Story")],
        today="2026-04-18",
        verify_story_matches=False,
        db_path=db_path,
        data_dir=data_dir,
    )
    tracker.track(
        [_article(1, "First title", story_label="New Story")],
        today="2026-04-18",
        verify_story_matches=False,
        db_path=db_path,
        data_dir=data_dir,
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


def test_track_attaches_previous_story_context(tmp_path):
    db_path = tmp_path / "stories.db"
    data_dir = tmp_path / "daily"
    def match_labels(labels, recent, today=None):
        return {label: label if label in recent else "NEW" for label in labels}

    first = tracker.track(
        [_article(1, "First title")],
        today="2026-04-18",
        verify_story_matches=False,
        db_path=db_path,
        data_dir=data_dir,
        match_labels=match_labels,
    )
    tracker.save_observation_memory([{
        "observation_id": first[0]["observation_id"],
        "summary": "Earlier summary.",
        "delta_summary": "Earlier change.",
    }], db_path=db_path)

    second = tracker.track(
        [_article(2, "Second title")],
        today="2026-04-19",
        verify_story_matches=False,
        db_path=db_path,
        data_dir=data_dir,
        match_labels=match_labels,
    )

    context = second[0]["previous_context"]
    assert context["last_observed"] == "2026-04-18"
    assert context["summary"] == "Earlier summary."
    assert context["delta_summary"] == "Earlier change."
    assert context["recent_articles"][0]["title"] == "First title"
    assert context["recent_articles"][0]["description"] == "Description"


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
    monkeypatch.setattr(llm_response_cache, "DB_PATH", db_path)

    run_id = observability.start_run(
        {"test": "story-match-text"},
        run_date="2026-05-02",
        db_path=db_path,
    )
    observability.set_current_run_id(run_id, db_path=db_path)
    try:
        first = tracker.track(
            [_article(1, "Iran sends proposal through mediators", "Iran Nuclear Talks")],
            today="2026-05-01",
            db_path=db_path,
            data_dir=data_dir,
            client_factory=lambda: client,
        )
        tracker.save_observation_memory([{
            "observation_id": first[0]["observation_id"],
            "summary": "US-Iran nuclear negotiations continued through mediators.",
            "delta_summary": "Iran sent a proposal but the US response remained unclear.",
        }], db_path=db_path)

        article = _article(2, "Iran sends revised peace proposal", "Iran Peace Proposal")
        article["published_at"] = "Sat, 02 May 2026 12:00:00 GMT"
        article["text"] = ""

        tracked = tracker.track(
            [article],
            today="2026-05-02",
            verify_story_matches=True,
            db_path=db_path,
            data_dir=data_dir,
            client_factory=lambda: client,
            fetch_article_text=lambda url: (
                "Full article text about the latest Iran nuclear talks proposal."
            ),
        )

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
            occurrence = conn.execute(
                """
                SELECT o.occurrence_id, o.body_text, o.retrieval_status
                FROM occurrence_assignments a
                JOIN article_occurrences o ON o.occurrence_id = a.occurrence_id
                WHERE o.article_id = '2'
                """
            ).fetchone()
            occurrence_rows = conn.execute(
                """
                SELECT occurrence_id, retrieval_status
                FROM article_occurrences
                WHERE article_id = '2'
                ORDER BY occurrence_id
                """
            ).fetchall()
            history = conn.execute(
                """
                SELECT h.run_id, h.occurrence_id
                FROM occurrence_assignment_history h
                JOIN article_occurrences o ON o.occurrence_id = h.occurrence_id
                WHERE o.article_id = '2'
                """
            ).fetchone()
        finally:
            conn.close()
        assert row == (1, 0)
        assert occurrence[1:] == (
            "Full article text about the latest Iran nuclear talks proposal.",
            "full_text",
        )
        assert occurrence_rows[0][1] == "rss_only"
        assert occurrence_rows[1][1] == "full_text"
        assert tracked[0]["occurrence_id"] == occurrence[0] == occurrence_rows[1][0]
        assert history == (run_id, occurrence[0])
        saved_daily = json.loads(
            (data_dir / "2026-05-02" / "articles.json").read_text(encoding="utf-8")
        )
        assert saved_daily[0]["occurrence_id"] == occurrence[0]
        assert saved_daily[0]["text"] == occurrence[1]
    finally:
        observability.clear_current_run_id()


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
    monkeypatch.setattr(llm_response_cache, "DB_PATH", db_path)

    first_article = _article(1, "Thai and Cambodian troops exchange fire", "Border clash")
    first_article["text"] = "Thai and Cambodian troops exchanged fire near a disputed temple."
    first = tracker.track(
        [first_article],
        today="2026-06-01",
        db_path=db_path,
        data_dir=data_dir,
        client_factory=lambda: client,
    )

    second_article = _article(2, "Kyrgyz-Tajik border clash wounds dozens", "Border clash")
    second_article["text"] = "Clashes broke out on the Kyrgyz-Tajik border over a water dispute."
    tracked = tracker.track(
        [second_article],
        today="2026-06-03",
        db_path=db_path,
        data_dir=data_dir,
        client_factory=lambda: client,
    )

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
    monkeypatch.setattr(llm_response_cache, "DB_PATH", db_path)

    first = tracker.track(
        [_article(1, "Knife attack at Hamburg station", "Stabbing attack")],
        today="2026-06-01",
        db_path=db_path,
        data_dir=data_dir,
        client_factory=lambda: client,
    )
    tracked = tracker.track(
        [_article(2, "Stabbing at Sydney mall", "Stabbing attack")],
        today="2026-06-03",
        db_path=db_path,
        data_dir=data_dir,
        client_factory=lambda: client,
    )

    assert tracked[0]["story_id"] != first[0]["story_id"]

    # A same-day rerun must reuse today's own story row, not create a third.
    rerun = tracker.track(
        [_article(2, "Stabbing at Sydney mall", "Stabbing attack")],
        today="2026-06-03",
        db_path=db_path,
        data_dir=data_dir,
        client_factory=lambda: client,
    )
    assert rerun[0]["story_id"] == tracked[0]["story_id"]

    conn = sqlite3.connect(db_path)
    story_count = conn.execute(
        "SELECT COUNT(*) FROM stories WHERE canonical_label = ?",
        ("Stabbing attack",),
    ).fetchone()[0]
    conn.close()
    assert story_count == 2
