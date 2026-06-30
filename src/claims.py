import json
import logging
import re
import sqlite3
import hashlib
from pathlib import Path

from src import observability
from src.config import CLAIMS_MODEL
from src.llm import (
    create_cached_chat_completion,
    create_chat_completion,
    get_openai_client,
    mark_schema_failure,
    parse_json_object,
    save_cached_chat_completion,
)
from src.number_normalization import normalized_number_tokens

DB_PATH = Path("data/stories.db")
logger = logging.getLogger(__name__)

CLAIMS_PROMPT_VERSION = "2026-05-13-v1"
CLAIMS_VERIFIER_MODEL = CLAIMS_MODEL
CLAIMS_VERIFIER_PROMPT_VERSION = "2026-05-14-v1"
CLAIM_TYPES = {"fact", "number", "quote", "prediction", "allegation", "background"}

CLAIMS_PROMPT = """You are extracting atomic claims from a news article.

For each significant factual statement that helps track a real news event, extract:
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
- allegation: disputed, unconfirmed, contested, reported by one side, sourced to
  unnamed officials, or phrased with says/claims/alleges/according to/reports
- background: context that is not a new development in today's reporting and is
  needed to understand the event

Focus on:
- Specific named decisions, facts, and events
- Quoted statements from identified people
- Disputed, contested, or one-sided claims (mark as allegation and preserve the attribution)
- Significant numbers or dates

Skip:
- Vague background sentences with no specific claim
- Background identity labels unless they are necessary to understand the event
- Claims already fully covered by another claim in your list
- Claims that require adding facts not present in the evidence_span

Atomicity and support rules:
- Extract one claim per event development. Split long sentences that combine
  separate actions, dates, charges, outcomes, or actors.
- The claim_text must not add facts beyond the evidence_span. If the evidence says
  "top Democrat Hakeem Jeffries", do not add "House minority leader" unless that
  exact role appears in the evidence_span.
- If a claim is based on a source's assertion, keep that source in claim_text and
  use claim_type "allegation" unless the article independently confirms it.
- Do not convert article theses, analysis headlines, or broad interpretations into
  fact claims unless the article states a concrete development.

Return a JSON object with key "claims": array of {claim_text, claim_type, entities, evidence_span, confidence}.
If the article contains no extractable claims, return {"claims": []}."""


CLAIMS_VERIFIER_PROMPT = """You verify whether a single news evidence span supports a single claim.

Inputs:
- claim_text: one factual sentence the claim asserts
- evidence_span: a sentence or short passage taken from a news article

Decide whether the evidence_span supports claim_text.

Mark supported=true only when:
- evidence_span states what claim_text asserts, or
- evidence_span attributes it via "said", "told", "announced", "reported", or
- claim_text is a faithful paraphrase that adds no facts, named roles, numbers, dates, or actors beyond the evidence_span.

Mark supported=false when:
- claim_text adds any fact, named role, number, date, or actor that does not appear in evidence_span, or
- claim_text changes the strength, direction, or attribution of what evidence_span says, or
- you are unsure.

Return a JSON object: {"supported": true | false, "reason": "<one short sentence>"}.
"""


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


def _clean_article_part(text):
    return re.sub(r"\s+", " ", _strip_html(text)).strip()


def article_claim_content(article, include_full_text=True):
    title = _clean_article_part(article.get("title"))
    description = _clean_article_part(article.get("description"))
    parts = [title, description]
    full_text = _clean_article_part(article.get("text")) if include_full_text else ""
    if include_full_text and full_text:
        parts.append(full_text)
    return "\n\n".join(part for part in parts if part)


def _article_content(article):
    return article_claim_content(article, include_full_text=True)


def _article_content_hash(content):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _normalize_for_span_match(text):
    return re.sub(r"\s+", " ", text or "").strip().casefold()


def _evidence_in_content(evidence_span, content):
    normalized_span = _normalize_for_span_match(evidence_span)
    if not normalized_span:
        return False
    return normalized_span in _normalize_for_span_match(content)


_WORD_PATTERN = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?")

# English-only for now; move this to configuration before broadening multilingual derivability.
_DERIVABILITY_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "had",
    "has",
    "have",
    "in",
    "is",
    "it",
    "its",
    "near",
    "of",
    "on",
    "or",
    "said",
    "says",
    "that",
    "the",
    "their",
    "to",
    "was",
    "were",
    "with",
}


def _number_tokens(text):
    return normalized_number_tokens(text)


def _word_tokens(text):
    return set(_WORD_PATTERN.findall(_normalize_for_span_match(text)))


def _entity_tokens(entities):
    tokens = set()
    for entity in entities or []:
        tokens.update(_word_tokens(entity))
    return tokens


