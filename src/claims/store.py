import json
from datetime import date, timedelta

from src.claims.constants import (
    CLAIMS_MODEL,
    CLAIMS_PROMPT_VERSION,
    CLAIMS_VALIDATION_VERSION,
)
from src.claims.schema import get_db


def _extraction_key(article_id, occurrence_id):
    if occurrence_id is not None:
        return f"occurrence:{occurrence_id}"
    return f"article:{article_id}"


def _has_cached_claims(article_id, occurrence_id, story_id, content_hash, conn):
    extraction_key = _extraction_key(article_id, occurrence_id)
    row = conn.execute(
        """
        SELECT story_id, content_hash
        FROM claim_extractions
        WHERE extraction_key = ? AND prompt_version = ?
          AND extractor_model = ? AND validation_version = ?
        """,
        (
            extraction_key,
            CLAIMS_PROMPT_VERSION,
            CLAIMS_MODEL,
            CLAIMS_VALIDATION_VERSION,
        ),
    ).fetchone()
    if not row:
        return False
    if row["content_hash"] != content_hash:
        return False
    if row["story_id"] != story_id:
        if occurrence_id is not None:
            conn.execute(
                """
                UPDATE claims
                SET story_id = ?
                WHERE occurrence_id = ? AND prompt_version = ?
                """,
                (story_id, occurrence_id, CLAIMS_PROMPT_VERSION),
            )
        else:
            conn.execute(
                """
                UPDATE claims
                SET story_id = ?
                WHERE article_id = ? AND occurrence_id IS NULL AND prompt_version = ?
                """,
                (story_id, article_id, CLAIMS_PROMPT_VERSION),
            )
        conn.execute(
            """
            UPDATE claim_extractions
            SET story_id = ?, extracted_at = CURRENT_TIMESTAMP
            WHERE extraction_key = ? AND prompt_version = ?
            """,
            (story_id, extraction_key, CLAIMS_PROMPT_VERSION),
        )
        conn.commit()
    return True


def _delete_cached_claims(article_id, occurrence_id, conn):
    extraction_key = _extraction_key(article_id, occurrence_id)
    if occurrence_id is not None:
        conn.execute(
            "DELETE FROM claims WHERE occurrence_id = ? AND prompt_version = ?",
            (occurrence_id, CLAIMS_PROMPT_VERSION),
        )
    else:
        conn.execute(
            """
            DELETE FROM claims
            WHERE article_id = ? AND occurrence_id IS NULL AND prompt_version = ?
            """,
            (article_id, CLAIMS_PROMPT_VERSION),
        )
    conn.execute(
        "DELETE FROM claim_extractions WHERE extraction_key = ? AND prompt_version = ?",
        (extraction_key, CLAIMS_PROMPT_VERSION),
    )


