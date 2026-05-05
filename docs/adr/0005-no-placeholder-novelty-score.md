# ADR 0005: No placeholder novelty score

**Date:** 2026-05-06  
**Status:** Accepted

---

## Context

The `story_observations` table had a `novelty_score` column that was never written, read, tested, or rendered. The documentation also called out that the field existed but was not populated.

That created a misleading signal: the schema implied the system had a novelty model, while the pipeline only had textual story deltas.

Novelty is also not a trivial field. Possible definitions include first-seen status, source-count movement, claim-level change, entity change, or semantic distance from previous observations. Those choices affect briefing confidence and should not be hidden behind an unused column.

---

## Decision

Remove the placeholder `novelty_score` column from fresh `story_observations` schemas.

Do not add a stored novelty score until the project has a clear definition, tests, and a reason to persist it. Existing local SQLite files are runtime artifacts and may retain old columns until rebuilt or manually migrated.

---

## Rationale

**Schema should reflect behavior.** A stored column should either be populated or have a near-term migration path. Otherwise reviewers cannot tell which fields matter.

**Novelty should be claim-backed later.** A simple placeholder such as "new story equals 1.0" would be cheap but weak. The stronger version should compare current claims or story observations against previous memory.

**Observability should come first.** Novelty scoring will affect briefing selection, confidence, or uncertainty labels. That makes it easier to justify after `runs`, `llm_calls`, and `--pipeline-report` exist.

---

## Consequences

**Positive:**
- Keeps the schema honest
- Removes dead data-model surface
- Forces future novelty work to define semantics before storage

**Negative:**
- Future novelty work will need to add the column or a related table back
- Existing ignored local databases may temporarily contain an old unused column

---

## Review trigger

Revisit this decision when:
- claim-backed source agreement exists
- run observability can measure cost and behavior changes
- the system needs a stored novelty signal for briefing selection, confidence, or evaluation
