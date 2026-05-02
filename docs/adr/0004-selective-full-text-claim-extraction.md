# ADR 0004: Selective full-text claim extraction

**Date:** 2026-05-02  
**Status:** Accepted

---

## Context

The claim extractor turns article input into structured claims with evidence spans. It currently uses `gpt-5.4-mini`, runs only when `--show-evidence` is enabled, reads RSS title/description, and stores claims in SQLite for reuse.

Two input strategies are available:

**Option A: RSS title and description by default**  
Use the compact text already available from each feed item. This is cheaper and faster, but evidence spans are limited by RSS quality.

**Option B: Full article text for every article**  
Use fetched article body text whenever available. This can improve evidence quality, but increases network work, input tokens, output claims, latency, and total run cost.

The project currently spends about EUR 1.20 per full run. Moving every claim extraction to full text could materially increase cost before the system can measure token and latency impact per pipeline stage.

---

## Decision

Keep claim extraction cost-conscious by default.

Use RSS title and description for broad claim extraction. In the planned claim-hardening pass, use full article text selectively for high-importance or briefing-worthy stories when `--fetch-article-text` is enabled. Do not make full-text claim extraction for every article the default until Phase 3 observability exists through `runs`, `llm_calls`, and `--pipeline-report`.

---

## Rationale

**Evidence quality matters most on selected stories.** The briefing only surfaces a subset of stories. Spending extra tokens on every low-importance article does not improve the final intelligence artifact enough to justify the cost.

**Cost should be measured before expanding.** Full-text extraction affects both input and output tokens. Longer article bodies may produce more extracted claims, and claim JSON is output-token heavy. The system should record token, cost, and latency data before adopting full text everywhere.

**Caching should stay ahead of input expansion.** The claim layer caches by input content hash, caches zero-claim results, and keeps cached claims aligned with current story assignment. Full-text expansion should preserve those properties.

**The CLI stays understandable.** `--show-evidence` enables claim extraction. `--fetch-article-text` fetches article body text and should become the input source for selective higher-quality evidence. This is clear enough without adding another flag yet.

---

## Consequences

**Positive:**
- Keeps normal runs affordable
- Improves evidence quality where it matters most
- Preserves a path to full-text-for-all extraction later
- Avoids committing to a more expensive behavior before observability exists

**Negative:**
- Claims for non-selected stories may remain shallow
- Evidence quality can vary between RSS-only and full-text-backed articles
- Selective full-text policy requires clear implementation rules when added

---

## Near-term implementation guidance

Phase 2 hardening should:

- compute a claim input content hash
- preserve zero-claim extraction caching
- preserve cached-claim invalidation when article content changes
- keep cached claim `story_id` aligned with the current tracked story
- render evidence with source and article context

Phase 3 should add `runs`, `llm_calls`, and `--pipeline-report` before revisiting Option B as the default.

---

## Alternatives rejected

**Full-text claims for every article now:** Better grounding, but too expensive to adopt blindly without per-stage observability.

**RSS-only claims forever:** Cheap, but not strong enough for high-confidence evidence in important stories.

**Separate full-text-claims flag now:** More control, but premature CLI complexity. The existing `--show-evidence --fetch-article-text` combination is the intended interface once selective full-text evidence is implemented.

---

## Review trigger

Revisit this decision when:
- `runs` and `llm_calls` record token, cost, and latency metrics
- `--pipeline-report` can show claim-extraction cost separately
- source agreement depends on richer claim evidence for more than the displayed briefing stories
- average run cost remains acceptable with selective full-text evidence enabled
