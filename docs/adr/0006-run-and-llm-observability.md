# ADR 0006: Run and LLM observability

**Date:** 2026-05-07
**Status:** Accepted

---

## Context

Phase 3 requires the pipeline to be inspectable before it becomes more expensive or autonomous.

Before this change, the system could produce story memory, claims, Markdown briefings, and PDFs, but it could not explain a run's model usage, token load, latency, schema failures, or cache behavior. That made it hard to evaluate cost-sensitive choices such as full-text claim extraction, source-agreement logic, or contradiction detection.

---

## Decision

Add durable run observability with two tables:

- `runs`: one row per pipeline execution, with run status, returned-article and saved-claim totals, cache-hit count, token totals, latency, and error state.
- `llm_calls`: one row per real model call, with purpose, model, optional prompt version, latency, token usage, schema-failure state, retry count, and error state.

Add `--pipeline-report` as an operator-facing CLI report over the latest run row.

Cache hits are counted on `runs`; they are not inserted into `llm_calls`, because no model call occurred.

Track prompt and completion tokens now. Defer EUR cost estimates until pricing is represented explicitly and maintained deliberately.

---

## Rationale

**Observability comes before expensive behavior.** Full-text claim extraction and contradiction work can increase token use and latency. The system should measure that impact before expanding those paths.

**`llm_calls` should mean real calls.** Treating cache hits as call rows would inflate call counts and make latency and token reports harder to interpret.

**Token totals are stable enough for v1.** Token usage is returned by model responses and can be recorded without maintaining a separate pricing table.

**The report is operational, not editorial.** `--pipeline-report` explains what the pipeline did. It does not change story selection, briefing claims, confidence, or source agreement.

---

## Consequences

**Positive:**
- Each run has an inspectable status and summary
- Real LLM calls can be audited by purpose and model
- LLM errors and schema failures become visible instead of only surfacing as exceptions or logs
- Future cost and latency tradeoffs have a measurement base

**Negative:**
- The first report does not yet show EUR cost estimates
- Scraper duplicate and fetch-failure counts need additional scraper instrumentation
- Cache-hit counts are aggregate run totals, not yet broken out by stage

---

## Review trigger

Revisit this decision when:
- model pricing is added for EUR cost estimates
- scraper observability exposes duplicate and fetch-failure counts
- full-text evidence runs need per-stage budget reporting
- retry behavior is implemented beyond recording retry counts
