# News2.0 direction — 2026-11-01

Accepted product decisions and a proposed bounded research sequence. This is a
direction revision, not an architecture winner, completed evaluation or live-run
authorization. [Protocol v0.2](PROTOCOL.md) supersedes the earlier two-candidate
restriction and three-arm calibration proposal. Frozen inventories, labels and
historical reviews remain unchanged.

## Accepted decisions

- The daily briefing chiefly reports meaningful developments in the most
  important new and ongoing stories. Repetition, new publication or regenerated
  wording alone does not qualify as news. Coverage of important omissions matters.
  Importance is a reader preference within the observed source window; source
  counts/model rankings do not establish world importance. Disclose coverage gaps.
- Merge when evidence supports a relationship; show uncertain connections as
  possible relationships without counting them as established membership.
- Offer extended analysis under a separate heading. It may explain implications
  and open questions, with uncertainty visible, but cannot mutate factual state,
  accepted links or delta membership. A separate heading does not require another
  model call; every stage added later needs a reason and cost accounting.
- Assess the first 30–90 days when suitable observed evidence exists. There is
  no fixed story expiry; preserve old evidence and unresolved questions, and allow
  late evidence to reconnect matters. Missing days are gaps, not quiet news.
- Explore more distinct architecture variants in parallel. Require automatic
  prevention, detection and repair. Never manually patch production assignments,
  databases, generated briefings or replay decisions to make an experiment pass.
- All future research, implementation, labeling, evaluation and review agents use
  `gpt-6-astra` / xhigh, including external semantic judges.
  Historical `gpt-6.1-sol` / high work retains its actual attribution. Application
  comparisons separately keep `gpt-6-astra` / medium unless a frozen plan explicitly
  varies model choice. Research-agent count does not prescribe application stages.

## Parallel variants and responsibilities

Use one independent author/worktree per new arm and a separate shared-harness
owner; an author cannot be their arm's only reviewer. All arms receive the same
visible source versions and clock, with no curated case grouping as a retrieval
hint. Source quality and model changes are separate experiments.

| Arm / author responsibility | Distinct choice | Main risk to examine |
| --- | --- | --- |
| D — direct reconstruction | Rebuild supported views from raw visible evidence. | Growing context and repeated synthesis can omit evidence or change identities. |
| E — extraction and reconstruction | Extract source-local contributions once; reconstruct from the complete visible contribution set and evidence. | Extraction omissions or premature semantic commitments propagate. |
| I — incremental interpretation | Use E's extraction; update prior interpretations with explicit detection and repair. | Wrong membership, stale claims or lost contributions persist through updates. |
| R — retrieval and reconstruction | Use E's extraction; retrieve bounded source evidence and reconstruct affected views. | Missed evidence hides connections or makes reconstruction falsely confident. |
| B — frozen control adapter | Present matched evidence to rebuild `bc7b0fb93d3ca34fdb9400d91deb4a627cf96fe9`. | Prior defects and unsupported capabilities remain visible, not quietly repaired. |

E is the hub: D/E isolates extraction, E/I prior-state dependence, E/R retrieval.
Do not combine incremental state and retrieval in this first batch. These are
outcome-compatible experiments, not a required final pipeline. Every arm must
account for all sources and pending work, retain uncertainty and demonstrate
automatic recovery from identical seeded defects. Fresh prefix reconstruction
is a recovery reference, not an assumed infallible answer.
D/E/R reconstruct without prior story interpretations; only the shared declared
delta-comparison interface may read the previous published view afterward.
Freeze semantic detection/repair policy without giving it seeded defect IDs or
expected repairs. The fixture/scorer retains that information separately.

Share extraction only when its inputs, prompt, model settings and output are
identically frozen. Charge it to each arm's standalone cost and report the actual
shared experiment cost separately. Include optional analysis, validators/judges,
failed calls, retries, and detection/repair in accounting. Attribute research-agent
preparation and review separately; unknown telemetry is never zero.
Shared artifacts are prefix-safe: no future source, later version or future-derived
index statistic enters an earlier view. R's index/query use the complete visible
source corpus, never prior story summaries or case IDs; a retrieval miss does not
expire a story. Corpus gaps block live retrieval assessment, not offline interfaces.

## Assessment with fallible references

