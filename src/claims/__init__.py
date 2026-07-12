from __future__ import annotations

from pathlib import Path

from src.claims import content, extraction, store, validation, verifier
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


def _claim_verifier(client_factory):
    def uncached_completion(claim_text, evidence_span):
        return verifier._uncached_verifier_completion(
            claim_text,
            evidence_span,
            client_factory,
        )

    def verify_claim(claim_text, evidence_span):
        return verifier.verify_claim_with_llm(
            claim_text,
            evidence_span,
            client_factory,
            uncached_completion,
        )

    return verify_claim


def call_claim_extractor(content_text, client=None, *, client_factory=None):
    resolved_client_factory = (
        client_factory if client_factory is not None else get_openai_client
    )
    return extraction.call_claim_extractor(
        content_text,
        client=client,
        client_factory=resolved_client_factory,
    )


def validate_claims_for_content(
    claims_data,
    content_text,
    *,
    verify_claim=None,
    client_factory=None,
):
    resolved_client_factory = (
        client_factory if client_factory is not None else get_openai_client
    )
    verifier_callback = (
        verify_claim
        if verify_claim is not None
        else _claim_verifier(resolved_client_factory)
    )
    return validation.validate_claims_for_content(
        claims_data,
        content_text,
        verifier_callback,
    )


def classify_claims_for_content(
    claims_data,
    content_text,
    *,
    verify_claim=None,
    client_factory=None,
):
    resolved_client_factory = (
        client_factory if client_factory is not None else get_openai_client
    )
    verifier_callback = (
        verify_claim
        if verify_claim is not None
        else _claim_verifier(resolved_client_factory)
    )
    return validation.classify_claims(
        claims_data,
        content_text,
        verifier_callback,
    )


def empty_claim_stats() -> ClaimStats:
    return extraction.empty_claim_stats()


def extract_and_save_claims(
    tracked,
    *,
    db_path=None,
    client_factory=None,
    verify_claim=None,
) -> ClaimStats:
    resolved_client_factory = (
        client_factory if client_factory is not None else get_openai_client
    )

    def call_llm(text):
        return extraction.call_claim_extractor(
            text,
            client_factory=resolved_client_factory,
        )[0]

    verifier_callback = (
        verify_claim
        if verify_claim is not None
        else _claim_verifier(resolved_client_factory)
    )

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
    "classify_claims_for_content",
    "collect_verifier_metrics",
    "empty_claim_stats",
    "extract_and_save_claims",
    "get_claims_for_story",
    "validate_claims_for_content",
]
