# ADR 0016: Briefing theme penalties and explicit story arcs

**Date:** 2026-05-20

## Status

Accepted.

## Context

The May 18 and May 19 pipeline reports showed two related problems.

First, briefing selection could omit source-backed public-interest stories because `Tech`, `Science`, and `Sports` were excluded from normal section selection. That hid high-signal stories such as an OpenAI-Musk lawsuit and an Ebola outbreak unless they happened to qualify as top lead stories.

Second, the memory layer was still over-splitting continuing events. The lightweight `story_developments` model from ADR 0015 helped, but it still used broad story rows as article owners. That made it hard to preserve the distinction between:

- the same concrete event
- a new concrete child story inside an existing broader arc
- a genuinely new arc

The system needs source-grounded event memory, not broad topical merging. Same-story matching must stay conservative, but rejected related matches should not always become unrelated new parent arcs.

## Decision

Replace hard briefing theme exclusions with score penalties.

- `Tech` and `Science` receive a moderate selection penalty.
- `Sports` receives a much stronger selection penalty.
- Low-interest keywords receive an additional penalty.
- Penalized themes can still appear when source count and importance are strong enough.

Implement explicit story arcs now instead of further tuning the lightweight parent/development workaround.

- Add `story_arcs`.
- Add `stories.arc_id`.
- Add `stories.parent_story_id`.
- Backfill existing stories with one compatibility arc each.
- Leave historical article rows intact.
- For new runs, articles attach to the most specific concrete story row available.

Add a cached arc-assignment LLM stage.

- Same-story verification remains unchanged and conservative.
- Labels that are not accepted as the same story can be assigned to an existing arc.
- Arc assignment uses `gpt-5.4-mini`.
- The call returns structured JSON and is cached through the existing exact response cache.
- Accepted arc attachments require a supplied arc, medium/high confidence, and concrete evidence.
- Invalid, weak, or low-confidence arc output creates a new arc instead.

## Implementation Checks

Code review after implementation confirmed these safeguards:

- Briefing selection no longer has active theme exclusions: `SECTION_EXCLUDED_THEMES`, `LEAD_EXCLUDED_THEMES`, and `LOW_INTEREST_LEAD_THEMES` are empty compatibility aliases.
- Selection ranking uses `selection_score = base score - selection penalty`, so theme policy can lower rank without making a theme impossible to display.
- `Tech` and `Science` receive a `60` point penalty, `Sports` receives a `260` point penalty, and low-interest keyword matches receive an additional `120` point penalty.
- Section selection sorts by adjusted selection score and allows high-signal `Tech`, `Science`, and exceptional `Sports` stories into the rendered briefing.
- Novelty audit records both base score and adjusted selection score, with penalty reasons, so omitted high-signal stories remain explainable.
- The database migration creates `story_arcs`, adds `stories.arc_id` and `stories.parent_story_id`, then backfills legacy stories with one compatibility arc each.
- Same-story verification still runs before arc assignment and still controls whether an existing story row can be reused.
- Arc assignment only runs for labels that remain unmatched after same-story matching and verification.
- Arc assignment validates that the model selected a supplied `arc_id`; unsupplied arc IDs, schema mismatches, low confidence, missing evidence, or invalid parent IDs are rejected.
- Accepted arc assignments create a concrete child story row under the existing arc. They do not merge the child into the prior broad story row.
- New-run articles attach to the concrete story row, while `arc_label` and `parent_label` are exposed as context for briefing generation.
- Observability records `match-arc` LLM calls plus arc assignment, arc attachment, and new-arc counters.

Tests added or updated cover:

- legacy schema backfill into `story_arcs`
- high-signal penalized themes appearing in briefings
- rejected same-story matches becoming child developments under an existing arc
- `gpt-5.4-mini` arc assignment receiving supplied arc candidates
- run report output for arc assignment, arc attachment, and new-arc counters
- novelty audit output after theme penalties

## Real-Run Validation

Run #20 on 2026-05-20 validated the first implementation on a real pipeline run:

- Status: ok
- Runtime: 1049.9 seconds
- Articles returned: 476
- Stories touched: 265
- Developments saved: 268
- Arc assignments: 215
- Arc attachments: 111
- New arcs / new parent arcs: 107
- New parent ratio: 107/268, 39.9%
- Story match checks: 125
- Story match accepted: 49
- Story match rejected: 76
- High-signal not displayed: 0
- High-signal new parent arcs: 0
- Schema failures, retries, and LLM errors: 0
- Estimated cost: EUR 1.18

Cost by relevant LLM purpose:

- `match-arc`: 18 calls, 303,180 prompt tokens, 15,779 completion tokens, EUR 0.25
- `match-crossday`: 6 calls, 285,588 prompt tokens, 3,663 completion tokens, EUR 0.20
- `match-verify`: 16 calls, 129,996 prompt tokens, 17,141 completion tokens, EUR 0.04
- `brief`: 1 call, 42,136 prompt tokens, 8,084 completion tokens, EUR 0.39

Compared with the May 18 and May 19 audit runs, the main observed improvement was that high-signal omissions dropped to zero and the new-parent ratio fell from above 70% to 39.9%.

The novelty audit still surfaced review candidates:

- `Dutch Navy delays -> Dutch economy` (`broader_context`, high)
- `Bird decline -> Population decline` (`broader_context`, high)
- `Disabled child parking -> Parking reform` (`adjacent_topic`, medium)
- `Lebanon politics -> Lebanon ceasefire` (`adjacent_topic`, medium)
- `UK immigration reform -> UK leadership challenge` (`adjacent_topic`, medium)

Rejected related matches also remained visible for review:

- `Bird decline -> Population decline` (`broader_context`, high)
- `Dutch Navy delays -> Dutch economy` (`broader_context`, high)
- `Home battery cars -> Battery expansion` (`broader_context`, high)
- `MAFS breakup stories -> MAFS drama` (`broader_context`, high)
- `Transfer rumors -> Transfer rumors` (`adjacent_topic`, high)

These rows show that the novelty audit still works as a review queue. They are not treated as blockers for the first explicit-arc implementation, but they should be reviewed before further loosening arc assignment.

## Consequences

Positive:

- Important Tech, Science, and exceptional Sports stories are no longer hidden solely by theme policy.
- Article ownership moves toward concrete event memory.
- Arc and parent context can improve continuity without pretending adjacent developments are the same event.
- Compatibility backfill keeps existing databases readable without destructive migration.
- Arc-assignment cost is visible in LLM observability under `match-arc`.

Negative:

- The pipeline adds another AI decision point.
- `gpt-5.4-mini` costs more than a deterministic-only arc heuristic.
- One-arc-per-story backfill preserves compatibility but does not repair old over-splits.
- Arc assignment will need real-run review to tune false attachments and missed continuity.

## Non-Goals

- Do not loosen same-story verification.
- Do not merge historical stories automatically.
- Do not make arcs factual evidence; claims still ground through articles and sources.
- Do not add a graph database, vector database, dashboard, or manual review UI in this step.

## Follow-Up

- Review fresh novelty-audit rows after several real runs.
- Check whether high-signal omitted stories are rare and explainable.
- Check whether new arc ratios fall or become easier to explain.
- Review `match-arc` examples before changing arc-assignment prompt semantics or model choice.
