import json
import re
import sqlite3
import hashlib
from pathlib import Path

from src.config import CLAIMS_MODEL
from src.llm import get_openai_client, parse_json_object

DB_PATH = Path("data/stories.db")

CLAIMS_PROMPT_VERSION = "2026-05-03-v1"
CLAIM_TYPES = {"fact", "number", "quote", "prediction", "allegation", "background"}

CLAIMS_PROMPT = """You are extracting atomic claims from a news article.

For each significant factual statement, extract:
- claim_text: the claim restated as one clear English sentence
- claim_type: one of: fact | number | quote | prediction | allegation | background
- entities: list of named entities involved (person name, organization, country, etc.)
- evidence_span: the exact sentence or phrase from the article that supports this claim
- confidence: float 0.0–1.0 (how clearly stated and directly supported this claim is)

Claim type guidance:
- fact: something reported as established or confirmed
- number: a specific quantity, percentage, date, or monetary amount
- quote: a direct quote attributed to a named person
- prediction: something stated as likely to happen
- allegation: disputed, unconfirmed, or attributed to one side only
- background: context that is not a new development in today's reporting

Focus on:
- Specific named decisions, facts, and events
- Quoted statements from identified people
- Disputed or contested claims (mark as allegation)
- Significant numbers or dates

Skip:
- Vague background sentences with no specific claim
- Claims already fully covered by another claim in your list

Return a JSON object with key "claims": array of {claim_text, claim_type, entities, evidence_span, confidence}.
If the article contains no extractable claims, return {"claims": []}."""


def _get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS claims (
            claim_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id     TEXT NOT NULL,
            story_id       INTEGER,
            claim_text     TEXT NOT NULL,
            claim_type     TEXT,
            entities       TEXT,
            evidence_span  TEXT,
            confidence     REAL,
            prompt_version TEXT,
            created_at     TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_claims_article
            ON claims (article_id, prompt_version);
        CREATE INDEX IF NOT EXISTS idx_claims_story
            ON claims (story_id);
        CREATE TABLE IF NOT EXISTS claim_extractions (
            article_id     TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            story_id       INTEGER,
            content_hash   TEXT NOT NULL,
            claims_count   INTEGER NOT NULL,
            extracted_at   TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (article_id, prompt_version)
        );
    """)
    conn.commit()
    return conn


def _strip_html(text):
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def _article_content(article):
    title = (article.get("title") or "").strip()
    description = _strip_html(article.get("description") or "")
    return f"{title}\n\n{description}".strip()


def _article_content_hash(content):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _normalize_for_span_match(text):
    return re.sub(r"\s+", " ", text or "").strip().casefold()


def _evidence_in_content(evidence_span, content):
    normalized_span = _normalize_for_span_match(evidence_span)
    if not normalized_span:
        return False
    return normalized_span in _normalize_for_span_match(content)


def _has_cached_claims(article_id, story_id, content_hash, conn):
    row = conn.execute(
        """
        SELECT story_id, content_hash
        FROM claim_extractions
        WHERE article_id = ? AND prompt_version = ?
        """,
        (article_id, CLAIMS_PROMPT_VERSION),
    ).fetchone()
    if not row:
        return False
    if row["content_hash"] != content_hash:
        return False
    if row["story_id"] != story_id:
        conn.execute(
            """
            UPDATE claims
            SET story_id = ?
            WHERE article_id = ? AND prompt_version = ?
            """,
            (story_id, article_id, CLAIMS_PROMPT_VERSION),
        )
        conn.execute(
            """
            UPDATE claim_extractions
            SET story_id = ?, extracted_at = CURRENT_TIMESTAMP
            WHERE article_id = ? AND prompt_version = ?
            """,
            (story_id, article_id, CLAIMS_PROMPT_VERSION),
        )
        conn.commit()
    return True


def _delete_cached_claims(article_id, conn):
    conn.execute(
        "DELETE FROM claims WHERE article_id = ? AND prompt_version = ?",
        (article_id, CLAIMS_PROMPT_VERSION),
    )
    conn.execute(
        "DELETE FROM claim_extractions WHERE article_id = ? AND prompt_version = ?",
        (article_id, CLAIMS_PROMPT_VERSION),
    )


def _call_llm(content):
    client = get_openai_client()
    response = client.chat.completions.create(
        model=CLAIMS_MODEL,
        messages=[
            {"role": "system", "content": CLAIMS_PROMPT},
            {"role": "user",   "content": content},
        ],
        response_format={"type": "json_object"},
    )
    payload = parse_json_object(response)
    claims = payload.get("claims")
    if not isinstance(claims, list):
        raise ValueError('Model response must contain a "claims" list')
    return claims


def _clean_string(value):
    return value.strip() if isinstance(value, str) else ""


def _validated_confidence(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    confidence = float(value)
    if confidence < 0.0 or confidence > 1.0:
        return None
    return confidence


def _validated_claim(claim, content):
    if not isinstance(claim, dict):
        return None

    claim_text = _clean_string(claim.get("claim_text"))
    claim_type = _clean_string(claim.get("claim_type"))
    evidence_span = _clean_string(claim.get("evidence_span"))
    entities = claim.get("entities")
    confidence = _validated_confidence(claim.get("confidence"))

    if not claim_text or claim_type not in CLAIM_TYPES:
        return None
    if not isinstance(entities, list):
        return None
    if not all(isinstance(entity, str) and entity.strip() for entity in entities):
        return None
    if not evidence_span or not _evidence_in_content(evidence_span, content):
        return None
    if confidence is None:
        return None

    return {
        "claim_text": claim_text,
        "claim_type": claim_type,
        "entities": [entity.strip() for entity in entities],
        "evidence_span": evidence_span,
        "confidence": confidence,
    }


def _replace_claims(article_id, story_id, content_hash, claims_data, content, conn):
    conn.execute(
        "DELETE FROM claims WHERE article_id = ? AND prompt_version = ?",
        (article_id, CLAIMS_PROMPT_VERSION),
    )
    saved = dropped = 0
    for claim in claims_data:
        validated = _validated_claim(claim, content)
        if not validated:
            dropped += 1
            continue
        conn.execute(
            """
            INSERT INTO claims
                (article_id, story_id, claim_text, claim_type, entities,
                 evidence_span, confidence, prompt_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                article_id,
                story_id,
                validated["claim_text"],
                validated["claim_type"],
                json.dumps(validated["entities"], ensure_ascii=False),
                validated["evidence_span"],
                validated["confidence"],
                CLAIMS_PROMPT_VERSION,
            ),
        )
        saved += 1
    conn.execute(
        """
        INSERT INTO claim_extractions
            (article_id, prompt_version, story_id, content_hash, claims_count)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(article_id, prompt_version) DO UPDATE SET
            story_id = excluded.story_id,
            content_hash = excluded.content_hash,
            claims_count = excluded.claims_count,
            extracted_at = CURRENT_TIMESTAMP
        """,
        (article_id, CLAIMS_PROMPT_VERSION, story_id, content_hash, saved),
    )
    return saved, dropped


