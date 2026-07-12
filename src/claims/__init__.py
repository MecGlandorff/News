from __future__ import annotations

from pathlib import Path

from src.claims import content, extraction, schema, store, validation, verifier
from src.claims.constants import (
    CLAIMS_MODEL,
    CLAIMS_PROMPT,
    CLAIMS_PROMPT_VERSION,
    CLAIMS_VALIDATION_VERSION,
    CLAIMS_VERIFIER_MODEL,
    CLAIMS_VERIFIER_PROMPT,
    CLAIMS_VERIFIER_PROMPT_VERSION,
    CLAIM_TYPES,
)
from src.claims.types import ClaimRecord, ClaimStats
from src.config import CLAIMS_CONTENT_CHAR_LIMIT
from src.llm import get_openai_client


DB_PATH = Path("data/stories.db")

article_claim_content = content.article_claim_content
collect_verifier_metrics = verifier.collect_verifier_metrics
_number_tokens = validation._number_tokens
_derivability_check = validation._derivability_check


def _get_db():
    return schema.get_db(DB_PATH)


def _uncached_verifier_completion(claim_text, evidence_span):
    return verifier._uncached_verifier_completion(
        claim_text,
        evidence_span,
        get_openai_client,
    )


def _verify_claim_with_llm(claim_text, evidence_span):
    return verifier.verify_claim_with_llm(
        claim_text,
        evidence_span,
        get_openai_client,
        _uncached_verifier_completion,
    )


def call_claim_extractor(content_text, client=None):
    return extraction.call_claim_extractor(
        content_text,
        client=client,
        client_factory=get_openai_client,
    )


def _call_llm(content_text):
    claims, _response = call_claim_extractor(content_text)
    return claims


def validate_claims_for_content(claims_data, content_text):
    return validation.validate_claims_for_content(
        claims_data,
        content_text,
        _verify_claim_with_llm,
    )


def _classify_claims(claims_data, content_text):
    return validation.classify_claims(
        claims_data,
        content_text,
        _verify_claim_with_llm,
    )


def _empty_claim_stats() -> ClaimStats:
    return extraction._empty_claim_stats()


def extract_and_save_claims(
    tracked,
    *,
    db_path=None,
    client_factory=None,
    verify_claim=None,
) -> ClaimStats:
    if client_factory is None:
        call_llm = _call_llm
        verifier_callback = verify_claim or _verify_claim_with_llm
    else:
        def call_llm(text):
            return extraction.call_claim_extractor(
                text,
                client_factory=client_factory,
            )[0]

        def default_verifier(claim_text, evidence_span):
            return verifier.verify_claim_with_llm(
                claim_text,
                evidence_span,
                client_factory,
                lambda claim, evidence: verifier._uncached_verifier_completion(
                    claim,
                    evidence,
                    client_factory,
                ),
            )

        verifier_callback = verify_claim or default_verifier

    return extraction.extract_and_save_claims(
        tracked,
        db_path=Path(db_path) if db_path is not None else DB_PATH,
        call_llm=call_llm,
        classify_claims=lambda claims_data, text: validation.classify_claims(
            claims_data,
            text,
            verifier_callback,
        ),
    )


def get_claims_for_story(
    story_id,
    as_of_date=None,
    history_days=7,
    *,
    db_path=None,
) -> list[ClaimRecord]:
    return store.get_claims_for_story(
        story_id,
        as_of_date=as_of_date,
        history_days=history_days,
        db_path=Path(db_path) if db_path is not None else DB_PATH,
    )


__all__ = [
    "CLAIMS_MODEL",
    "CLAIMS_CONTENT_CHAR_LIMIT",
    "CLAIMS_PROMPT",
    "CLAIMS_PROMPT_VERSION",
    "CLAIMS_VALIDATION_VERSION",
    "CLAIMS_VERIFIER_MODEL",
    "CLAIMS_VERIFIER_PROMPT",
    "CLAIMS_VERIFIER_PROMPT_VERSION",
    "CLAIM_TYPES",
    "ClaimRecord",
    "ClaimStats",
    "article_claim_content",
    "call_claim_extractor",
    "collect_verifier_metrics",
    "extract_and_save_claims",
    "get_claims_for_story",
    "validate_claims_for_content",
]
