# ADR 0012: Exact LLM response cache for matching and briefing

**Date:** 2026-05-11

**2026-07-11 follow-up:** Exact responses are eligible for reuse for 30 days, and successful runs prune the table to 1,000 entries. Run metrics now attribute cache hits to classification, claims, verifier, matching, briefing, or other layers.

## Status

Accepted.

## Context

Recent pipeline reports show that recurring cost is concentrated in story matching and briefing calls, especially `match-crossday` and `brief` on `gpt-5.5`. Classification and claim extraction already have durable article-level caches, but reruns can still repeat high-token story-memory and briefing prompts.

OpenAI prompt caching can reduce repeated input-token cost, but it does not skip a model call. This project also needs inspectable local behavior: if the same validated prompt input is replayed, the system should be able to reuse the exact prior structured response.

## Decision

Add a durable SQLite `llm_response_cache` table for exact response reuse on:

- same-day story consolidation
- cross-day story matching
- story-match verification
- story-arc assignment
- claim-derivability verification
- briefing generation

The cache key includes purpose, model, prompt version, messages, response format, and API kwargs. A response is saved only after the caller parses the JSON object and validates the expected top-level list. Cache hits increment `runs.llm_cache_hits` and do not insert fake `llm_calls` rows.

## Consequences

Reruns and retries with identical inputs can skip expensive model calls entirely. Changed article inputs, story memory, prompts, models, prompt versions, or response formats produce a different cache key and force a fresh call.

This cache does not make stale or approximate matches. It is exact-result reuse only, so it improves cost without changing story-memory semantics.

The cache operates during observed pipeline runs. Expired entries are ignored on read and pruning runs after successful pipelines. Domain caches for classifications and claims remain separate.
