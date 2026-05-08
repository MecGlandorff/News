# ADR 0008: Story match continuity verification

**Date:** 2026-05-08
**Status:** Accepted

---

## Context

The tracker is responsible for preserving source-grounded event memory. A story match must mean that today's article continues the same real-world event or news arc. It must not mean that two articles share a broad topic, geography, actor, allegation type, or political context.

Run #2 on 2026-05-07 exposed a false merge:

- Existing story memory: `Gaza flotilla raid`
- Today's article source: Al Jazeera
- Today's article title: `Palestinians expose torture and sexual violence in Israeli detention`
- Today's RSS description: `Palestinian detainees and rights groups share disturbing accounts of rape, sexual violence and physical abuse.`
- Generated briefing file: `briefings/briefing_20260507_2339.md`
- Bad output: the article was presented under `Gaza flotilla raid`

The briefing itself showed the failure:

```text
Today's supplied article is not a new flotilla development but it deepens the adjacent detention-abuse issue...
```

That is not a valid continuation. It is an adjacent issue. The system should have created or matched a separate story such as `Israel detention abuse` rather than attaching it to `Gaza flotilla raid`.

Current matching flow:

```text
article title/description -> classifier story_label
story_label -> same-day consolidation
today label + recent story memory -> cross-day matcher
```

Before this ADR, the cross-day matcher received compact recent story memory and recent titles. It did not independently verify that today's article was the same real-world event. It also did not read full article text for story matching. The CLI could fetch article text with `--fetch-article-text`, but matching, classification, claim extraction, and briefing generation used RSS title and description unless claims had already been extracted.

---

## Rejected Patch

Do not fix this class of failure by adding the observed words from the bad example to `GENERIC_EVENT_TOKENS`, deny lists, allow lists, or similar keyword tables.

That kind of patch would make this specific example pass while leaving the underlying failure mode intact. It would also create brittle behavior around new topics, languages, paraphrases, and future examples. Story matching should be grounded in event continuity, not in a growing list of manually discovered failure words.

---

## Design Goal

Before a recent story is reused, the system should be able to answer:

```text
Is today's article continuing the same real-world event or story arc,
or is it only adjacent because it shares actors, place, topic, or context?
```

A good patch should:

- reduce false merges without relying on hardcoded example terms
- make the model provide match evidence, not just a label
- default to `NEW` when continuity evidence is weak
- keep cost visible and bounded
- preserve legitimate ongoing arcs where the wording changes over time
- produce testable behavior with fake clients

---

## Options

### Option 1: Prompt-only stricter matching

Keep the current input shape, but strengthen the cross-day matcher prompt with explicit instructions to reject adjacent issues.

Tradeoff:

- Lowest implementation cost
- Does not materially improve auditability
- Still lets the model silently accept a weak match
- Hard to test beyond canned responses

### Option 2: Structured continuity verifier

Change cross-day matching so each candidate match returns structured evidence:

```json
{
  "today_label": "Israel detention abuse",
  "canonical_label": "Gaza flotilla raid",
  "same_event": false,
  "relationship": "adjacent_topic",
  "continuity_evidence": [],
  "reject_reason": "The article concerns Palestinian detainees generally, not the flotilla raid or detained flotilla activists."
}
```

The tracker would only accept a match when:

- `same_event` is true
- `relationship` is an allowed continuity type
- at least one continuity evidence item points to a shared event identity, not only a shared topic
- the returned canonical label is one of the supplied candidates

Tradeoff:

- Improves auditability without a new database table
- Keeps the matcher as the decision point
- Adds prompt/schema complexity
- Still depends on the article context supplied to the model

### Option 3: Ambiguity-gated full article verification

Use the cheap label matcher first. When a candidate match is plausible but risky, verify with richer article context before accepting it.

Possible flow:

```text
label candidate found
-> if high-confidence exact continuation, accept
-> if ambiguous, verify using today's article title, RSS description, and full text when available
-> require structured same-event evidence
-> default to NEW if verification is weak
```

Tradeoff:

- Directly addresses cases where an RSS summary is too thin
- Keeps full-text cost targeted instead of defaulting to every article
- Requires a definition of "ambiguous"
- Requires deciding whether the verifier can trigger network fetches or only use text already fetched by `--fetch-article-text`

### Option 4: Claim-backed story matching

Extract claims first, then compare current article claims against recent story claims or story observations.

Tradeoff:

- Best aligned with the project direction: `Article -> Claim -> Story Arc`
- Can eventually distinguish repeated, new, adjacent, and contradictory claims
- More expensive today
- Depends on broader claim extraction coverage and claim-level comparison, which is still Phase 3 work

---

## Recommendation

Do not implement a keyword patch.

Implement Option 2 plus a narrow form of Option 3 behind `--verify-story-matches`:

- require structured continuity decisions for cross-day matches
- include today's title, RSS description, reported date, and full article text in the verifier input when available
- when the verifier flag is enabled and text is missing, fetch article text only for candidate matches
- use `gpt-5.4-nano` for the verifier
- default to `NEW` for adjacent-topic relationships
- store verifier decisions in `story_match_decisions`
- report verifier accepted/rejected counts in `--pipeline-report`
- add tests using the Al Jazeera detention article versus `Gaza flotilla raid`

This keeps the fix focused on event continuity rather than topic tokens. It also leaves room for the later claim-backed matcher without forcing broad claim extraction into every run.

---

## Open Questions

1. What relationships are acceptable continuations beyond `same_event`, `same_story_arc`, and `direct_follow_up`?
2. Should a story with no strong match become `NEW`, or should it be attached to a broader parent arc once parent/child story arcs exist?
3. What fixture format should hold the 5-10 reviewed true/false match examples from recent newspapers?

---

## Review trigger

Revisit this ADR when:

- cross-day story matching is changed
- claim-extraction input strategy changes again
- claim-backed source agreement or contradiction detection creates reusable claim comparison logic
- briefing output again contains prose that admits a story is adjacent rather than a continuation