def _write_classified_claims(
    article_id,
    occurrence_id,
    story_id,
    content_hash,
    classified,
    conn,
):
    """Persist already-validated claims. Must be called inside `with conn:`."""
    conn.execute(
        "DELETE FROM claims WHERE occurrence_id = ? AND prompt_version = ?"
        if occurrence_id is not None
        else "DELETE FROM claims WHERE article_id = ? AND occurrence_id IS NULL AND prompt_version = ?",
        (occurrence_id, CLAIMS_PROMPT_VERSION)
        if occurrence_id is not None
        else (article_id, CLAIMS_PROMPT_VERSION),
    )
    saved = dropped = 0
    for validated, _decision in classified:
        if not validated:
            dropped += 1
            continue
        conn.execute(
            """
            INSERT INTO claims
                (article_id, occurrence_id, story_id, claim_text, claim_type, entities,
                 evidence_span, confidence, prompt_version, validation_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                article_id,
                occurrence_id,
                story_id,
                validated["claim_text"],
                validated["claim_type"],
                json.dumps(validated["entities"], ensure_ascii=False),
                validated["evidence_span"],
                validated["confidence"],
                CLAIMS_PROMPT_VERSION,
                CLAIMS_VALIDATION_VERSION,
            ),
        )
        saved += 1
    conn.execute(
        """
        INSERT INTO claim_extractions
            (extraction_key, occurrence_id, article_id, prompt_version, story_id,
             content_hash, claims_count, extractor_model, validation_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(extraction_key, prompt_version) DO UPDATE SET
            occurrence_id = excluded.occurrence_id,
            article_id = excluded.article_id,
            story_id = excluded.story_id,
            content_hash = excluded.content_hash,
            claims_count = excluded.claims_count,
            extractor_model = excluded.extractor_model,
            validation_version = excluded.validation_version,
            extracted_at = CURRENT_TIMESTAMP
        """,
        (
            _extraction_key(article_id, occurrence_id),
            occurrence_id,
            article_id,
            CLAIMS_PROMPT_VERSION,
            story_id,
            content_hash,
            saved,
            CLAIMS_MODEL,
            CLAIMS_VALIDATION_VERSION,
        ),
    )
    return saved, dropped


def get_claims_for_story(
    story_id,
    as_of_date=None,
    history_days=7,
    *,
    db_path,
):
    """Return current and recent claims for a story.

    When ``as_of_date`` is provided, the result is bounded to an inclusive
    editorial-day window. Occurrence dates take precedence over mutable
    article rows.
    """
    conn = get_db(db_path)
    try:
        has_articles = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'articles'"
        ).fetchone()
        has_occurrences = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'article_occurrences'"
        ).fetchone()
        date_clause = ""
        date_params = []
        if as_of_date is not None:
            end = date.fromisoformat(str(as_of_date))
            start = end - timedelta(days=max(1, int(history_days)) - 1)
            date_clause = " AND COALESCE(o.editorial_date, a.date) BETWEEN ? AND ?"
            date_params = [start.isoformat(), end.isoformat()]
        if has_articles and has_occurrences:
            rows = conn.execute(
                """
                SELECT c.claim_id, c.article_id, c.occurrence_id,
                       c.claim_text, c.claim_type,
                       c.entities, c.evidence_span, c.confidence,
                       COALESCE(o.source, a.source) AS source,
                       COALESCE(o.source_id, a.source_id) AS source_id,
                       COALESCE(o.title, a.title) AS article_title,
                       COALESCE(o.url, a.url) AS url,
                       COALESCE(o.editorial_date, a.date) AS editorial_date
                FROM claims c
                LEFT JOIN article_occurrences o
                  ON o.occurrence_id = c.occurrence_id
                LEFT JOIN occurrence_assignments oa
                  ON oa.occurrence_id = c.occurrence_id
                LEFT JOIN articles a
                  ON (a.occurrence_id = c.occurrence_id)
                  OR (c.occurrence_id IS NULL
                      AND a.id = c.article_id AND a.story_id = c.story_id)
                WHERE c.story_id = ?
                  AND c.prompt_version = ?
                  AND c.validation_version = ?
                  AND (c.occurrence_id IS NULL OR oa.story_id = c.story_id)
                """ + date_clause + """
                GROUP BY c.claim_id
                ORDER BY editorial_date DESC, c.confidence DESC
                """,
                (
                    story_id,
                    CLAIMS_PROMPT_VERSION,
                    CLAIMS_VALIDATION_VERSION,
                    *date_params,
                ),
            ).fetchall()
        elif has_articles:
            rows = conn.execute(
                """
                SELECT c.claim_id, c.article_id, c.occurrence_id,
                       c.claim_text, c.claim_type, c.entities, c.evidence_span,
                       c.confidence, a.source, a.source_id,
                       a.title AS article_title, a.url, a.date AS editorial_date
                FROM claims c
                LEFT JOIN articles a
                  ON a.id = c.article_id AND a.story_id = c.story_id
                WHERE c.story_id = ?
                  AND c.prompt_version = ?
                  AND c.validation_version = ?
                GROUP BY c.claim_id
                ORDER BY editorial_date DESC, c.confidence DESC
                """,
                (story_id, CLAIMS_PROMPT_VERSION, CLAIMS_VALIDATION_VERSION),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT claim_id, article_id, occurrence_id, claim_text, claim_type,
                       entities, evidence_span, confidence,
                       NULL AS source, NULL AS source_id, NULL AS article_title,
                       NULL AS url, NULL AS editorial_date
                FROM claims
                WHERE story_id = ?
                  AND prompt_version = ?
                  AND validation_version = ?
                ORDER BY confidence DESC
                """,
                (story_id, CLAIMS_PROMPT_VERSION, CLAIMS_VALIDATION_VERSION),
            ).fetchall()
        return [
            {
                "claim_id":     r["claim_id"],
                "article_id":   r["article_id"],
                "occurrence_id": r["occurrence_id"],
                "claim_text":   r["claim_text"],
                "claim_type":   r["claim_type"],
                "entities":     json.loads(r["entities"] or "[]"),
                "evidence_span": r["evidence_span"],
                "confidence":   r["confidence"],
                "source":       r["source"],
                "source_id":    r["source_id"],
                "article_title": r["article_title"],
                "url":          r["url"],
                "editorial_date": r["editorial_date"],
            }
            for r in rows
        ]
    finally:
        conn.close()
