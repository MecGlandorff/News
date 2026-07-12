import logging

from src import observability
from src.claims.constants import (
    CLAIMS_MODEL,
    CLAIMS_PROMPT,
    CLAIMS_PROMPT_VERSION,
)
from src.claims.content import _article_content, _article_content_hash
from src.config import CLAIMS_CONTENT_CHAR_LIMIT
from src.claims.schema import get_db
from src.claims.store import (
    _delete_cached_claims,
    _has_cached_claims,
    _write_classified_claims,
)
from src.llm import create_chat_completion, mark_schema_failure, parse_json_object


logger = logging.getLogger(__name__)


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


def call_claim_extractor(content, client=None, client_factory=None):
    client = client or client_factory()
    response = _claim_completion(client, content)
    return _claims_from_response(response), response


def empty_claim_stats():
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
        "content_truncations": 0,
    }


def extract_and_save_claims(
    tracked,
    *,
    db_path,
    call_llm,
    classify_claims,
):
    """Extract claims for all tracked articles and save to DB.

    Claims are saved directly with story_id — no back-fill needed because
    tracked articles already carry story_id assigned by the tracker.
    Articles whose claims are already cached at the current prompt version
    are skipped entirely.
    """
    if not tracked:
        return empty_claim_stats()

    conn = get_db(db_path)
    extracted = skipped = failed = invalid = saved_claims = zero_claim_results = 0
    cheap_accepts = verifier_calls = verifier_accepts = verifier_rejects = 0
    content_truncations = 0
    try:
        for article in tracked:
            article_id = str(article["id"])
            occurrence_id = article.get("occurrence_id")
            story_id   = article.get("story_id")
            content, was_truncated = _article_content(article)
            if not content:
                continue
            if was_truncated:
                content_truncations += 1
                logger.info(
                    "Truncated claim input for article %s to %s characters",
                    article_id,
                    CLAIMS_CONTENT_CHAR_LIMIT,
                )

            content_hash = _article_content_hash(content)
            if _has_cached_claims(
                article_id,
                occurrence_id,
                story_id,
                content_hash,
                conn,
            ):
                skipped += 1
                observability.increment_cache_hits(layer="claims")
                continue

            with conn:
                _delete_cached_claims(article_id, occurrence_id, conn)

            try:
                claims_data = call_llm(content)
            except Exception as exc:
                logger.warning("Claims extraction failed for %s: %s", article_id, exc)
                failed += 1
                continue

            # Classify outside the SQLite transaction so the verifier's
            # network call does not hold a write lock.
            classified = classify_claims(claims_data, content)
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
                    occurrence_id,
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
        "content_truncations": content_truncations,
    }
