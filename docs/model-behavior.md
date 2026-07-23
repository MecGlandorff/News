# Model Behavior

This document describes how the project uses LLMs, what each model call is allowed to decide, and where the current failure boundaries are.

For the full runtime flow around these calls, read [how-it-works.md](how-it-works.md).

The guiding rule is: LLMs produce structured intermediate artifacts where possible, and prose only at the final briefing layer.

---

## Current model usage

| Task | Model | Output | Cache status | Purpose |
|---|---|---|---|---|
| Article classification | `gpt-5.4-mini` | JSON | Cached by `content_hash + model + prompt_version` | Assign theme, story label, and importance |
| Claim extraction | `gpt-5.4-nano` | JSON | Cached by occurrence + content + model + prompt/validation versions | Extract atomic claims and evidence spans from full text when available |
| Claim derivability verification | `gpt-5.4-nano` | JSON | Exact response cache by request shape | Decide uncertain claim/span paraphrases; default reject |
| Same-day evidence grouping | `gpt-5.4-mini-2026-03-17` with `low` reasoning | Strict JSON decisions | Exact response cache by request shape | Judge retrieved article pairs; a complete-link gate prevents bridge merges |
| Cross-day same-story matching | `gpt-5.4-mini-2026-03-17` with `low` reasoning | Strict JSON decisions | Exact response cache by request shape | Decide whether current evidence continues one concrete stored story |
| Named-arc assignment | `gpt-5.4-mini-2026-03-17` with `low` reasoning | Strict JSON decisions | Exact response cache by request shape | Attach a distinct story only to a supported named event container |
| Briefing generation | `gpt-5.5` | JSON story-card fields plus prose | Exact response cache by request shape | Produce status, confidence, source agreement, dispute flag, `delta_summary`, briefing text, and open questions |

Classification and evidence-gated matching use the pinned mini snapshot. Claim
extraction uses `gpt-5.4-nano` behind `--show-evidence`, with full article text
when available. Final briefing prose uses `gpt-5.5`.

The exact response cache key includes purpose, model, prompt version, messages, response format, and API kwargs. Cache hits skip the model call and increment the total plus a layer-specific run counter; they do not create `llm_calls` rows. Entries are eligible for reuse for 30 days, and successful runs cap the table at 1,000 rows.

---

## Structured output contract

All LLM calls should return JSON objects and pass through `parse_json_object()` in `src/llm.py`.

Expected behavior:

- classification returns a `results` list
- claim extraction returns a `claims` list
- claim derivability verification returns a `supported` boolean
- same-day, cross-day, and arc matching return a strict `decisions` object keyed
  by every supplied short response key; opaque case IDs are restored locally
- briefing generation returns a `briefings` list with bounded story-card fields

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

It should not decide source agreement, source divergence, or final confidence. Those are downstream interpretation steps.

The claim layer validates each returned claim before storage. A claim must have a valid type, string entities, numeric confidence in `[0.0, 1.0]`, and a non-empty evidence span that appears in the article input sent to the extractor.

### Story tracking

Tracking decides whether article evidence refers to the same concrete story, or
whether a distinct story belongs under the same named event arc. Classifier labels are
retrieval signals, not identity proof.

The default cascade is:

1. Build compact profiles from classifier labels, RSS titles and descriptions, and
   recent stored story memory.
2. Retrieve a capped candidate set with deterministic lexical, semantic, phrase,
   number, date, and exact-URL signals.
3. Ask pinned mini for strict structured same-story or same-arc judgments.
4. Require one schema-constrained decision for every short response key and bind
   those keys back to opaque internal case IDs locally.
5. Verify model-supplied anchors against evidence on both sides. Two locally grounded
   headline signals can fill an omitted anchor, but cannot override a model rejection.
6. Reject conflicts, recurring formats, broad topics, invalid parent context,
   multiple accepted candidates, malformed output, and uncertainty.

Same story accepts only `same_event` or `direct_continuation` at medium/high
confidence with grounded evidence. Sharing a tournament or other named container is
not enough; different matches, stages, incidents, and results belong in separate
stories and may then attach to one named arc. Arc acceptance requires `same_arc` or
valid `parent_context`, a `named_event` container, grounded anchors, and no material
conflict.

