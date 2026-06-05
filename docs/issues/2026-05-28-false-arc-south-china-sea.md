# False arc attachment: South China Sea friction assigned to China-Russia visit

Status: open
Date observed: 2026-05-28
Observed artifact: `briefings/briefing_20260527_2309.md`

## Problem

The briefing item `South China Sea friction` was rendered with:

```text
Arc: China-Russia visit
```

That arc is not supported by the item. The story is about China saying it drove
away Dutch frigate Zr. Ms. De Ruyter near the Paracel Islands, while Dutch
defence officials deny entering Chinese waters and say the ship continued its
planned route.

This should be treated as a false story/arc attachment, not a prose issue. It
undermines source-grounded event memory because a reader sees the current event
as part of an unrelated diplomatic visit arc.

## Expected Behavior

The item should either:

- create a new arc such as `South China Sea sovereignty friction`, or
- attach to an existing South China Sea / China maritime claims arc if one is
  supplied and supported by concrete evidence.

It should not attach to `China-Russia visit` based only on broad China,
geopolitics, or state-power context.

## Suspected Area

- `src/story_matching.py`
- `ARC_ASSIGNMENT_PROMPT`
- `ARC_ACCEPT_RELATIONSHIPS`
- `arc_assignment_from_model()`
- `assign_story_arcs()`
- `src/top10.py` rendering of `arc_label`

The current arc-assignment path accepts `adjacent_topic` and `broader_context`
as attachable arc relationships. Existing docs already note questionable loose
attachments in `docs/session-log.md` and ADR 0016.

## Investigation Notes

Check the 2026-05-27 persisted rows for:

- the `South China Sea friction` story row
- its `arc_id`, `parent_story_id`, `parent_relationship`, and
  `parent_confidence`
- the candidate arcs supplied to the `match-arc` call
- the model's `continuity_evidence`
- whether `China-Russia visit` entered the candidate set only through generic
  shared tokens like `China`

## Acceptance Criteria

- Add a regression test where a Dutch frigate / Paracel Islands / South China
  Sea story cannot attach to a `China-Russia visit` arc.
- Arc assignment rejects actor-only, country-only, and broad geopolitics-only
  matches unless there is concrete continuity with the supplied arc.
- The accepted relationship set or validation gate is narrowed after review;
  changing this affects trust and should follow the repo decision protocol.
- If local data is repaired, do it with an idempotent SQLite-compatible helper
  or clearly document that this is a generated-artifact-only correction.

## Open Decision

Decision needed before implementation: should `adjacent_topic` and
`broader_context` be demoted to audit-only for arc assignment, or should they
remain attachable with stricter evidence/token gates?
