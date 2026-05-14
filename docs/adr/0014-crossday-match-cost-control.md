# ADR 0014: Cross-day story matching cost control

**Date:** 2026-05-15

## Status

Accepted.

## Context

Pipeline reports showed that run cost was concentrated in `match-crossday`, not in the new nano claim verifier. One observed run spent about EUR 2.20 total, with `match-crossday` alone accounting for about EUR 1.42:

- `match-crossday`: 1 `gpt-5.5` call, 273,069 prompt tokens, 10,044 completion tokens, about EUR 1.42
- `match-verify`: 21 `gpt-5.4-nano` calls, 237,743 prompt tokens, 22,154 completion tokens, about EUR 0.06
- claim verifier calls: 0

The expensive step is the broad cross-day label matcher. It compares today's consolidated story labels against recent story memory and decides whether each label continues a tracked story or should become `NEW`. This is central to source-grounded event memory, so cost cuts must avoid increasing false merges.

## Decision

Route the first-pass cross-day matcher to `gpt-5.4-mini` with a dedicated `CROSSDAY_MATCH_MODEL` config value.

Keep the existing trust shape:

- same-day label consolidation still uses `TRACKER_MODEL`
- cross-day matching still uses the same prompt, candidates, output schema, and validation
- story-match verification still uses `gpt-5.4-nano` with richer article context
- weak or adjacent proposed matches are still rejected by the verifier

Also batch cross-day match cases with `MATCH_CASES_PER_CALL = 50`. Each batch uses the same `match-crossday` purpose and prompt version, so exact response caching works per batch instead of being all-or-nothing for the entire run.

Do not reduce `CANDIDATES_PER_LABEL` yet. Reducing candidates could save more tokens, but it changes recall behavior: a true continuing story ranked outside the smaller candidate window would become `NEW` and create duplicate story memory.

## Consequences

For the observed run, routing `match-crossday` from `gpt-5.5` to `gpt-5.4-mini` would estimate roughly:

```text
match-crossday: EUR 1.42 -> EUR 0.21
total run:      EUR 2.20 -> EUR 0.99
```

The first run after the model change will miss old exact cache rows for `match-crossday`, because the model is part of the cache key. Future identical mini batches can cache normally.

Batching may increase the raw `LLM calls` count while reducing cache invalidation blast radius. A fresh uncached run still sends roughly the same total candidate content, but reruns can reuse unchanged batches when only part of the day's input changes.

The quality risk is bounded by keeping candidate generation unchanged and retaining the nano verifier after the first-pass matcher. The main expected failure mode is duplicate stories from missed continuing matches, not false merges, because the verifier rejects weak proposed continuations.

## What this does not do

- It does not shrink candidate memory, summaries, deltas, or recent titles.
- It does not lower `CANDIDATES_PER_LABEL`.
- It does not make deterministic accept/reject rules for obvious cross-day cases.
- It does not change briefing claims or source-grounding behavior.

Those are possible future cost passes, but they affect story continuity behavior more directly and should be reviewed against real match decisions first.