Exact normalized URL duplicates are the narrow deterministic acceptance. Recurring
content formats can be rejected deterministically. All other unresolved cases become
new memory. Decisions are stored in `same_day_match_decisions`,
`story_match_decisions`, and `story_arc_decisions`, including route, retrieval
signals, conflicts, and ambiguity reason.

Matching does not fetch article bodies. A headline-only occurrence may therefore
remain split when source identity cannot be proved. `--no-verify-story-matches`
exists only for comparison with the legacy label-first path.

### Briefing generation

Briefing generation is the final prose layer. It may synthesize across sources, but should use today's articles as the authority for current developments and previous context only for continuity.

It returns story-card metadata as bounded labels:

- `status`: `new`, `developing`, `escalating`, `cooling`, `disputed`, or `unresolved`
- `confidence`: `high`, `medium`, or `low`
- `source_agreement`: `broad`, `partial`, `mixed`, `single-source`, or `disputed`
- `dispute_flag`: `none` or `possible conflict`
- `open_questions`: short watch items grounded in the supplied articles and claims

Without evidence mode, these labels are briefing-level signals backed by source identity defaults and prompt constraints. `confirmed conflict` is intentionally not an allowed briefing value; even claim-backed divergence is surfaced as `possible conflict`.

When `--show-evidence` supplies saved claims, the briefing input includes a deterministic `claim_source_agreement` summary:

- background claims are ignored
- exact repeated non-background claims across distinct source identities count as claim-backed support
- conservatively similar claims can count as multi-source support, but never as proof of independent corroboration
- four or more distinct source identities repeating the same claim can produce `broad`; two or three can produce `partial`
- multiple claim-bearing source identities without exact repeats remain `partial`, not `broad`
- precise number, date, explicit status-opposite, or attribution differences produce lightweight source-divergence notes and force `mixed` plus `possible conflict`
- only current-day claims affect current agreement; claims from the prior six editorial days are dated continuity context

The summary uses `source_id` where available and falls back to normalized source names for older rows. It does not adjudicate truth, infer independence, or create confirmed contradiction prose.

---

## Claim extraction cost policy

Claim extraction stays gated behind `--show-evidence`. Observability now exists, so the broader full-text path should be reviewed with measured token, cost, and latency impact rather than assumed to be cheap.

Default behavior:

- when `--show-evidence` is enabled, fetch full article text during scraping
- build claim input from title, RSS description, and full article text when available
- fall back to title and RSS description when full text is empty or unavailable
- use `gpt-5.4-nano`
- use claim prompt version `2026-05-13-v1`, which tightens atomicity,
  attribution, and low-value background rules after the first reviewed
  claim-quality eval
- cache aggressively

Current cache behavior:

- cache by occurrence identity, content hash, model, prompt version, and validation-policy version
- cache zero-claim results
- update cached claim `story_id` when tracking changes
- ignore older prompt-version claims when rendering current evidence
- render evidence with source and article context

`runs`, `llm_calls`, and `--pipeline-report` now measure token use, latency, claim metrics, and estimated cost from explicit model pricing. The claim-quality eval compares RSS-only input against full-text input with the same claim model:

```bash
python -m evals.run_claim_quality_eval
```

Use that report to decide whether the full-text quality lift is worth the extra cost before broadening claim extraction or loosening the shipped conservative agreement/divergence patterns.

---

## Known model failure modes

The most important current risks are:

- the legacy label-first path can over-merge distinct events when evidence-gated matching is disabled
- the precision-first matcher can over-split headline-only or otherwise thin RSS
  evidence, or when several plausible candidates clear the gate
- briefing prose overstates certainty compared with source claims
- claim extraction can still treat allegations as confirmed facts; the
  `2026-05-13-v1` prompt reduces this risk but needs a live current-prompt eval
- full-text extraction can increase latency and token use when `--show-evidence` is enabled
- source-divergence comparison is deliberately narrow and may miss semantically equivalent wording outside its precise deterministic patterns
- exact response caching only reuses identical prompts; it is not a semantic story-match cache

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
