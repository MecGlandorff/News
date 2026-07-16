# ADR 0017: Arc-decision audit trail in `story_arc_decisions`

**Date:** 2026-06-09

## Status

Accepted.

## Context

`assign_story_arcs` in `src/tracker/matching/arcs.py` decides, for every unmatched story
label, whether to attach it to an existing story arc or let it become a new arc.
Nothing about that decision is persisted. Only the same-story verifier writes an
audit row (`story_match_decisions`, ADR 0008).

That gap has concrete costs:

- A false arc — the South China Sea attachment in
  `docs/issues/2026-05-28-false-arc-south-china-sea.md`, or the live "Film review"
  arc holding 9 unrelated children — leaves no trace of which candidate arcs were
  offered, what the model proposed, or why the gate accepted it.
- The June roadmap GATE (`docs/june_roadmap.md`) must choose between fixing and
  simplifying the arc layer using measured data. Its first signal — "false-arc
  rate after an obvious country/topic-only guard" — needs each candidate's
  `arc_candidate_score` *at decision time*. Scores are not reconstructable later
  because arc state (`last_seen`, recent-story text) moves underneath the scorer.
- ADR 0015 left this open as Q4: should `story_match_decisions` also record
  proposed `arc_id` and `parent_story_id`, or should arc decisions get their own
  audit table?

The `runs` table already counts `story_arc_assignments` and
`story_arc_attachments` (ADR 0006), so run-level totals exist. What is missing is
the per-decision trail.

## Decision

Arc-assignment decisions get their own table. This resolves ADR 0015 Q4.

Extending `story_match_decisions` was rejected on three grounds: its
`candidate_label` and `same_event` columns are `NOT NULL` and have no honest
value for an arc decision, and SQLite cannot relax `NOT NULL` without a table
rebuild — a destructive migration the database rules forbid; the novelty audit
queries `story_match_decisions` unfiltered, so mixed-in arc rows would corrupt
`_new_parent_arcs_with_candidates` and `_rejected_related_matches` unless every
consumer learned a `decision_type` filter; and the 1,471-row verifier history is
the dataset Phase 2 mines — it should stay homogeneous.

One row per decided case (a today-label with its candidate set), not one row per
candidate. That matches the decision shape: the model picks one arc from a set.
Per-candidate analysis stays available through SQLite `json_each` over the
`candidates` column.

### Schema

Added to the idempotent `executescript` in `src.tracker.store.get_db`, next to
`story_match_decisions`:

```sql
CREATE TABLE IF NOT EXISTS story_arc_decisions (
    decision_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id               INTEGER,
    run_date             TEXT NOT NULL,
    today_label          TEXT NOT NULL,
    candidates           TEXT NOT NULL,
    arc_id               INTEGER,
    parent_story_id      INTEGER,
    story_id             INTEGER,
    accepted             INTEGER NOT NULL,
    relationship         TEXT NOT NULL,
    confidence           TEXT,
    continuity_evidence  TEXT,
    reject_reason        TEXT,
    assignment_model     TEXT,
    prompt_version       TEXT NOT NULL,
    created_at           TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_story_arc_decisions_run_id
    ON story_arc_decisions (run_id);
CREATE INDEX IF NOT EXISTS idx_story_arc_decisions_run_date
    ON story_arc_decisions (run_date);
```

Column semantics:

- `candidates` — JSON array of the arcs actually supplied to the model
  (the post-limit `scored[:limit]` slice), each as
  `{"arc_id": 143, "arc_label": "China-Russia diplomatic visit", "score": 34}`.
  `arc_label` is the untruncated `canonical_label`; `score` is the
  `arc_candidate_score` value at decision time. This is the only place
  decision-time scores survive.
- `arc_id`, `parent_story_id` — the model's parsed proposal, recorded even when
  the decision is rejected (mirroring how `story_match_decisions` keeps
  `candidate_story_id` on rejects). `NULL` when the model chose `NEW_ARC` or
  returned nothing usable. `accepted` says whether the proposal was applied; the
  effective attachment is `arc_id` only where `accepted = 1`.
- `story_id` — the story row this label resolved to in the same run (created or
  reused). This makes an attachment reconstructable end to end:
  decision -> candidates -> chosen arc -> resulting story row. It also exposes
  the `find_story_by_label` reuse path that bypasses the verifier (the Phase 3a
  target), because those rows show a reused `story_id` with no accepted arc.
- `assignment_model`, `prompt_version` — `ARC_ASSIGNMENT_MODEL` and
  `ARC_ASSIGNMENT_PROMPT_VERSION`.

A label that produced no model case (no candidate arc scored above zero, or no
current articles) gets no row. Absence of a row for a new story therefore means
"no arc candidates existed", which is itself auditable.

### Hard constraint: the prompt does not change

Candidate labels and scores for the audit trail are collected *beside* the
prompt cases, never inside them. The JSON sent to the model stays byte-identical
to today, so prompt semantics, the response cache (ADR 0012), and `match-arc`
cost are all untouched. This change adds zero LLM calls — only SQLite writes,
on the order of tens of rows per run.

### Surfacing