def _has_strong_non_entity_overlap(claim_text, evidence_span, entities):
    entity_tokens = _entity_tokens(entities)
    claim_tokens = _word_tokens(claim_text) - entity_tokens - _DERIVABILITY_STOPWORDS
    span_tokens = _word_tokens(evidence_span) - entity_tokens - _DERIVABILITY_STOPWORDS
    return len(claim_tokens & span_tokens) >= 2


def _derivability_check(claim_text, evidence_span, entities):
    """Decide whether evidence_span deterministically supports claim_text.

    Returns one of:
      "reject"    — a number in claim_text is missing from evidence_span.
      "accept"    — evidence_span contains claim_text verbatim, or a listed
                    entity appears in evidence_span with enough non-entity
                    lexical overlap to avoid weak anaphoric spans.
      "uncertain" — neither rule applies; needs the LLM verifier.
    """
    claim_numbers = _number_tokens(claim_text)
    span_numbers = _number_tokens(evidence_span)
    if claim_numbers - span_numbers:
        return "reject"

    normalized_claim = _normalize_for_span_match(claim_text)
    normalized_span = _normalize_for_span_match(evidence_span)
    if normalized_claim and normalized_claim in normalized_span:
        return "accept"

    for entity in entities or []:
        normalized_entity = _normalize_for_span_match(entity)
        if (
            normalized_entity
            and normalized_entity in normalized_span
            and _has_strong_non_entity_overlap(claim_text, evidence_span, entities)
        ):
            return "accept"

    return "uncertain"


def _verifier_completion(claim_text, evidence_span):
    return create_cached_chat_completion(
        get_openai_client,
        model=CLAIMS_VERIFIER_MODEL,
        messages=_verifier_messages(claim_text, evidence_span),
        purpose="claim_verifier",
        prompt_version=CLAIMS_VERIFIER_PROMPT_VERSION,
        response_format={"type": "json_object"},
    )


def _uncached_verifier_completion(claim_text, evidence_span):
    return create_chat_completion(
        get_openai_client(),
        model=CLAIMS_VERIFIER_MODEL,
        messages=_verifier_messages(claim_text, evidence_span),
        purpose="claim_verifier",
        prompt_version=CLAIMS_VERIFIER_PROMPT_VERSION,
        response_format={"type": "json_object"},
    )


def _verifier_messages(claim_text, evidence_span):
    user_content = json.dumps(
        {"claim_text": claim_text, "evidence_span": evidence_span},
        ensure_ascii=False,
    )
    return [
        {"role": "system", "content": CLAIMS_VERIFIER_PROMPT},
        {"role": "user", "content": user_content},
    ]


def _verifier_supported(response):
    parsed = parse_json_object(response)
    supported = parsed.get("supported")
    if not isinstance(supported, bool):
        mark_schema_failure(
            'Model response must contain boolean "supported"',
            response=response,
        )
        raise ValueError('Model response must contain boolean "supported"')
    return supported


def _verify_claim_with_llm(claim_text, evidence_span):
    """Ask gpt-5.4-nano whether the span supports the claim. Default-reject on any error."""
    try:
        response, cache_metadata, was_cached = _verifier_completion(claim_text, evidence_span)
    except Exception:
        return False
    refreshed_bad_cache = False
    try:
        supported = _verifier_supported(response)
    except ValueError:
        if not was_cached:
            return False
        try:
            response = _uncached_verifier_completion(claim_text, evidence_span)
            supported = _verifier_supported(response)
        except Exception:
            return False
        refreshed_bad_cache = True
    if not was_cached or refreshed_bad_cache:
        try:
            save_cached_chat_completion(cache_metadata, response)
        except sqlite3.Error as exc:
            logger.warning("Claim verifier cache save failed: %s", exc)
    return supported


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


def _claim_completion(client, content):
    return create_chat_completion(
        client,
        model=CLAIMS_MODEL,
        messages=[
            {"role": "system", "content": CLAIMS_PROMPT},
            {"role": "user",   "content": content},
        ],
        purpose="claim",
        prompt_version=CLAIMS_PROMPT_VERSION,
        response_format={"type": "json_object"},
    )


def _claims_from_response(response):
    payload = parse_json_object(response)
    claims = payload.get("claims")
    if not isinstance(claims, list):
        mark_schema_failure('Model response must contain a "claims" list', response=response)
        raise ValueError('Model response must contain a "claims" list')
    return claims


def call_claim_extractor(content, client=None):
    client = client or get_openai_client()
    response = _claim_completion(client, content)
    return _claims_from_response(response), response


def _call_llm(content):
    claims, _response = call_claim_extractor(content)
    return claims


def validate_claims_for_content(claims_data, content):
    valid_claims = []
    dropped = 0
    for claim in claims_data:
        validated, _decision = _validated_claim(claim, content)
        if not validated:
            dropped += 1
            continue
        valid_claims.append(validated)
    return valid_claims, dropped


