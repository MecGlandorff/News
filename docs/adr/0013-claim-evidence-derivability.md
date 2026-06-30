# ADR 0013: Claim evidence derivability gate

**Date:** 2026-05-13

## Status

Accepted.

## Context

Before this change, claim extraction validated only that `evidence_span` appeared (case-folded, whitespace-normalized) as a substring of the article. It did **not** verify that `claim_text` was actually supported by `evidence_span`. A model could pair any article sentence with any claim and pass validation. The README oversold this as "claims require evidence spans that appear in source text before they are stored" — true, but load-bearing on a check that did not exist.

The flagship pitch of this repo is *source-grounded event memory*. A claim that adds facts, roles, numbers, dates, or attribution beyond its evidence span is exactly the failure mode the trust layer is supposed to catch.

## Decision

Add a hybrid derivability gate between `claim_text` and `evidence_span` in `src/claims.py`:

1. **Deterministic reject** — if any number in `claim_text` (integer, decimal, percentage, or thousands-separated value, with decimal commas preserved as decimals) does not appear in `evidence_span`, reject immediately. No verifier call.
2. **Deterministic accept** — if `claim_text` (normalized) is contained in `evidence_span`, or if entity overlap is backed by enough non-entity lexical overlap, accept immediately.
3. **LLM verifier** for the ambiguous middle — call `gpt-5.4-nano` with a small prompt that asks whether the span supports the claim and returns `{"supported": true | false, "reason": "..."}`. Weak entity-only or anaphoric spans are routed here instead of being accepted deterministically. The verifier uses its own prompt version `CLAIMS_VERIFIER_PROMPT_VERSION = "2026-05-14-v1"` and reuses the existing `llm_response_cache` table via the standard `create_cached_chat_completion` path.

Verifier failures (network error, JSON parse error, unexpected payload) default to **reject**. The verifier prompt instructs the model to mark `false` when unsure, so failures and uncertainty both drop the claim.

Run-level counters are added to `runs`:

- `claim_derivable_accepts` — accepted by deterministic rule 2
- `claim_verifier_calls` — uncertain claims sent to the LLM verifier
- `claim_verifier_accepts` — verifier returned `supported: true`
- `claim_verifier_rejects` — verifier returned `false`, failed, or errored

These counters surface in `--pipeline-report` and `run_artifacts/`. No new columns are added to `claims`; rejected claims are dropped silently as before.

Validation runs **outside** the SQLite transaction so the verifier's network call does not hold a write lock.

## Consequences

- Closes the gap between the README's trust-layer claim and what the code enforces.
- Most claims are decided for free (deterministic gate). Paraphrases without strong overlap and weak anaphoric spans pay for the verifier call.
- Verifier cost is bounded by `gpt-5.4-nano` pricing on short prompts; cache reuse keeps reruns cheap.
- Tests can monkeypatch `_verify_claim_with_llm` to keep unit tests offline.

## What this does not do

- It does not check semantic *direction* changes that the verifier prompt may miss (e.g., "fell" vs "rose" when the verifier returns `true` anyway). The eval harness is the right place to measure this.
- It does not detect numeric *unit* mismatches when the digits coincide (e.g., "$1.5 million" vs "$1.5 billion" both extract `1.5`). The verifier may catch this; reviewed eval cases are still needed.
- It does not add per-claim audit rows; if we want to inspect which claims took which path, that needs a future `verification_status` column on `claims`.

## What the eval still owes

Before broadening the verifier (e.g., trusting it for source-divergence labels), `evals/datasets/golden_claims.jsonl` should grow to include reviewed paraphrase cases — claims where the deterministic gate cannot decide and the verifier's accept/reject is the only signal. Until those cases exist, the verifier's accuracy is asserted by tests using mocks, not measured against real reviewed claims.
