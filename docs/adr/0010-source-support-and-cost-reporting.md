# ADR 0010: Source support and cost reporting

**Date:** 2026-05-09
**Status:** Accepted

---

## Context

Phase 3 needs the pipeline to be inspectable before expanding expensive or autonomous behavior. The project already stores source metadata, run rows, and LLM call rows, but two important pieces were still not load-bearing:

- source counts could still rely on raw source names even when `articles.source_id` was available
- `--pipeline-report` showed tokens and latency, but not scraper failures, duplicate skips, claim-extraction counters, or estimated EUR cost

The system also cannot yet prove source agreement from claim comparison. This ADR covers the deterministic support and observability step before claim-backed agreement.

---

## Decision

Add `src/source_agreement.py` with source identity helpers:

- use `source_id` when it is present
- fall back to normalized source name for older article rows
- keep unknown sources explicit
- report distinct source count plus the identities that supported a story

Use that source identity for deterministic briefing defaults and story aggregation. This is source support, not final claim-backed agreement.

Extend run observability with scraper and claim counters:

- duplicate URL skips
- feed fetch failures
- article text fetch successes and failures
- claim articles extracted
- claim articles cached
- invalid claims dropped
- claim extraction failures
- zero-claim extraction results

Add explicit model pricing in `src/config.py` and estimate EUR cost from rows in `llm_calls`. The estimate uses standard uncached API input/output token rates and a static USD-to-EUR rate. It does not model provider-side cached-input token discounts, Batch, Flex, Priority, regional processing, or long-context uplifts.

---

## Rationale

**Source identity is the right v1.** A source row is more stable than a display name, while the name fallback keeps older databases readable.

**Cost estimates need explicit assumptions.** A hidden or live pricing lookup would make reports harder to reproduce. A visible pricing table is boring, testable, and reviewable.

**Run reports should measure the expensive path.** Full-text evidence runs add network work and token load. Scraper counts, claim counters, token totals, latency, and estimated cost together make that tradeoff visible.

**This is not claim-backed agreement.** Two articles from different source identities do not prove independent corroboration, and two articles from the same source do not prove a claim is false or unsupported. Claim comparison and source-divergence notes remain separate work.

---

## Consequences

**Positive:**
- Briefing defaults no longer overcount renamed copies from the same seeded source
- `--pipeline-report` explains scraper work, claim extraction behavior, token use, latency, and estimated EUR cost
- Full-text claim extraction can now be judged against measured cost and latency
- Older rows without `source_id` remain usable

**Negative:**
- EUR estimates can drift when model pricing or exchange rates change
- The report is an estimate, not a billing ledger
- Source support can still be inflated by syndication across distinct source IDs
- Claim-backed source agreement and source-divergence notes are still missing

---

## Review trigger

Revisit this decision when:

- OpenAI model pricing changes
- provider-side cached-input token counts are recorded
- claim-backed source agreement lands
- source-divergence notes are backed by claim comparison
- source reliability or syndication metadata starts weighting agreement
