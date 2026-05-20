# Briefing Selection And Memory Continuity Audit

## Status

Addressed pending real-run review.

This issue documents run-quality concerns from the May 18 and May 19 pipeline reports. The code now implements the selected fix; the remaining work is to validate it on fresh real pipeline reports.

## Resolution

Implemented fix:

- Briefing selection no longer hard-excludes `Tech`, `Science`, or `Sports`; it applies theme penalties instead.
- `Sports` receives a much stronger penalty than `Tech` and `Science`, so ordinary sports stories stay unlikely while exceptional high-source/high-importance sports stories can still appear.
- The tracker now has explicit `story_arcs`, `stories.arc_id`, and `stories.parent_story_id` support.
- Existing flat story rows receive a compatibility arc without merging historical stories.
- Same-story verification remains conservative; rejected or unmatched labels can use a cached `gpt-5.4-mini` arc-assignment stage to attach a new concrete story under an existing arc.
- New-run articles attach to the concrete story row, while briefing output can show arc and parent-story context.
- Novelty audit output includes adjusted selection score and penalty information for omitted high-signal stories.

Documented in [ADR 0016](../docs/adr/0016-briefing-theme-penalties-and-explicit-story-arcs.md).

## Why This Matters

The project goal is source-grounded event memory. The current reports show the system is inspectable, but also show two risks:

1. High-signal stories can be omitted from the briefing because section policy excludes or deprioritizes their theme.
2. Many daily developments are still being treated as new parent arcs, which suggests the memory layer may be over-splitting continuing events.

## Evidence

### 2026-05-18 Run

- New parent ratio: 179/233, 76.8%.
- High-signal not displayed:
  - San Diego mosque shooting, Other, score 561.0, 5 sources, importance 5.0.
  - OpenAI-Musk lawsuit, Tech, score 384.0, 7 sources, importance 3.0.
- Suspicious rejected related match:
  - Bangkok train crash -> Bangkok train crash, direct_follow_up, high.

### 2026-05-19 Run

- New parent ratio: 193/272, 71.0%.
- High-signal not displayed:
  - Ebola outbreak in Congo, Science, score 481.1, 6 sources, importance 4.1.
  - Speed camera expansion, Dutch Politics, score 373.0, 6 sources, importance 3.0.
- High-signal new parent arcs:
  - Andic death probe, Other, score 372.0, 6 sources, 6 articles, importance 3.0.
  - Speed camera expansion, Dutch Politics, score 372.0, 6 sources, 6 articles, importance 3.0.
- Rejected related matches to review:
  - Iran war -> Iran war escalation and fallout, broader_context, high.
  - Chip demand -> Chip shortage prices, broader_context, high.
  - Civic education -> Civics education, adjacent_topic, high.
  - Dutch inequality -> Dutch economy, adjacent_topic, high.
  - Iran attack in London -> Iran conflict, adjacent_topic, high.

## Diagnosis

The reports are not failed runs. They are useful diagnostic runs: schema failures, retries, and LLM errors were zero, cost stayed around EUR 0.80, and the novelty audit surfaced real editorial and memory-continuity problems.

The concerning signals are:

- New parent ratios above 70% are high for an event-memory system.
- Theme exclusions can hide stories that are source-backed and important.
- Some rejected matches are probably correct, but high-confidence related matches need review because they may indicate missing parent-child attachment behavior.
- The system needs clearer rules for when a high-signal item overrides section exclusions.

## Future Fix Candidates

Historical candidates considered before the fix:

1. Add a high-signal briefing safety net.
   - Candidate rule: include any story above a score threshold or source-count/importance threshold even if its theme is normally excluded.
   - Risk: the briefing may become too long or allow low-relevance Science/Tech stories to displace more important public-interest news.

2. Review section exclusion policy.
   - Science and Tech are currently easy to omit unless they qualify as lead stories.
   - This should distinguish low-interest product/media stories from public-health, infrastructure, AI-governance, lawsuit, security, and major science stories.

3. Review parent-child attachment semantics.
   - Some rejected matches are useful as parent context even when they are not the same concrete event.
   - The fix should preserve the distinction between same-story merge and broader parent-arc attachment.

4. Add a manual review loop for novelty-audit rows.
   - Use real runs to mark omitted high-signal stories as "should display" or "okay to omit".
   - Use rejected related matches to label "same event", "new child under parent", "adjacent only", or "unrelated".

5. Define acceptable new-parent ratio expectations.
   - A broad daily news run will always produce many new stories.
   - The project needs a rough target or review threshold so future reports can be judged consistently.

## Done Criteria

- High-signal omitted stories are rare and explainable in fresh real-run reports.
- Public-health, mass-casualty, major legal, major science, major tech-governance, and major geopolitical stories are not hidden only because of theme policy.
- Rejected high-confidence related matches are reviewed against real examples after the explicit-arc implementation.
- Arc attachments improve continuity without false-merging distinct concrete events.
- New arc/new parent ratios become explainable in the novelty audit.
