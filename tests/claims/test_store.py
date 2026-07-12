import sqlite3

import src.claims as claims_module
from src.claims import schema as claims_schema
from src.tracker import store as tracker_store
from src.claims import extract_and_save_claims, get_claims_for_story
from tests.claims.support import ARTICLE, CLAIM_RESPONSE, _fake_client


def test_get_claims_for_story_ignores_old_prompt_versions(tmp_path):
    db_path = tmp_path / "stories.db"
    client = _fake_client(CLAIM_RESPONSE)
    extract_and_save_claims(
        [ARTICLE],
        db_path=db_path,
        client_factory=lambda: client,
    )

    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO claims (
            article_id, story_id, claim_text, claim_type, entities,
            evidence_span, confidence, prompt_version
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ARTICLE["id"],
            ARTICLE["story_id"],
            "Old cached claim.",
            "fact",
            "[]",
            "Old cached evidence.",
            0.99,
            "old-version",
        ),
    )
    conn.commit()
    conn.close()

    saved = get_claims_for_story(42, db_path=db_path)
    assert len(saved) == 2
    assert "Old cached claim." not in [claim["claim_text"] for claim in saved]


def test_cached_claims_follow_story_reassignment(tmp_path):
    db_path = tmp_path / "stories.db"
    client = _fake_client(CLAIM_RESPONSE)

    extract_and_save_claims([ARTICLE], db_path=db_path, client_factory=lambda: client)
    extract_and_save_claims(
        [{**ARTICLE, "story_id": 84}],
        db_path=db_path,
        client_factory=lambda: client,
    )

    assert client.calls == 1
    assert get_claims_for_story(42, db_path=db_path) == []
    assert len(get_claims_for_story(84, db_path=db_path)) == 2


def test_get_claims_for_story_returns_empty_for_unknown(tmp_path):
    assert get_claims_for_story(9999, db_path=tmp_path / "stories.db") == []


def test_get_claims_for_story_uses_seven_day_occurrence_window(tmp_path):
    db_path = tmp_path / "stories.db"
    conn = tracker_store.get_db(db_path)
    try:
        with conn:
            for occurrence_id, editorial_date in [
                (1, "2026-07-04"),
                (2, "2026-07-05"),
                (3, "2026-07-11"),
            ]:
                conn.execute(
                    """
                    INSERT INTO article_occurrences (
                        occurrence_id, article_id, editorial_date, source, title,
                        description, body_text, url, published_at, content_hash,
                        retrieval_status
                    ) VALUES (?, ?, ?, 'Source', 'Title', '', '', ?, '', ?, 'rss_only')
                    """,
                    (
                        occurrence_id,
                        f"article-{occurrence_id}",
                        editorial_date,
                        f"https://example.com/{occurrence_id}",
                        f"hash-{occurrence_id}",
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO occurrence_assignments (
                        occurrence_id, theme, story_label, importance,
                        story_id, canonical_label,
                        development_label, development_status
                    ) VALUES (?, 'World', 'Story', 4, 42, 'Story', 'Story', 'continuing')
                    """,
                    (occurrence_id,),
                )
    finally:
        conn.close()

    conn = claims_schema.get_db(db_path)
    try:
        with conn:
            for occurrence_id in (1, 2, 3):
                conn.execute(
                    """
                    INSERT INTO claims (
                        article_id, occurrence_id, story_id, claim_text,
                        claim_type, entities, evidence_span, confidence,
                        prompt_version, validation_version
                    ) VALUES (?, ?, 42, ?, 'fact', '[]', 'Evidence', 0.9, ?, ?)
                    """,
                    (
                        f"article-{occurrence_id}",
                        occurrence_id,
                        f"Claim {occurrence_id}",
                        claims_module.CLAIMS_PROMPT_VERSION,
                        claims_module.CLAIMS_VALIDATION_VERSION,
                    ),
                )
    finally:
        conn.close()

    saved = get_claims_for_story(
        42,
        as_of_date="2026-07-11",
        history_days=7,
        db_path=db_path,
    )

    assert [claim["editorial_date"] for claim in saved] == ["2026-07-11", "2026-07-05"]
