# Phase 3 Matching Audit: 2026-07-21 and 2026-07-22

**Status:** Fix required  
**Reviewed:** 2026-07-23  
**Pre-fix Git SHA:** `0b693b0`

## Outcome

Both runs were operationally healthy, but the two-day story memory was not
safe enough to close Phase 3. The main failure was not API reliability or the
price of `gpt-5.4-mini`; it was that matching decisions received incomplete or
already-grouped evidence.

The reviewed data is retained as the pre-fix baseline. Post-fix validation must
use a reconstructed database and a new five-day run series.

## Run Summary

| Signal | 2026-07-21, run 33 | 2026-07-22, run 34 |
|---|---:|---:|
| Mode | evidence | ordinary |
| Articles | 78 | 80 |
| Stories touched | 51 | 54 |
| Claims saved | 907 | not enabled |
| LLM calls | 965 | 12 |
| Estimated cost | EUR 0.74 | EUR 0.38 |
| Runtime | about 44 minutes | about 6.1 minutes |
| LLM errors / schema failures / retries | 0 / 0 / 0 | 0 / 0 / 0 |

Run 33 saved 72 deterministically derivable claims and 835 verifier-accepted
claims. The verifier rejected 48 claims, and 368 invalid candidates were
dropped. These counts show that the evidence path and its observability were
working.

Run 34 made nine direct story-match decisions: three accepted and six
rejected. It evaluated 32 arc cases, accepted nine attachments, and created 42
new parent arcs. The direct mini decisions were mostly cautious; the arc layer
and same-day grouping produced the material quality failures.

## Reviewed Matching Cases

### Correct direct continuity

- `India student protests` continued the same protest event.
- `Iran conflict escalation and diplomacy` continued the Iran conflict.
- `World Cup final` continued the same final and its aftermath.
- The omitted `Ukraine military shakeup` verifier response should have failed
  closed without creating a duplicate story row.

### Unsafe or structurally wrong memory

| Current story | Stored memory | Review |
|---|---|---|
| Erasmus Bridge tram crash | Bridge safety inspections | False arc: generic bridge/safety overlap |
| Sugar tax lobby | Tax reform debate | False arc: generic tax overlap |
| Tour de France stage | Tour de France crash | The stories share a tournament, but the stored arc label is a concrete crash rather than `Tour de France 2026` |
| Ukraine war | Ukraine military shakeup | False parent; the current group also mixed a separate operational strike with leadership coverage |
| Football transfers | one same-day story | Mixed unrelated clubs, matches, injuries, and transfers |
| Tour de France crash | one same-day story | Mixed a Lipowitz crash with an unrelated timing commentary item |

### Useful but policy-sensitive arc cases

- `World Matchplay incident` belongs under the named World Matchplay
  tournament.
- `England bus fares` may belong under a named Burnham government policy
  programme only when the current evidence explicitly supplies that programme.
- `B&B Vol Liefde` contestant instalments are recurring entertainment content,
  not durable real-world event memory.
- `US tariffs` must be split into concrete developments before any child is
  placed under a named tariff-policy arc.

### Missed candidates or continuity

- `Phone-free youth` should have considered the France under-15 social-media
  restriction.
- `Middle East gas prices` should have considered the Iran/Hormuz energy-shock
  context.
- `Yemen stalemate` should have considered the Saudi-Houthi conflict.
- `UK prison release` should have considered the named Burnham review when that
  link is explicit in the article.
- `Tyre heritage damage` should have considered the Israel-Lebanon conflict.
- `AI agent behavior` and `AI cyberattack` covered the same reported
  OpenAI/Hugging Face incident and should have been compared before becoming
  separate same-day stories.

## Root Causes

1. The tracker grouped articles by identical classifier `story_label` before
   same-day consolidation. A matcher could merge label groups but could not
   split unrelated articles already sharing one label.
2. Arc retrieval compared the current label with arc memory. Current article
   titles and descriptions were supplied only after the shortlist existed.
3. The arc gate accepted a supplied ID, an accepted relationship, medium/high
   confidence, and non-empty model evidence. It did not validate that evidence
   against both sides.
4. New arcs inherited their first concrete story label permanently, so later
   child stories could turn a narrow event label into a misleading umbrella.
5. The static story/arc eval replayed historical model outputs through the
   acceptance gate; it did not execute the current prompt and model on article
   evidence.

## Quality Decision

Keep automatic story and arc matching, but replace it with the evidence-gated
mini cascade in ADR 0022. The acceptance target is zero reviewed corrupting
accepts. Clear positive continuity should match; genuinely ambiguous cases may
create separate memory.

The implementation PR may merge after the frozen reconstruction passes.
Phase 3 itself remains open until five fresh post-fix daily runs have been
reviewed, including at least three evidence runs.