Keep three kinds of evidence separate:

1. Deterministic checks establish source/version integrity, prefix boundaries,
   visibility, output structure, accounting and persistence/recovery invariants.
   They cannot establish semantic correctness or usefulness.
2. Source-grounded semantic review checks emitted claims, supported omissions,
   merge/split decisions, meaningful deltas, questions and recovery. Blind arm
   identity where feasible; keep evidence pointers, judgments, disagreements and
   unscorable units. Labels and reviewers can share model errors. Report sensitivity
   to disputed judgments instead of treating adjudication as certainty.
   Check both canonical facts/deltas and their rendered briefing/analysis.
   Sample un-emitted sources, audit unanimous passes, and test the judge with
   independently checked error/valid-paraphrase probes and arm/order/verbosity
   perturbations. Model-authored controls alone are not verified semantic truth.
3. Small later human source/product samples can assess factual interpretation,
   importance, clarity and daily usefulness. Another model or model majority cannot
   supply this evidence. Human sampling is not an approval gate for offline work;
   if absent, say human usefulness/semantic validation remains unmeasured.
   A proposed small sample separates source-only importance/sufficiency from
   blinded output usefulness across arms and omissions; freeze its size later.

Measure false merges and missed links/developments together. Keep abstentions,
silent actionable days, rejected results, pending work, failures and missing sources
in the report. Distinguish uncertainty in evidence from unmeasured system quality.
The inherited protocol floors are proposed screens, not guarantees; below-minimum
denominators and unresolved comparisons remain insufficient evidence. No model
reviewer, agreement count or small perfect sample establishes reliability.

The current 12 cases, 49 observations and 37 prefixes are curated development
diagnostics. Their integrity checks do not establish independent trajectories,
complete-day coverage, 30–90-day continuity or automatic recovery. Archive growth
does not itself resolve these gaps. New source versions need a provenance/exposure
audit; do not silently extend the frozen inventory or call them holdout. No claim
is made here about operational schedules being active.

## Finite next batch: offline only

Complete one shared batch before application candidate calls:

Budget: **zero application model calls; six aggregate active agent-hours and one
elapsed working day**, stopping at either limit. Allocate at most three hours to
harness/interfaces, two to corpus/fixtures and one to review/corrections, including
preparation. Permit one initial independent review and at most one correction/
recheck cycle inside these caps. Log actual effort and available usage; unknown
agent tokens/cost remain unknown. Preserve unresolved work when a cap is reached;
do not restart the budget or repeat reviews until they pass.

1. **Harness and contract owner:** implement a model-free replay interface with
   immutable inputs, prefix/day boundaries, visible source accounting, explicit
   possible/accepted relationships, versioned output/state and call-budget checks.
   Thin arm interfaces and a B adapter contract use stub responses to exercise
   successful, malformed, failed and exhausted execution. This is not five
   production pipelines; no old pipeline or production state is executed or changed.
2. **Corpus and evaluation owner:** freeze one mixed-stream diagnostic input
   fixture with curated grouping withheld, a clean/contaminated derived-state
   fixture pack, and an audit of the additional full-day/long-gap evidence needed.
   Pin the effective reference/amendments, map dependencies/exposure, and list
   missing categories. Derived fixtures add no new source truth or natural news.
3. **Independent reviewer:** inspect the executable boundaries and evidence limits,
   including automatic recovery checks and both accepted and omitted output units.
   Record defects and unmeasured properties; validate only what the artifacts show.

The batch ends with one reviewable harness/fixture change and its audit, or a
specific unresolved blocker; it is not an open-ended search for passing examples.
New arms are then implemented in parallel against that common contract. Freeze
one small five-arm feasibility manifest with exact inputs and numeric budgets
before live calls; [protocol §8](PROTOCOL.md#8-offline-prerequisites-bounded-calibration-and-later-gates)
defines its required accounting and stop rules. No implied application-call budget
exists in this direction record, and the old three-arm budget cannot be reused.

Feasibility can establish executable behavior, cost and failure modes only.
Larger matched comparisons need separately frozen samples, repeats and ceilings;
full-day, genuinely unexposed and prospective 30–90-day claims require their own
evidence. Choose no architecture before those results, and add no complexity
without a demonstrated benefit.
