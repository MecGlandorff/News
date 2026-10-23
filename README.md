# News2.0

A fresh research project for coherent, source-grounded news stories and useful
daily changes. This branch starts without an application implementation.

`News2.0` is the temporary integration branch. Create small feature or experiment
branches from it and open PRs with an explicit `--base News2.0`. The previous
rebuild at [`bc7b0fb`](https://github.com/MecGlandorff/News/tree/bc7b0fb93d3ca34fdb9400d91deb4a627cf96fe9)
is a frozen comparison baseline. Its code, databases and outputs are not a new
implementation or evaluation truth. The empty starting commit retains common
Git ancestry so a later transition to the permanent main branch remains possible.

## What the system must explain

For an ongoing matter, show what was previously supported, what new evidence
adds, the supporting sources, and what remains uncertain. A new article alone
does not establish a meaningful change.

- One document may support zero or several distinct observations. A digest must
  not force unrelated matters into one event or story.
- Separate a real-world occurrence from the broader story it belongs to.
  Shared people, places or topics alone do not establish that relationship.
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
3. **Two minimal candidates.** Compare direct reconstruction of a story view from
   source evidence with source-local observation extraction followed by story
   reconstruction. Retain the frozen rebuild as a control. Use matched source
   inputs and model settings; do not improve evidence for only one arm.
4. **Evaluation and recovery.** Replay complete trajectories, including quiet
   gaps, competing matters, corrections and multi-matter sources. Preserve failed
   trials and repeat trials for variability. Fresh-generation reconstruction is
   the recovery reference; incremental updates and selective repair must earn
   their added complexity through measured benefits.
5. **Prospective use.** Validate unattended capture, processing and recovery on
   newly observed sources. Claims about 30/60/90-day evolution require suitable
   source-supported trajectories and declared coverage gaps, not shifted dates.

The next research PR should provide the frozen research protocol and
casebook, not a new news pipeline. Calibrate cost on a small development slice
before budgeting larger replays. Record finite call, token and runtime ceilings
for every live experiment, including preparation, rejected calls and recovery.

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

Research agents use `gpt-6.1-sol` with high reasoning. Production model choice is a
separate experiment: comparisons initially retain the baseline's `gpt-6-astra` /
medium configuration unless the protocol explicitly declares a model comparison.
The number of research agents does not prescribe the number of production calls.

## Contributing

Read [AGENTS.md](AGENTS.md). Use `news2/<task>` branches and separate worktrees for
experiments. Publish reviewable changes with `gh pr create --base News2.0` and
verify the PR's base after creation. Preserve unsuccessful experiments and their
evidence; integrate improvements only when the comparison supports them.

Raw runtime archives belong under `.news/` and are ignored. Commit deliberately
selected fixtures and manifests only when their provenance and publication scope
have been checked. No application tests or CI workflow exist in this bootstrap;
add executable checks with the first executable implementation.
