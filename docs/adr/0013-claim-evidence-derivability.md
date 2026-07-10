# ADR 0013: Claim evidence derivability gate

**Date:** 2026-05-13

**2026-07-11 follow-up:** The deterministic entity-plus-lexical shortcut was removed after adversarial examples showed that it accepted negation, direction, and unit contradictions. Claim-cache reuse now includes an independent validation-policy version.

## Status

Accepted.

## Context

Before this change, claim extraction validated only that `evidence_span` appeared (case-folded, whitespace-normalized) as a substring of the article. It did **not** verify that `claim_text` was actually supported by `evidence_span`. A model could pair any article sentence with any claim and pass validation. The README oversold this as "claims require evidence spans that appear in source text before they are stored" — true, but load-bearing on a check that did not exist.

The flagship pitch of this repo is *source-grounded event memory*. A claim that adds facts, roles, numbers, dates, or attribution beyond its evidence span is exactly the failure mode the trust layer is supposed to catch.

## Decision

Add a conservative derivability gate between `claim_text` and `evidence_span` in `src/claims.py`:

1. **Deterministic reject** — reject missing quantities and explicit negation, semantic-direction, or numeric-unit mismatches. No verifier call.
2. **Deterministic accept** — accept only when normalized `claim_text` is contained in `evidence_span`.
3. **LLM verifier** — route every other paraphrase, including entity-overlap and anaphoric spans, to `gpt-5.4-nano`. The verifier returns `{"supported": true | false, "reason": "..."}` and uses the exact-response cache.

`CLAIMS_VALIDATION_VERSION` is stored with claims and extraction-cache rows. Prompt version, model, content hash, and validation version must all match before claims can be reused.

Verifier failures (network error, JSON parse error, unexpected payload) default to **reject**. The verifier prompt instructs the model to mark `false` when unsure, so failures and uncertainty both drop the claim.

Run-level counters are added to `runs`:

- `claim_derivable_accepts` — accepted by deterministic rule 2
- `claim_verifier_calls` — uncertain claims sent to the LLM verifier
- `claim_verifier_accepts` — verifier returned `supported: true`
- `claim_verifier_rejects` — verifier returned `false`, failed, or errored

These counters surface in `--pipeline-report` and `run_artifacts/`. Rejected claims are dropped as before; accepted claims store the validation version used.

Validation runs **outside** the SQLite transaction so the verifier's network call does not hold a write lock.

## Consequences

- Closes the gap between the README's trust-layer claim and what the code enforces.
- Near-verbatim claims are decided for free. All other paraphrases pay for the verifier call, favoring trust over the previous lexical shortcut's lower cost.
- Verifier cost is bounded by `gpt-5.4-nano` pricing on short prompts; cache reuse keeps reruns cheap.
- Tests can monkeypatch `_verify_claim_with_llm` to keep unit tests offline.

## What this does not do

- Deterministic direction and common-unit guards are intentionally narrow; unusual wording still reaches the verifier rather than being inferred locally.
- It does not add per-claim audit rows; if we want to inspect which claims took which path, that needs a future `verification_status` column on `claims`.

## What the eval still owes

Before broadening the verifier (e.g., trusting it for source-divergence labels), `evals/datasets/golden_claims.jsonl` should grow to include reviewed paraphrase cases — claims where the deterministic gate cannot decide and the verifier's accept/reject is the only signal. Until those cases exist, the verifier's accuracy is asserted by tests using mocks, not measured against real reviewed claims.
