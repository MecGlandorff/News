from __future__ import annotations

from typing import TypedDict


class ClaimStats(TypedDict):
    articles_extracted: int
    claims_saved: int
    cached: int
    invalid: int
    failed: int
    zero_claim_results: int
    claim_derivable_accepts: int
    claim_verifier_calls: int
    claim_verifier_accepts: int
    claim_verifier_rejects: int
    content_truncations: int


class ClaimRecord(TypedDict, total=False):
    claim_id: int
    article_id: str
    occurrence_id: int | None
    story_id: int | None
    claim_text: str
    claim_type: str
    entities: list[str]
    evidence_span: str
    confidence: float
    source: str | None
    source_id: int | None
    article_title: str | None
    url: str | None
    editorial_date: str | None
