# News2.0

A fresh research project for coherent, source-grounded news stories and useful
daily changes. Research replay, candidate adapters and recording tools are
implemented; a production news pipeline is not yet built.

`News2.0` is the temporary integration branch. Create small feature or experiment
branches from it and open PRs with an explicit `--base News2.0`. The previous
rebuild at [`bc7b0fb`](https://github.com/MecGlandorff/News/tree/bc7b0fb93d3ca34fdb9400d91deb4a627cf96fe9)
is a frozen comparison baseline. Its code, databases and outputs are not a new
implementation or evaluation truth. The empty starting commit retains common
Git ancestry so a later transition to the permanent main branch remains possible.
Bootstrap commit `2033740` is in this branch's ancestry. Integration still depends
on bootstrap PR #58 reaching `News2.0`; verify that dependency and the exact target
before merging subsequent research changes.

## What the system must explain

The daily briefing chiefly presents meaningful developments in the most important
new and ongoing stories. For each matter, show what was previously supported,
what new evidence adds, the supporting sources, and what remains uncertain.
A new article alone does not establish a meaningful change. Extended analysis
belongs under a separate heading, with evidence and interpretation distinguishable.
Importance is a reader preference assessed within the observed source window,
not objective world importance inferred from source counts; disclose missing coverage.

- One document may support zero or several distinct observations. A digest must
  not force unrelated matters into one event or story.
- Separate a real-world occurrence from the broader story it belongs to.
  Shared people, places or topics alone do not establish that relationship.
- Merge when the evidence supports it; display uncertain connections as possible
  relationships. Useful coverage must not depend on resolving every relationship.
- Represent new occurrences, material new facts about an existing occurrence,
  explicit corrections, unresolved disagreement and answered questions.
- Preserve attribution, exact evidence and uncertainty. Publication, capture,
  occurrence and processing times have different meanings.
- Keep captured sources immutable. Story membership and summaries are versioned
  interpretations that can be superseded automatically, with an audit trail.
- Distinguish a source correcting its claim from the system repairing its own
  interpretation. Regenerated wording is not fresh news.
- Keep acquisition independent of processing failures. Uncertain work must stay
  visible without indefinitely blocking unrelated useful work or hiding omissions.
- Assess initial behavior across the first 30–90 days of suitable observed evidence.
  This is an assessment horizon, not a story expiry: old stories, evidence and
  unresolved questions remain available, and late developments can reconnect them.

## Research sequence

1. **Protocol and casebook.** Audit source provenance, chronology, prior exposure
   and text sufficiency. Freeze source-only expectations, scoring rules, absolute
   quality floors and comparison margins before inspecting candidate outputs.
   Use independent labeling and adjudication. Known failures are development
   regressions, never newly claimed holdout examples.
2. **Representation and replay harness.** First demonstrate that the required
   outcomes can be expressed without invented events or lost source contributions.
   Build replay and accounting around immutable inputs and explicit observation
   order. Synthetic stress and historical data with uncertain capture dates must
   be reported separately from authentic online evidence.
3. **Parallel architecture variants.** Develop more than two distinct approaches
   to representation, linking and recovery under the common reader contract.
   The [direction record](research/DIRECTION.md) defines the bounded next batch.
   Retain direct reconstruction as a reference and the frozen rebuild as a control;
   match source evidence, model settings and declared resource ceilings.
4. **Evaluation and recovery.** Replay complete trajectories, including quiet
   gaps, competing matters, corrections and multi-matter sources. Preserve failed
   trials and predeclared repeats for variability. Measure automatic prevention,
   detection and repair; compare recovery against fresh prefix reconstruction.
   Every additional component must earn its complexity through measured benefit.
5. **Prospective use.** Validate unattended capture, processing and recovery on
   newly observed sources. Claims about 30/60/90-day evolution require suitable
   source-supported trajectories and declared coverage gaps, not shifted dates.

The research now includes a protocol, frozen source casebook, offline replay,
bounded D/E model adapters and acquisition recording. The
[November 1 feasibility results](research/live-feasibility/RESULTS-2026-11-01.md)
record one failed source-free preflight and a separate acquisition sideprobe;
no candidate-quality result has been measured. Calibrate cost before
budgeting larger replays. Record finite call, token and runtime ceilings
for every live experiment, including preparation, rejected calls and recovery.

The [pre-candidate protocol v0.2](research/PROTOCOL.md) records the November 1
direction revision and retains source-only labels, prefix replay and proposed
finite screening floors. It is a development proposal, not measured quality or
authorization for live model calls; holdout and prospective promotion gates remain
pending. The
[development casebook](research/CASEBOOK.md) documents source provenance,
chronology limits, local rehydration and the independent-labeling boundary.
The [labeling reference](research/LABELING.md) records completed adjudication and
its interpretation limits; the [research review](research/REVIEW.md) records the
independent assessment. These are development evidence, not replay readiness or
measured candidate quality.

## Evidence required to advance

Measure false merges, missed connections and developments, supported and novel
deltas, correction/question handling, automatic recovery, usable output coverage,
queue age, failures, runtime and token usage. Report denominators and uncertainty.
Precision among accepted outputs must be reported alongside rejected and pending
work. A system that refuses everything is not a successful news system.

Evaluate missing information separately: uncaptured source, insufficient text,
extraction omission, retrieval miss, linking error or briefing omission. Existing
RSS archives are not assumed to contain full articles or complete daily coverage.
Legacy material already used in experiments is not presumed an unseen holdout.

Better than the old baseline is insufficient on its own. Advance a candidate only
when it meets the predeclared absolute floors, passes the relevant regressions,
and has independent review of correctness, narrative usefulness and simplicity.
Agent agreement and small perfect matching samples are not reliability estimates.
Model judges can share errors with candidates and source labelers. Deterministic
integrity checks, source-grounded semantic review, disagreement records and later
human source/product sampling answer different questions; none substitutes for
the others. Optional human sampling is not an approval gate for ordinary offline
work, and another model or model majority is not human validation.

All future research, implementation, labeling, evaluation and review agents use
`gpt-6-astra` with xhigh reasoning. Historical Sol work remains attributed as
performed. Production model choice is a separate experiment: comparisons initially
retain the baseline's `gpt-6-astra` / medium configuration unless the protocol
explicitly declares a model comparison.
External semantic judges are evaluation agents and use Astra/xhigh, with their
calls and costs recorded separately from each application arm.
The number of research agents does not prescribe the number of production calls.

## Contributing

Read [AGENTS.md](AGENTS.md). Use `news2/<task>` branches and separate worktrees for
experiments. Publish reviewable changes with `gh pr create --base News2.0` and
verify the PR's base after creation. Preserve unsuccessful experiments and their
evidence; integrate improvements only when the comparison supports them.

Raw runtime archives belong under `.news/` and are ignored. Commit deliberately
selected fixtures and manifests only when their provenance and publication scope
have been checked. Offline research checks use only the Python standard library:

```sh
python3 -m unittest discover -s research/tests -v
```

These checks validate research tooling, fake-process transport behavior and
accounting, not live model quality. No CI workflow exists yet.
The [offline replay contract](research/REPLAY.md) documents the model-free
representation, accounting and recovery probes and their limits.
