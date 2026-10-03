# Recent evidence experiment

The rebuild is the primary system under test. Its frozen July baseline is
documented in [HISTORICAL.md](HISTORICAL.md). Both repetitions missed the same two
source-reviewed cross-day connections. The relevant events were outside the
30-event projection; an earlier identifying quote had also been replaced by a
later observation.

## Proposed change

Application commit `2438f84` removes the event-count cutoff and projects every
event observed since fourteen days before the current snapshot date. It retains
the latest evidence and adds distinct earlier quotes, including source, URL,
publication timestamp and observation day. The latest observation still defines
the displayed quote-change count. Policy version 2 prevents reuse of decisions
made under the old memory policy.

The 240,000-character request bound remains. Oversized windows fail before a
model call and preserve accepted state. This is an experiment for bounded
workloads, not a claim that arbitrary fourteen-day feed volumes fit. Historical
quotes expire with their observations; no complete lifetime history is promised.
No new storage layer, retrieval ranking or dependencies are introduced.

An independent agent reviewed the patch and ran all 221 offline tests. Six new
regressions cover event capacity, overwritten identity evidence, reused article
IDs, deduplication, expiry and over-budget state preservation. Independent
projections of the existing July journals produced maximum requests of 83,598
and 81,418 characters. That is an offline size check, not a new model result.

## Criteria fixed before measurement

- Repeat the same frozen 158 July records twice, with the same ordering,
  50/28/50/30 batches, model, medium reasoning and 180-second call deadline.
- Recover both demonstrated positive links without new incorrect merges in
  the supported July negatives; distinguish absent memory from model rejection.
- Then test independently labeled April 18–19 and May 9–10 captures, without
  changing prompts or labels in response to their outputs.
- Preserve unsuccessful calls and experiments. Record incorrect merges, missed
  connections, unprocessed pairs, request sizes, runtime and reported usage.
- Require a separate correctness and simplicity review before promotion. Treat
  remaining disagreement and capacity limits as findings, not hidden exclusions.
- Evaluate whole story trajectories spanning more than fourteen days, including
  retained early anchors, later milestones, corrections, unresolved disagreements
  and meaningful changes. Pair-label agreement is a regression signal, never an
  overall system-quality score. Test deliberately sparse ingestion separately
  from actual gaps in archive coverage.

The fourteen-day quote-history policy is therefore an intermediate experiment.
Short-slice success alone does not satisfy the durable story-evolution goal or
authorize its promotion as the finished memory design.

The April slice has 362 eligible records in eight batches. Twenty-two original
rows lack publication timestamps and were excluded before annotation; no dates
were invented. The May slice retains all 423 records in nine batches. Stable URL
hashes replace positional legacy IDs. Older publication dates remain eligible;
these are capture-day replays rather than measurements of a freshness filter.

Independent reviewers froze 24 April and 23 May pair labels before any slice
outputs were available. These include nine cross-day positives. Original audit
files, exclusions, uncertain relations, hashes and any separate label-review
caveats remain under the ignored `.news/backtests/` directories. The labels are
selected agent judgments, not comprehensive human gold or independent statistical
samples.

A separate May source cross-review identified one granularity-dependent negative
in a multi-development item. Before any May execution, a derived primary scoring
file excluded that pair, leaving 22 primary May pairs. The original 23-pair audit
remains unchanged and will also be scored for transparency. April's separate
cross-review recommended retaining its existing scoring set.

Measured outcomes will be recorded alongside the preserved baseline after the
planned experiments complete. Nothing in this experiment has been promoted to
`from-scratch/main` at the time this protocol was written.
