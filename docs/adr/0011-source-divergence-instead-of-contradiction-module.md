# ADR 0011: Source divergence instead of a contradiction module

**Date:** 2026-05-10  
**Status:** Accepted

---

## Context

Phase 3 originally listed a dedicated contradiction-detection module and `contradictions` table as a required step before Phase 4. That was a cautious trust posture, but direct contradictions across mainstream reporting are rare enough that a dedicated module is not the best next investment.

The project still needs to avoid confident prose when sources differ. The more common useful behavior is lighter: when claim comparison naturally finds different numbers, statuses, dates, or attributions, the system should preserve that difference as source divergence.

---

## Decision

Replace the Phase 3 contradiction module/table requirement with claim-backed source-divergence notes.

Phase 3 should now focus on:

- reviewed claim-quality measurement for RSS-only vs full-text extraction
- claim-backed source agreement
- lightweight source-divergence notes when comparable claims differ in number, date, status, or attribution

Do not add a dedicated contradiction module or `contradictions` table in Phase 3.

Briefing generation should not emit `confirmed conflict`. Until there is structured claim-backed divergence, source disagreement may only be surfaced as `possible conflict` or cautious prose.

---

## Rationale

**Most valuable disagreements are not hard contradictions.** Sources often differ by specificity, framing, attribution, or update timing. Treating every difference as contradiction would overstate what the system knows.

**Claim comparison is still needed.** Source agreement and divergence both depend on comparing extracted claims. That shared layer should come before any specialized conflict detector.

**This keeps the trust boundary visible.** A briefing can say reporting differs only when it can point to the claims and sources that differ.

---

## Consequences

Positive:

- Phase 3 stays focused on source agreement and inspectability
- Fewer schema and product concepts are added before claim comparison exists
- Briefings avoid overstating rare hard contradictions

Negative:

- The system will not maintain a first-class contradiction history yet
- Severe true contradictions will initially appear as source divergence rather than a specialized record
- Future contradiction work may need a new ADR if product priorities change

---

## Review trigger

Revisit this decision when:

- real runs show frequent high-impact conflicting claims
- users need contradiction history as a first-class artifact
- claim-backed source agreement has enough reviewed cases to justify a specialized conflict layer