def extract_and_save_claims(tracked):
    """Extract claims for all tracked articles and save to DB.

    Claims are saved directly with story_id — no back-fill needed because
    tracked articles already carry story_id assigned by the tracker.
    Articles whose claims are already cached at the current prompt version
    are skipped entirely.
    """
    if not tracked:
        return

    conn = _get_db()
    extracted = skipped = failed = invalid = 0
    try:
        for article in tracked:
            article_id = str(article["id"])
            story_id   = article.get("story_id")
            content = _article_content(article)
            if not content:
                continue

            content_hash = _article_content_hash(content)
            if _has_cached_claims(article_id, story_id, content_hash, conn):
                skipped += 1
                continue

            with conn:
                _delete_cached_claims(article_id, conn)

            try:
                claims_data = _call_llm(content)
            except Exception as exc:
                print(f"  Claims extraction failed for {article_id}: {exc}", flush=True)
                failed += 1
                continue

            with conn:
                _, dropped = _replace_claims(
                    article_id,
                    story_id,
                    content_hash,
                    claims_data,
                    content,
                    conn,
                )
                invalid += dropped
            extracted += 1
    finally:
        conn.close()

    print(
        f"Claims: {extracted} extracted, {skipped} cached"
        + (f", {invalid} invalid" if invalid else "")
        + (f", {failed} failed" if failed else ""),
        flush=True,
    )


def get_claims_for_story(story_id):
    """Return all claims for a story, sorted by confidence descending."""
    conn = _get_db()
    try:
        has_articles = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'articles'"
        ).fetchone()
        if has_articles:
            rows = conn.execute(
                """
                SELECT c.claim_id, c.article_id, c.claim_text, c.claim_type,
                       c.entities, c.evidence_span, c.confidence,
                       a.source, a.title AS article_title, a.url
                FROM claims c
                LEFT JOIN articles a
                  ON a.id = c.article_id
                 AND a.story_id = c.story_id
                WHERE c.story_id = ?
                  AND c.prompt_version = ?
                GROUP BY c.claim_id
                ORDER BY c.confidence DESC
                """,
                (story_id, CLAIMS_PROMPT_VERSION),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT claim_id, article_id, claim_text, claim_type,
                       entities, evidence_span, confidence,
                       NULL AS source, NULL AS article_title, NULL AS url
                FROM claims
                WHERE story_id = ?
                  AND prompt_version = ?
                ORDER BY confidence DESC
                """,
                (story_id, CLAIMS_PROMPT_VERSION),
            ).fetchall()
        return [
            {
                "claim_id":     r["claim_id"],
                "article_id":   r["article_id"],
                "claim_text":   r["claim_text"],
                "claim_type":   r["claim_type"],
                "entities":     json.loads(r["entities"] or "[]"),
                "evidence_span": r["evidence_span"],
                "confidence":   r["confidence"],
                "source":       r["source"],
                "article_title": r["article_title"],
                "url":          r["url"],
            }
            for r in rows
        ]
    finally:
        conn.close()
