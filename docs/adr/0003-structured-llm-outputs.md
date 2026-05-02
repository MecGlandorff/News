# ADR 0003: Structured JSON outputs for all LLM calls

**Date:** 2026-05-02  
**Status:** Accepted

---

## Context

The pipeline makes several LLM calls at different stages:

- Article classification (theme, story_label, importance)
- Claim extraction (claim_text, claim_type, evidence_span, confidence)
- Same-day story consolidation (group labels by event)
- Cross-day story matching (match today's labels to yesterday's)
- Briefing generation (briefing text + delta_summary)

Each call could return:
- Free-form prose
- Structured JSON (validated against an expected schema)
- A mix of both (prose with embedded JSON)

---

## Decision

All LLM calls return JSON objects validated by `parse_json_object()` in `src/llm.py`.

The `response_format={"type": "json_object"}` parameter is set on every call to enforce JSON output at the API level. Results are validated as Python dicts before use.

---

## Rationale

**Downstream processing requires structure.** Classification results are inserted into SQLite; story labels are passed between pipeline stages; briefing payloads are merged and keyed by canonical_label. Free-form prose cannot be reliably parsed to support these operations.

**Validation is cheap, failure is expensive.** A malformed classification silently corrupts a story record. A malformed claim has no evidence span. Structured output with validation makes failures loud and debuggable rather than silent.

**Caching depends on stable schemas.** The classification and claim caches are keyed by `article_id + content_hash + model + prompt_version`. The cached output must be parseable on retrieval. Free-form prose would be fragile here.

**Separation of concerns.** By separating structured data extraction (classification, claims, story matching) from prose generation (briefing text), we can:
- Cache and reuse the structured layer independently
- Validate each layer independently
- Evaluate each layer independently
- Replace the prose layer without touching the data layer

**Prose is the final layer.** The briefing text itself is free-form prose, but it is the terminal output — it is not parsed or used as input to anything else. It is the one place where unstructured generation is appropriate.

---

## Consequences

**Positive:**
- Failures are explicit (`ValueError` with context, not silent bad data)
- Each structured output is independently testable with fixed inputs
- Caching is reliable because the schema is stable
- Outputs can be stored, versioned, and compared across model upgrades
- Future evals can compare structured outputs against golden sets

**Negative:**
- More complex prompts (must instruct the model to return JSON)
- Occasional schema validation failures (model ignores format instruction)
- Retry logic needed for schema failures (not yet implemented)

---

## Implementation pattern

```python
response = client.chat.completions.create(
    model=MODEL,
    messages=[
        {"role": "system", "content": PROMPT},
        {"role": "user",   "content": json.dumps(input_data)},
    ],
    response_format={"type": "json_object"},
)
payload = parse_json_object(response)  # raises ValueError if not a dict
results = payload.get("key")
if not isinstance(results, list):
    raise ValueError('Model response must contain a "key" list')
```

---

## Alternatives rejected

**Free-form prose with regex extraction:** Brittle. Model output format varies by phrasing and context. Regex maintenance cost grows with prompt changes.

**Function calling / tool use:** More explicit schema enforcement but higher prompt complexity and harder to test with simple doubles. May be worth revisiting when schema stability becomes a bottleneck.

---

## Review trigger

Revisit this decision if:
- Schema validation failure rate exceeds ~5% on a given call type
- A call type genuinely cannot return useful structured output (e.g. long-form analysis)
- OpenAI structured outputs (strict JSON schema enforcement) becomes stable and worth adopting
