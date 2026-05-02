# ADR 0002: Story memory via observation pattern, not vector search

**Date:** 2026-05-02  
**Status:** Accepted

---

## Context

The system needs to remember what happened in previous runs so that daily briefings can surface what is genuinely new rather than repeating yesterday's summary.

Two approaches were considered:

**Option A: Vector search over past articles**  
Embed all past articles into a vector store. At briefing time, retrieve semantically similar articles from the last N days and use them as context.

**Option B: Observation pattern with SQLite**  
After each run, write a structured observation record per story (summary + delta_summary) back to the database. On the next run, read the most recent observation as the "previous context" for that story.

---

## Decision

Use the observation pattern (Option B).

The `story_observations` table stores one record per story per day, including the LLM-generated summary and delta_summary written back after briefing generation. The `_get_previous_story_context()` function retrieves the most recent observation with non-empty summary content.

---

## Rationale

**Curated memory is better than raw retrieval.** Vector search returns the most semantically similar past articles — which may include tangential coverage, duplicates, and noise. The observation pattern returns the best human-readable summary the system already generated, which is more compact and useful as context.

**No additional infrastructure.** Vector search requires embedding calls (cost), a vector store (infrastructure), and a retrieval step. The observation pattern uses the SQLite database that already exists.

**Temporal continuity is explicit.** The delta_summary answers "what changed since the last observation" directly. This is the primary question the briefing needs to answer. Vector retrieval does not naturally produce this answer — it would need to be synthesized from raw documents.

**Coherence across runs.** Because the same model writes the observation and reads it the next day, the memory layer is self-consistent. The LLM is not asked to synthesize across a potentially large and noisy retrieval set.

**Incremental complexity.** The observation pattern can be built incrementally on top of existing story tracking. Vector search would require a new dependency and a new retrieval architecture.

---

## Consequences

**Positive:**
- Memory is compact and readable (one summary per story per day)
- Delta-aware by design
- No embedding cost or vector store needed
- Easy to inspect and debug in any SQLite browser

**Negative:**
- Memory is lossy — only the last generated summary is retained, not the full history of raw articles
- If the summary is wrong (model error), that error propagates into future context
- Cannot retrieve articles from several weeks ago without reading all daily observation records

---

## Alternatives rejected

**Vector search (Option A):** Useful for open-ended semantic retrieval. Not the right primitive for "what changed since yesterday" — that question is better answered by comparing structured observations than by ranking past articles.

**No memory (daily-only pipeline):** Simpler, but produces briefings with no temporal depth. The delta signal ("what changed today") is the primary value-add over a basic article summarizer.

---

## Review trigger

Revisit this decision if:
- The system needs to answer arbitrary questions about past coverage (not just "what changed")
- The observation summaries become too lossy to provide useful context
- A user-facing search interface is added that requires full-text or semantic retrieval across the article archive