The pipeline report already prints `Arc assignments` / `Arc attachments` from
the run totals. The new visibility goes into the novelty audit
(`novelty_audit()` payload, `novelty_audit_lines()` rendering, and the markdown
report), guarded by `_table_exists(conn, "story_arc_decisions")`:

1. **Arc attachments to review** — accepted decisions for the run, joined to
   the arc's current child count, ordered by child count descending. Arcs
   accumulating the most children ("Film review", 9 children) surface first.
   Fields: today label, arc id + label, relationship, confidence, chosen
   candidate's decision-time score, arc child count.
2. **Rejected arc decisions** — `accepted = 0` with medium/high confidence,
   mirroring the existing `_rejected_related_matches` section. Fields: today
   label, proposed arc label (LEFT JOIN on `arc_id`, nullable), relationship,
   confidence, reject reason, continuity evidence.

## Implementation plan (Codex handoff)

`src/tracker/matching/arcs.py`

1. `arc_assignment_cases_for_prompt` returns `(cases, candidate_audit)`, where
   `candidate_audit` maps `today_label` to the audit list described above,
   built from the same `scored[:limit]` slice the prompt cases use. The case
   dicts themselves are unchanged.
2. `arc_assignment_from_model` additionally returns `proposed_arc_id` and
   `proposed_parent_story_id` — the parsed values before the accept gate.
   The existing `arc_id` / `parent_story_id` keys keep their exact current
   semantics (nulled unless assigned), so `tracker.track()` behavior is
   untouched.
3. `assign_story_arcs` attaches `assignment["candidates"]` from
   `candidate_audit` to every returned assignment, including
   `missing_arc_assignment` fallbacks.

`src/tracker/store/`

4. The DDL above, in the `get_db` executescript.
5. `save_story_arc_decisions(conn, decisions, run_date, assignment_model,
   prompt_version, story_ids=None)` — mirrors `save_story_match_decisions`:
   no-op on empty input, `observability.current_run_id()`, one INSERT per
   decision, `json.dumps` for `candidates` and `continuity_evidence`. Table
   columns `arc_id` / `parent_story_id` are written from the decision's
   `proposed_arc_id` / `proposed_parent_story_id`; `story_id` comes from
   `(story_ids or {}).get(today_label)`; model and prompt version fall back to
   the passed-in defaults like the sibling helper does.
6. `get_story_arc_decisions(conn, run_date=None, run_id=None)` — small read
   helper returning dict rows, for the audit queries and tests.

`src/tracker/service.py`

7. `track()` passes `ARC_ASSIGNMENT_MODEL` and
   `src.tracker.matching.ARC_ASSIGNMENT_PROMPT_VERSION` to persistence.
8. In `track()`, after the story-resolution loop inside the same write
   transaction (story ids are known there), build
   `{assignment["story_label"]: assignment["story_id"]}` and persist all values
   of `arc_assignments`.

`src/observability/audit.py`, `console.py`, and `markdown.py`

9. The two audit sections above, added to `novelty_audit()`,
   `novelty_audit_lines()`, and the markdown audit rendering, each guarded by
   `_table_exists`.

Tests (`tests/tracker/`, `tests/observability/`, fake LLM client,
`tmp_path / "stories.db"`):

10. An accepted arc decision persists with `accepted = 1`, its chosen `arc_id`,
    the resulting `story_id`, and a `candidates` JSON whose entries carry
    `arc_id`, `arc_label`, and a numeric `score`.
11. A rejected arc decision persists with `accepted = 0`, a non-empty
    `reject_reason`, and the model's proposed `arc_id` when it picked one the
    gate refused.
12. Prompt purity: the JSON the fake client receives for arc cases contains no
    `score` or audit keys — byte-for-byte the same case shape as before.
13. Novelty audit: seeded `story_arc_decisions` rows render both sections; a
    database without the table yields empty sections, not errors.

Done when: after a run, every arc attachment is queryable with its candidate
set, scores, and evidence; a South-China-Sea-type attachment is fully
reconstructable from the database alone; the full test suite passes.

## Alternatives considered

- **Extend `story_match_decisions`** — rejected for the `NOT NULL` rebuild,
  consumer-filter, and history-pollution reasons in the Decision section.
- **One row per (label, candidate) pair** — friendlier raw SQL for
  per-candidate questions, but roughly an order of magnitude more rows,
  duplicated decision fields on every row, and a shape that misrepresents the
  one-of-N decision. `json_each` covers the same queries.
- **Recompute scores at analysis time instead of storing them** — not viable;
  `arc_candidate_score` depends on arc recency and recent-story text, which
  change daily.

## Consequences

- False arcs become diagnosable after the fact, and the GATE gets its inputs:
  decision-time candidate scores, accept/reject outcomes, and proposal-vs-effect
  separation.
- The database gains a second decision-audit table that intentionally mirrors
  `story_match_decisions`; the two stay separate because they record different
  decision shapes.
- No new LLM cost, no prompt change, no cache invalidation, no migration of
  existing rows.

## Review Trigger

Revisit this ADR when:

- the GATE decision lands and Phase 3b changes how arc assignment works
- the candidate scorer changes shape enough that `{arc_id, arc_label, score}`
  no longer captures what the gate saw
- claim-backed matching (ADR 0008 Option 4, roadmap Phase 5) replaces
  label-token scoring
