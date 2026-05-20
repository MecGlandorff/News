# ADR 0006: Run and LLM observability

**Date:** 2026-05-07
**Status:** Accepted

---

## Context

Phase 3 requires the pipeline to be inspectable before it becomes more expensive or autonomous.

Before this change, the system could produce story memory, claims, Markdown briefings, and PDFs, but it could not explain a run's model usage, token load, latency, schema failures, or cache behavior. That made it hard to evaluate cost-sensitive choices such as full-text claim extraction, source-agreement logic, or source-divergence notes.

---

## Decision

Add durable run observability with two tables:

- `runs`: one row per pipeline execution, with run status, returned-article and saved-claim totals, cache-hit count, token totals, latency, and error state.
- `llm_calls`: one row per real model call, with purpose, model, optional prompt version, latency, token usage, schema-failure state, retry count, and error state.

Add `--pipeline-report` as an operator-facing CLI report over the latest run row.

Cache hits are counted on `runs`; they are not inserted into `llm_calls`, because no model call occurred.

Track prompt and completion tokens now. EUR cost estimates require explicit pricing and should only be added once that table is represented and maintained deliberately.

2026-05-09 follow-up: ADR 0010 adds scraper counters, claim counters, and estimated EUR cost to `--pipeline-report` using explicit model pricing in code.

2026-05-17 follow-up: `--pipeline-report` also includes a novelty audit section. It surfaces high-signal stories not selected for briefing, high-signal new parent arcs, new parent arcs with related rejected candidates, and rejected medium/high related story-match decisions.

---

## Rationale

**Observability comes before expensive behavior.** Full-text claim extraction and source-divergence work can increase token use and latency. The system should measure that impact before expanding those paths.

**`llm_calls` should mean real calls.** Treating cache hits as call rows would inflate call counts and make latency and token reports harder to interpret.

**Token totals are stable enough for v1.** Token usage is returned by model responses and can be recorded without maintaining a separate pricing table.

**The report is operational, not editorial.** `--pipeline-report` explains what the pipeline did. It does not change story selection, briefing claims, confidence, source agreement, or parent/child assignment.

---

## Consequences

**Positive:**
- Each run has an inspectable status and summary
- Real LLM calls can be audited by purpose and model
- LLM errors and schema failures become visible instead of only surfacing as exceptions or logs
- Future cost and latency tradeoffs have a measurement base

**Negative:**
- Cost estimates depend on a manually maintained model-pricing table and static USD-to-EUR rate
- Cached-input token pricing is not represented because the current LLM call telemetry records prompt and completion tokens, not provider-side cached-token split
- Cache-hit counts are aggregate run totals, not yet broken out by stage

---

## Review trigger

Revisit this decision when:
- model pricing changes or the project needs provider-side cached-input pricing
- full-text evidence runs need per-stage budget reporting
- retry behavior is implemented beyond recording retry counts
