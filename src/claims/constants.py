from src.config import CLAIMS_MODEL


CLAIMS_PROMPT_VERSION = "2026-05-13-v1"

CLAIMS_VALIDATION_VERSION = "2026-07-11-v1"

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
