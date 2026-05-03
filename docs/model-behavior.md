# Model Behavior

This document describes how the project uses LLMs, what each model call is allowed to decide, and where the current failure boundaries are.

The guiding rule is: LLMs produce structured intermediate artifacts where possible, and prose only at the final briefing layer.

---

## Current model usage

| Task | Model | Output | Cache status | Purpose |
|---|---|---|---|---|
| Article classification | `gpt-5.4-mini` | JSON | Cached by `content_hash + model + prompt_version` | Assign theme, story label, and importance |
| Claim extraction | `gpt-5.4-mini` | JSON | Cached by `article_id + prompt_version + content_hash` | Extract atomic claims and evidence spans |
| Same-day consolidation | `gpt-5.5` | JSON | Not cached | Merge same-day labels that refer to the same event |
| Cross-day matching | `gpt-5.5` | JSON | Not cached | Match today's labels to recent canonical stories |
| Briefing generation | `gpt-5.5` | JSON object containing prose fields | Not cached | Produce story briefing text and `delta_summary` |

High-volume calls use `gpt-5.4-mini`. Cross-story reasoning and final prose use `gpt-5.5`.

---

## Structured output contract

All LLM calls should return JSON objects and pass through `parse_json_object()` in `src/llm.py`.

Expected behavior:

- classification returns a `results` list
- claim extraction returns a `claims` list
- same-day consolidation returns a `groups` list
- cross-day matching returns a `matches` list
- briefing generation returns a `briefings` list

Free-form model text should not become internal state unless it is the final briefing prose or a stored story memory summary.

---

## Separation of responsibilities

### Classification

Classification should only decide:

- theme
- story label
- importance

It should not generate briefing prose or claims.

### Claim extraction

Claim extraction should only extract article-supported statements:

- `claim_text`
- `claim_type`
- `entities`
- `evidence_span`
- `confidence`

It should not decide source agreement, contradiction, or final confidence. Those are downstream interpretation steps.

The claim layer validates each returned claim before storage. A claim must have a valid type, string entities, numeric confidence in `[0.0, 1.0]`, and a non-empty evidence span that appears in the article input sent to the extractor.

### Story tracking

Tracking decides whether labels refer to the same ongoing story. It should preserve temporal continuity and avoid merging stories merely because they share broad topics.

### Briefing generation

Briefing generation is the final prose layer. It may synthesize across sources, but should use today's articles as the authority for current developments and previous context only for continuity.

---

## Claim extraction cost policy

Claim extraction should remain cost-conscious until observability exists.

Default behavior:

- extract broad claims from RSS title/description
- use `gpt-5.4-mini`
- cache aggressively

Current cache behavior:

- cache by claim input content hash and prompt version
- cache zero-claim results
- update cached claim `story_id` when tracking changes
- ignore older prompt-version claims when rendering current evidence
- render evidence with source and article context

Deferred behavior:

- full-text claim extraction for every article

Full-text-for-all should be reconsidered only after `runs`, `llm_calls`, and `--pipeline-report` can measure the token, cost, and latency impact.

---

## Known model failure modes

The most important current risks are:

- story consolidation over-merges distinct events with similar keywords
- cross-day matching attaches fresh reporting to an old canonical label
- briefing prose overstates certainty compared with source claims
- claim extraction treats allegations as confirmed facts
- RSS-only claims miss qualifications present in full article text
- numeric claims conflict across sources but are not yet compared

See [failure-modes.md](failure-modes.md) for the broader list.

---

## Model change rules

When changing a model, prompt, or output schema:

- bump the prompt version where cached outputs depend on it
- update or add tests with mocked LLM responses
- document expected behavior changes
- avoid changing multiple LLM stages in one unclear edit
- add evaluation coverage if the change affects story clustering, claim extraction, source grounding, or temporal diffing

Model changes are architecture changes when they alter what the system treats as memory or evidence.
