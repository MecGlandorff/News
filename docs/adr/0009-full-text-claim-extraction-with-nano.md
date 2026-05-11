# ADR 0009: Full-text claim extraction with nano

**Date:** 2026-05-09  
**Status:** Accepted

---

## Context

Claim extraction turns article input into structured claims with evidence spans. Before this decision, the extractor used `gpt-5.4-mini` and read only RSS title plus description. That kept claim extraction cheap, but it also meant evidence quality was limited by feed summaries.

The project now has run and LLM observability for token use, latency, cache hits, schema failures, scraper counts, claim totals, and estimated cost. That makes it reasonable to try a richer claim input path while still measuring the impact.

The working hypothesis is:

```text
gpt-5.4-nano + full article text can produce better grounded claims than
gpt-5.4-mini + RSS title/description.
```

This decision is only about claim extraction. Classification and story tracking remain separate because bad labels can corrupt story memory.

---

## Decision

For evidence runs:

- `--show-evidence` requests full article text during scraping.
- Claim extraction uses title, RSS description, and full article text when body text is available.
- If body extraction fails or returns empty text, claim extraction falls back to title plus RSS description.
- The claim model changes from `gpt-5.4-mini` to `gpt-5.4-nano`.
- The claim prompt version is bumped so old RSS/mini cached results are not reused as current evidence.
- Article classification remains on `gpt-5.4-mini` with RSS title/description.

This keeps the more expensive path gated behind an explicit evidence flag. Ordinary runs without `--show-evidence` do not run claim extraction.

---

## Rationale

**Evidence quality depends on source context.** Claims are only useful when the supporting span appears in the source input. Full article text gives the extractor more qualified statements, attributed claims, numbers, and context than an RSS summary.

**Nano is an acceptable experiment for extraction.** Claim extraction is a structured extraction task with strict validation. Invalid claims are dropped, zero-claim results are cached, and output must include evidence spans found in the input.

**Classification should stay stable.** Classification creates story labels and importance scores. Switching it to full text and `nano` at the same time would mix a cost experiment with a story-memory risk.

**Cost remains gated and observable.** Full-text claims run only when `--show-evidence` is enabled, and `llm_calls` records token and latency data for the resulting model calls.

---

## Consequences

Positive:

- Evidence runs can extract claims from richer source material.
- Claim spans can include qualifications that RSS descriptions omit.
- Smaller model choice may offset some full-text token cost.
- Cache invalidation is explicit through the prompt-version bump.

Negative:

- `--show-evidence` now performs more network work because it fetches article bodies.
- Full-text inputs can increase token use and latency.
- Some sources may block body extraction, so evidence depth will vary by source.
- Cost estimates depend on manually maintained pricing and a static USD-to-EUR rate.

---

## Alternatives rejected

**Switch classification and claims to nano with full text.** Rejected for now because classification affects story memory and should not be changed in the same step as claim input expansion.

**Keep mini with RSS input.** Rejected because it preserves a known grounding weakness: RSS summaries often omit qualifications and source-specific detail.

**Add another CLI flag for full-text claims.** Rejected for now because `--show-evidence` already means the user is asking for the evidence layer. A separate flag can be added later if evidence runs need finer cost controls.

---

## Review trigger

Revisit this decision when:

- measured evidence-run cost or latency exceeds the project's tolerance
- source agreement uses claim-level comparison
- source-divergence notes compare extracted claims
- evals show that `gpt-5.4-nano` materially reduces claim quality compared with `gpt-5.4-mini`
