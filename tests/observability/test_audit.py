import sqlite3

import pytest

import src.observability as observability
from src.tracker import store as tracker_store
from tests.observability.support import _run_args


def test_novelty_audit_filters_decisions_by_run_id(tmp_path):
    db_path = tmp_path / "stories.db"
    conn = tracker_store.get_db(db_path)
    conn.close()

    first = observability.start_run(
        _run_args(), run_date="2026-05-07", db_path=db_path
    )
    observability.finish_run(first, db_path=db_path)
    second = observability.start_run(
        _run_args(), run_date="2026-05-07", db_path=db_path
    )
    observability.finish_run(second, db_path=db_path)

    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            """
            INSERT INTO story_match_decisions (
                run_id, run_date, today_label, candidate_label, accepted,
                same_event, relationship, confidence, prompt_version
            ) VALUES (?, '2026-05-07', ?, ?, 0, 0, 'adjacent_topic', 'high', 'v1')
            """,
            [
                (first, "First run label", "First candidate"),
                (second, "Second run label", "Second candidate"),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    audit = observability.novelty_audit(first, db_path=db_path)

    assert [item["today_label"] for item in audit["rejected_related_matches"]] == [
        "First run label"
    ]


def test_novelty_audit_surfaces_review_candidates(tmp_path):
    db_path = tmp_path / "stories.db"

    run_id = observability.start_run(
        _run_args(), run_date="2026-05-17", db_path=db_path
    )
    observability.update_run_totals(
        run_id,
        story_developments_saved=3,
        story_new_parent_arcs=2,
        db_path=db_path,
    )
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript("""
            CREATE TABLE stories (
                story_id INTEGER PRIMARY KEY,
                canonical_label TEXT NOT NULL,
                theme TEXT,
                first_seen DATE NOT NULL,
                last_seen DATE NOT NULL
            );
            CREATE TABLE articles (
                id TEXT,
                story_id INTEGER,
                date DATE,
                source TEXT,
                title TEXT,
                url TEXT,
                published_at TEXT,
                importance INTEGER,
                description TEXT
            );
            CREATE TABLE story_developments (
                development_id INTEGER PRIMARY KEY,
                story_id INTEGER,
                observation_id INTEGER,
                date DATE,
                development_label TEXT,
                development_status TEXT,
                source_count INTEGER,
                article_count INTEGER,
                importance_avg REAL,
                parent_relationship TEXT,
                parent_confidence TEXT
            );
            CREATE TABLE story_match_decisions (
                decision_id INTEGER PRIMARY KEY,
                run_id INTEGER,
                run_date TEXT NOT NULL,
                today_label TEXT NOT NULL,
                candidate_label TEXT NOT NULL,
                candidate_story_id INTEGER,
                accepted INTEGER NOT NULL,
                same_event INTEGER NOT NULL,
                relationship TEXT NOT NULL,
                confidence TEXT,
                article_dates TEXT,
                candidate_last_seen TEXT,
                continuity_evidence TEXT,
                reject_reason TEXT,
                verifier_model TEXT,
                prompt_version TEXT NOT NULL
            );
        """)
        conn.executemany(
            """
            INSERT INTO stories (story_id, canonical_label, theme, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (1, "Displayed war story", "Geopolitics & War", "2026-05-16", "2026-05-17"),
                (2, "Odido data breach", "Tech", "2026-05-17", "2026-05-17"),
                (3, "Modena car attack", "Other", "2026-05-17", "2026-05-17"),
            ],
        )
        articles = []
        for index in range(6):
            articles.append((
                f"war-{index}", 1, "2026-05-17", f"War Source {index}",
                "War update", f"https://example.com/war/{index}",
                "Sun, 17 May 2026 10:00:00 GMT", 5, "",
            ))
            articles.append((
                f"tech-{index}", 2, "2026-05-17", f"Tech Source {index}",
                "Data breach update", f"https://example.com/tech/{index}",
                "Sun, 17 May 2026 11:00:00 GMT", 4, "",
            ))
            articles.append((
                f"modena-{index}", 3, "2026-05-17", f"Modena Source {index}",
                "Car drives into pedestrians", f"https://example.com/modena/{index}",
                "Sun, 17 May 2026 12:00:00 GMT", 4, "",
            ))
        conn.executemany(
            """
            INSERT INTO articles (
                id, story_id, date, source, title, url, published_at, importance, description
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            articles,
        )
        conn.executemany(
            """
            INSERT INTO story_developments (
                story_id, date, development_label, development_status,
                source_count, article_count, importance_avg
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (1, "2026-05-17", "Displayed war story", "continuing", 6, 6, 5.0),
                (2, "2026-05-17", "Odido data breach", "new_parent", 6, 6, 4.0),
                (3, "2026-05-17", "Modena car attack", "new_parent", 6, 6, 4.0),
            ],
        )
        conn.execute(
            """
            INSERT INTO story_match_decisions (
                run_id, run_date, today_label, candidate_label, candidate_story_id,
                accepted, same_event, relationship, confidence, continuity_evidence,
                reject_reason, prompt_version
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                "2026-05-17",
                "Modena car attack",
                "Italian vehicle attacks",
                9,
                0,
                0,
                "adjacent_topic",
                "medium",
                '["same country and incident type"]',
                "Not the same concrete event.",
                "test",
            ),
        )
        conn.commit()
    finally:
        conn.close()
    observability.finish_run(run_id, status="ok", db_path=db_path)

    audit = observability.novelty_audit(run_id, db_path=db_path)
    report = observability.pipeline_report(run_id, db_path=db_path)
    markdown = observability.run_report_markdown(run_id, db_path=db_path)

    assert audit["new_parent_ratio"] == pytest.approx(2 / 3)
    assert audit["high_signal_not_displayed"] == []
    assert {item["label"] for item in audit["high_signal_new_parent_arcs"]} == {
        "Odido data breach",
        "Modena car attack",
    }
    assert audit["new_parent_arcs_with_candidates"][0]["label"] == "Modena car attack"
    assert "Novelty audit:" in report
    assert "New parent ratio:      2/3 (66.7%)" in report
    assert "High-signal not displayed: 0" in report
    assert "Modena car attack -> Italian vehicle attacks (adjacent_topic, medium)" in report
    assert "## Novelty Audit" in markdown
    assert "| None |  | 0 | 0.0 | 0.0 | 0.0 | 0.0 |  |" in markdown
    assert "| Odido data breach | Odido data breach | Tech | 6 | 6 | 4.0 | 472.0 |" in markdown
    # No story_arc_decisions table in this database: sections degrade to empty.
    assert audit["arc_attachments_review"] == []
    assert audit["rejected_arc_decisions"] == []
    assert "Arc attachments to review: 0" in report
    assert "Rejected arc decisions: 0" in report


def test_novelty_audit_surfaces_arc_decisions(tmp_path):
    db_path = tmp_path / "stories.db"

    run_id = observability.start_run(
        _run_args(), run_date="2026-06-02", db_path=db_path
    )
    observability.update_run_totals(
        run_id,
        story_developments_saved=2,
        story_new_parent_arcs=1,
        db_path=db_path,
    )
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript("""
            CREATE TABLE stories (
                story_id INTEGER PRIMARY KEY,
                canonical_label TEXT NOT NULL,
                theme TEXT,
                first_seen DATE NOT NULL,
                last_seen DATE NOT NULL,
                arc_id INTEGER
            );
            CREATE TABLE articles (
                id TEXT,
                story_id INTEGER,
                date DATE,
                source TEXT,
                title TEXT,
                url TEXT,
                published_at TEXT,
                importance INTEGER,
                description TEXT
            );
            CREATE TABLE story_developments (
                development_id INTEGER PRIMARY KEY,
                story_id INTEGER,
                observation_id INTEGER,
                date DATE,
                development_label TEXT,
                development_status TEXT,
                source_count INTEGER,
                article_count INTEGER,
                importance_avg REAL,
                parent_relationship TEXT,
                parent_confidence TEXT
            );
            CREATE TABLE story_arcs (
                arc_id INTEGER PRIMARY KEY,
                canonical_label TEXT NOT NULL,
                theme TEXT,
                first_seen DATE,
                last_seen DATE
            );
            CREATE TABLE story_arc_decisions (
                decision_id INTEGER PRIMARY KEY,
                run_id INTEGER,
                run_date TEXT NOT NULL,
                today_label TEXT NOT NULL,
                candidates TEXT NOT NULL,
                arc_id INTEGER,
                parent_story_id INTEGER,
                story_id INTEGER,
                accepted INTEGER NOT NULL,
                relationship TEXT NOT NULL,
                confidence TEXT,
                continuity_evidence TEXT,
                reject_reason TEXT,
                assignment_model TEXT,
                prompt_version TEXT NOT NULL
            );
        """)
        conn.execute(
            """
            INSERT INTO story_arcs (arc_id, canonical_label, theme, first_seen, last_seen)
            VALUES (1, 'Film festival coverage', 'Other', '2026-05-20', '2026-06-02')
            """
        )
        conn.executemany(
            """
            INSERT INTO stories (story_id, canonical_label, theme, first_seen, last_seen, arc_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (11, "Festival opening film", "Other", "2026-05-20", "2026-05-20", 1),
                (12, "Festival jury dispute", "Other", "2026-05-25", "2026-05-25", 1),
                (13, "New film premiere", "Other", "2026-06-02", "2026-06-02", 1),
            ],
        )
        conn.executemany(
            """
            INSERT INTO story_arc_decisions (
                run_id, run_date, today_label, candidates, arc_id, parent_story_id,
                story_id, accepted, relationship, confidence, continuity_evidence,
                reject_reason, assignment_model, prompt_version
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    run_id, "2026-06-02", "New film premiere",
                    '[{"arc_id": 1, "arc_label": "Film festival coverage", "score": 12}]',
                    1, None, 13, 1, "same_arc", "medium",
                    '["Festival coverage continues."]', "", "gpt-5.4-mini", "test",
                ),
                (
                    run_id, "2026-06-02", "Dutch frigate shadowed",
                    '[{"arc_id": 1, "arc_label": "Film festival coverage", "score": 10}]',
                    1, None, 21, 0, "same_arc", "high",
                    '["Weak shared context."]',
                    "Arc assignment did not accept an existing arc.",
                    "gpt-5.4-mini", "test",
                ),
                (
                    run_id, "2026-06-02", "Minor storm",
                    "[]",
                    None, None, 22, 0, "uncertain", "low",
                    "[]", "Arc assignment returned no decision for this case.",
                    "gpt-5.4-mini", "test",
                ),
            ],
        )
        conn.commit()
    finally:
        conn.close()
    observability.finish_run(run_id, status="ok", db_path=db_path)

    audit = observability.novelty_audit(run_id, db_path=db_path)
    report = observability.pipeline_report(run_id, db_path=db_path)
    markdown = observability.run_report_markdown(run_id, db_path=db_path)

    review = audit["arc_attachments_review"]
    assert len(review) == 1
    assert review[0]["today_label"] == "New film premiere"
    assert review[0]["arc_label"] == "Film festival coverage"
    assert review[0]["chosen_score"] == 12
    assert review[0]["arc_child_count"] == 3

    rejected = audit["rejected_arc_decisions"]
    assert [item["today_label"] for item in rejected] == ["Dutch frigate shadowed"]
    assert rejected[0]["proposed_arc_label"] == "Film festival coverage"
    assert rejected[0]["reject_reason"] == "Arc assignment did not accept an existing arc."

    assert "Arc attachments to review: 1" in report
    assert (
        "New film premiere -> Film festival coverage "
        "(same_arc, medium, score 12, 3 stories in arc)"
    ) in report
    assert "Rejected arc decisions: 1" in report
    assert "Dutch frigate shadowed -> Film festival coverage (same_arc, high)" in report
    assert "### Arc Attachments To Review" in markdown
    assert "| New film premiere | Film festival coverage | same_arc | medium | 12 | 3 |" in markdown
    assert "### Rejected Arc Decisions" in markdown
    assert "| Dutch frigate shadowed | Film festival coverage | same_arc | high |" in markdown
