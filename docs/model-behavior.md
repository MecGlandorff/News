# Model Behavior

This document describes how the project uses LLMs, what each model call is allowed to decide, and where the current failure boundaries are.

For the full runtime flow around these calls, read [how-it-works.md](how-it-works.md).

The guiding rule is: LLMs produce structured intermediate artifacts where possible, and prose only at the final briefing layer.

---

## Current model usage

| Task | Model | Output | Cache status | Purpose |
|---|---|---|---|---|
| Article classification | `gpt-5.4-mini` | JSON | Cached by `content_hash + model + prompt_version` | Assign theme, story label, and importance |
| Claim extraction | `gpt-5.4-nano` | JSON | Cached by `article_id + prompt_version + content_hash` | Extract atomic claims and evidence spans from full text when available |
| Same-day consolidation | `gpt-5.5` | JSON | Not cached | Merge same-day labels that refer to the same event |
| Cross-day matching | `gpt-5.5` | JSON | Not cached | Match today's labels to recent canonical stories |
| Story-match verification | `gpt-5.4-nano` | JSON | Not cached | Verify candidate cross-day matches with full article text before reusing story memory |
| Briefing generation | `gpt-5.5` | JSON story-card fields plus prose | Not cached | Produce status, confidence, source agreement, dispute flag, `delta_summary`, briefing text, and open questions |

Classification uses `gpt-5.4-mini`. Claim extraction uses `gpt-5.4-nano` behind `--show-evidence`, with full article text when available. Cross-story reasoning and final prose use `gpt-5.5`.

---

## Structured output contract

All LLM calls should return JSON objects and pass through `parse_json_object()` in `src/llm.py`.

Expected behavior:

- classification returns a `results` list
- claim extraction returns a `claims` list
- same-day consolidation returns a `groups` list
- cross-day matching returns a `matches` list
- story-match verification returns a `decisions` list
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

Tracking decides whether labels refer to the same ongoing story. It should preserve temporal continuity and avoid merging stories merely because they share broad topics.

When `--verify-story-matches` is enabled, candidate cross-day matches are checked by a separate verifier before the tracker reuses a story ID. The verifier receives today's title, RSS description, normalized article date, full article text when available, and compact recent story memory. It returns structured fields including:

- `same_event`
- `relationship`
- `confidence`
- `article_dates`
- `candidate_last_seen`
- `continuity_evidence`
- `reject_reason`

Only `same_event`, `same_story_arc`, and `direct_follow_up` relationships can be accepted, and only when confidence is at least medium and continuity evidence is present. `adjacent_topic`, `broader_context`, `unrelated`, `uncertain`, malformed, or missing verifier decisions default to a new story. Decisions are stored in `story_match_decisions` for review.

The verifier is deliberately separate from claim extraction. It asks whether an article group continues an existing story; it does not extract factual claims for evidence rendering.

### Briefing generation

Briefing generation is the final prose layer. It may synthesize across sources, but should use today's articles as the authority for current developments and previous context only for continuity.

It returns story-card metadata as bounded labels:

- `status`: `new`, `developing`, `escalating`, `cooling`, `disputed`, or `unresolved`
- `confidence`: `high`, `medium`, or `low`
- `source_agreement`: `broad`, `partial`, `mixed`, `single-source`, or `disputed`
- `dispute_flag`: `none` or `possible conflict`
- `open_questions`: short watch items grounded in the supplied articles and claims

These labels are briefing-level signals. They make uncertainty visible in the artifact, but they are not yet a replacement for the planned claim-backed source-agreement and source-divergence layer. `confirmed conflict` is intentionally not an allowed briefing value until there is structured claim backing for it.

When `--show-evidence` supplies saved claims, the briefing input includes a deterministic `claim_source_agreement` summary. This first pass is intentionally conservative:

- background claims are ignored
- exact repeated non-background claims across distinct source identities count as claim-backed support
- four or more distinct source identities repeating the same claim can produce `broad`; two or three can produce `partial`
- multiple claim-bearing source identities without exact repeats remain `partial`, not `broad`
- numeric claims with similar context but different numbers produce lightweight source-divergence notes and force `mixed` plus `possible conflict`

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

- cache by claim input content hash and prompt version
- cache zero-claim results
- update cached claim `story_id` when tracking changes
- ignore older prompt-version claims when rendering current evidence
- render evidence with source and article context

`runs`, `llm_calls`, and `--pipeline-report` now measure token use, latency, claim metrics, and estimated cost from explicit model pricing. The claim-quality eval compares RSS-only input against full-text input with the same claim model:

```bash
python -m evals.run_claim_quality_eval
```

Use that report to decide whether the full-text quality lift is worth the extra cost before broadening claim extraction or using it for source agreement and source-divergence notes.

---

## Known model failure modes

The most important current risks are:

- story consolidation over-merges distinct events with similar keywords
- cross-day matching attaches fresh reporting to an old canonical label when the verifier is disabled or when the verifier lacks enough context
- briefing prose overstates certainty compared with source claims
- claim extraction can still treat allegations as confirmed facts; the
  `2026-05-13-v1` prompt reduces this risk but needs a live current-prompt eval
- full-text extraction can increase latency and token use when `--show-evidence` is enabled
- numeric/status/attribution claims can diverge across sources but are not yet compared
- stored story-match verifier decisions are not reused as a cache yet

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