def _classify_claims(claims_data, content):
    """Validate every claim and return [(validated_or_None, decision), ...].

    Runs the LLM verifier for uncertain claims. Must be called outside any
    open SQLite transaction so the verifier's network call does not hold a
    write lock.
    """
    return [_validated_claim(claim, content) for claim in claims_data]


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
    """Return (validated_dict_or_None, decision).

    decision is one of:
      "invalid"             — failed schema / field / span-in-article checks.
      "derivability_reject" — a number in claim_text is missing from evidence_span.
      "cheap_accept"        — deterministic accept (entity or verbatim overlap).
      "verifier_accept"     — LLM verifier confirmed support.
      "verifier_reject"     — LLM verifier rejected support or failed.
    """
    if not isinstance(claim, dict):
        return None, "invalid"

    claim_text = _clean_string(claim.get("claim_text"))
    claim_type = _clean_string(claim.get("claim_type"))
    evidence_span = _clean_string(claim.get("evidence_span"))
    entities = claim.get("entities")
    confidence = _validated_confidence(claim.get("confidence"))

    if not claim_text or claim_type not in CLAIM_TYPES:
        return None, "invalid"
    if not isinstance(entities, list):
        return None, "invalid"
    if not all(isinstance(entity, str) and entity.strip() for entity in entities):
        return None, "invalid"
    if not evidence_span or not _evidence_in_content(evidence_span, content):
        return None, "invalid"
    if confidence is None:
        return None, "invalid"

    cleaned_entities = [entity.strip() for entity in entities]
    derivability = _derivability_check(claim_text, evidence_span, cleaned_entities)
    if derivability == "reject":
        return None, "derivability_reject"
    if derivability == "uncertain":
        if not _verify_claim_with_llm(claim_text, evidence_span):
            return None, "verifier_reject"
        decision = "verifier_accept"
    else:
        decision = "cheap_accept"

    return {
        "claim_text": claim_text,
        "claim_type": claim_type,
        "entities": cleaned_entities,
        "evidence_span": evidence_span,
        "confidence": confidence,
    }, decision


def _write_classified_claims(article_id, story_id, content_hash, classified, conn):
    """Persist already-validated claims. Must be called inside `with conn:`."""
    conn.execute(
        "DELETE FROM claims WHERE article_id = ? AND prompt_version = ?",
        (article_id, CLAIMS_PROMPT_VERSION),
    )
    saved = dropped = 0
    for validated, _decision in classified:
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


def _empty_claim_stats():
    return {
        "articles_extracted": 0,
        "claims_saved": 0,
        "cached": 0,
        "invalid": 0,
        "failed": 0,
        "zero_claim_results": 0,
        "claim_derivable_accepts": 0,
        "claim_verifier_calls": 0,
        "claim_verifier_accepts": 0,
        "claim_verifier_rejects": 0,
    }


def extract_and_save_claims(tracked):
    """Extract claims for all tracked articles and save to DB.

    Claims are saved directly with story_id — no back-fill needed because
    tracked articles already carry story_id assigned by the tracker.
    Articles whose claims are already cached at the current prompt version
    are skipped entirely.
    """
    if not tracked:
        return _empty_claim_stats()

    conn = _get_db()
    extracted = skipped = failed = invalid = saved_claims = zero_claim_results = 0
    cheap_accepts = verifier_calls = verifier_accepts = verifier_rejects = 0
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
                observability.increment_cache_hits()
                continue

            with conn:
                _delete_cached_claims(article_id, conn)

            try:
                claims_data = _call_llm(content)
            except Exception as exc:
                logger.warning("Claims extraction failed for %s: %s", article_id, exc)
                failed += 1
                continue

            # Classify outside the SQLite transaction so the verifier's
            # network call does not hold a write lock.
            classified = _classify_claims(claims_data, content)
            for _validated, decision in classified:
                if decision == "cheap_accept":
                    cheap_accepts += 1
                elif decision == "verifier_accept":
                    verifier_calls += 1
                    verifier_accepts += 1
                elif decision == "verifier_reject":
                    verifier_calls += 1
                    verifier_rejects += 1

            with conn:
                saved, dropped = _write_classified_claims(
                    article_id,
                    story_id,
                    content_hash,
                    classified,
                    conn,
                )
                saved_claims += saved
                invalid += dropped
                if saved == 0:
                    zero_claim_results += 1
            extracted += 1
    finally:
        conn.close()

    logger.info(
        f"Claims: {extracted} extracted, {skipped} cached"
        + (f", {invalid} invalid" if invalid else "")
        + (f", {failed} failed" if failed else ""),
    )
    return {
        "articles_extracted": extracted,
        "claims_saved": saved_claims,
        "cached": skipped,
        "invalid": invalid,
        "failed": failed,
        "zero_claim_results": zero_claim_results,
        "claim_derivable_accepts": cheap_accepts,
        "claim_verifier_calls": verifier_calls,
        "claim_verifier_accepts": verifier_accepts,
        "claim_verifier_rejects": verifier_rejects,
    }


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
