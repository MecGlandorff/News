# ADR 0022: Evidence-gated matching cascade

**Date:** 2026-07-23

## Status

Accepted.

## Context

The Phase 3 closure runs on 2026-07-21 and 2026-07-22 exposed two different
memory failures:

- articles with the same classifier label could be grouped before the matcher
  saw their source evidence, so unrelated articles became one story;
- arc candidates were retrieved from the current label rather than the current
  articles, while the final gate trusted model confidence and non-empty
  evidence without verifying that evidence.

The reviewed July 22 arc assignments contained three clearly useful
attachments, two coarse attachments, and four materially unsafe attachments.
Several source-grounded continuations were not supplied as candidates at all.
This is an information-flow and acceptance-gate problem, not evidence that a
more expensive model is required.

False merges are more damaging than false splits because they persist an
incorrect event memory. The pipeline must therefore fail closed when concrete
identity is unresolved.

## Decision

Replace label-first grouping and the independent cross-day proposal/verifier
stages with one evidence-gated matching cascade:

```text
article evidence
    -> deterministic candidate retrieval
    -> GPT-5.4 mini semantic judgment
    -> deterministic evidence gate
    -> accept, reject, or ambiguous
```

- Pin classification and matching to `gpt-5.4-mini-2026-03-17` during the
  Phase 3 closure series.
- Use RSS titles and descriptions, classifier labels, and recent stored memory
  for matching profiles. Do not fetch article bodies during matching.
- Use strict JSON Schema outputs for matching calls. Batch cases receive short,
  stable response keys that are required as object properties; opaque internal
  case IDs are rebound locally rather than copied by the model.
- Use deterministic signals only to retrieve candidates, accept exact content
  duplicates, or reject concrete conflicts. Ordinary semantic matches require
  the model and the evidence gate to agree.
- Verify shared anchors against evidence present on both sides. Confidence
  alone never authorizes a match.
- Treat classifier labels as retrieval signals, not grouping keys.
- Persist plausible same-day candidate edges and extend story/arc decision
  rows with their route, signals, conflicts, and ambiguity reason.
- Route unresolved cases to new story or new arc memory. Do not call a stronger
  model in this change.

Same-story and same-arc decisions remain separate:

- same story means the same concrete incident, proceeding, decision,
  investigation, contest, operation, or its direct continuation;
- same arc means a distinct story under a specific named ongoing container,
  such as a war, election, tournament, investigation, disaster, or policy
  programme;
- generic topics, recurring content formats, broad country/actor overlap, and
  adjacent context are not persisted as arcs.

When a second concrete story belongs under a narrowly named one-story arc, the
model may propose a short umbrella label. Promotion is accepted only when the
shared named anchor is grounded in both stories. The previous, proposed, and
final labels are recorded.

## Model And Cost Gate

The saved-run reconstruction evaluates reasoning efforts `none` and `low` on
the same reviewed inputs.

1. Reject a setting that creates any reviewed mixed same-day group, false
   same-story merge, or false arc.
2. Prefer the passing setting that recovers more clear positive cases.
3. Select `low` only when it improves recall and adds no more than EUR 0.05 to
   the representative run.
4. Select `none` on a tie.

If neither setting passes, refine the mini prompt, retrieval, or deterministic
gate. A stronger-model escalation requires a later measured decision.

## Reconstruction Outcome

The final isolated reconstruction replayed 158 stored article occurrences from
2026-07-21 and 2026-07-22 through separate database copies. It reviewed 16
cases: 15 were scorable and one remained explicitly insufficient because the
saved occurrence had a headline but no description or body.

`none` produced one reviewed corrupting accept and recovered three of five
scorable positives at an estimated EUR 0.1793. `low` produced zero corrupting
accepts and recovered four of five at EUR 0.1920, an increase of about EUR
0.0127. Both efforts completed with zero LLM errors, schema failures, or
retries. The approved precision-first gate therefore selected `low`.

The insufficient-evidence case remains fail-closed and is excluded from quality
scoring rather than being forced into a merge. One scorable India continuation
also remained split because two candidate stories cleared the gate and the
approved ambiguity policy refuses to guess. The reconstruction did not replace
`data/stories.db`. See the
[sanitized reconstruction report](../../evals/reports/phase3_matching_reconstruction_2026-07-23.md).

## Consequences

Positive:

- candidate recall can use the article evidence already available to the
  pipeline;
- accepted matches have reconstructable source-derived anchors;
- ambiguous cases are visible and cannot silently corrupt memory;
- the model and reasoning setting remain reproducible during closure;
- ordinary evidence-gated matching uses the measured `low` reasoning effort;
- the existing SQLite and exact-cache architecture remains in place.

Negative:

- conservative ambiguity handling can create duplicate or over-split stories;
- thin RSS metadata can remain an explicit input-quality gap;
- matching now has more explicit decision data and tests;
- a one-story arc may remain narrow until a grounded umbrella is available;
- the July closure series must restart after the behavior change.

## Non-Goals

- no embeddings or vector database;
- no stronger-model escalation;
- no automatic repair of historical databases;
- no change to claim extraction, source agreement, briefing claims, or Phase 4
  scope.
