Run one bounded News improvement experiment, starting from
`/Users/mrgreen/Desktop/AI/News-worktrees/from-scratch`.
Scheduled time: Sunday at 10:00 Europe/Brussels. This prompt does not create
or activate the schedule.

Read `AGENTS.md`, `DOGFOOD.md`, `EVALUATION.md`, recent dogfood reports and
`.news/dogfood/feedback.md`. Inspect the Git state and active experiments first.
Preserve user changes, original sources, accepted memory and all earlier results.
Do not run an experiment or make repairs in the daily state.

1. Choose one concrete hypothesis from a documented reader or operational
   failure. Record the expected benefit, plausible regression, baseline commit,
   intended code/task delta and what result would leave the change unpromoted.
   Do not select a change merely to raise an existing pair score. If no supported
   hypothesis is available, report that and stop without model calls.

2. Create a permanent branch `experiments/dogfood-YYYYMMDD` and a sibling worktree
   under `/Users/mrgreen/Desktop/AI/News-worktrees/experiments/dogfood-YYYYMMDD`,
   using the Europe/Brussels date. If that name already exists, inspect it; never
   reset or overwrite it. Use a recorded unique suffix for a separate experiment.
   Work on one candidate at a time. Keep research artifacts in that worktree's
   `.news/`; use a small tracked experiment report to index the preserved evidence.

3. Freeze source inputs and a consistent read-only snapshot of accepted prehistory
   plus needed artifacts. Use independent baseline and candidate states seeded
   from the same frozen prehistory, never the live journal. The prehistory must
   end before the evaluation window; check for future leakage. Preserve exact
   captured text, URLs, publication timestamps, observation dates, order and
   batching. Record file hashes and exclusions. Missing RSS captures are gaps,
   not permission to invent intervening history.

4. Delegate labels to an independent source-only agent before generating or
   revealing any evaluation output, including baseline output. Give that agent
   a fresh context with no inherited parent conversation (for example,
   `fork_turns="none"` where supported); do not reuse an output-exposed reviewer.
   Supply its source-only task and absolute source paths explicitly. Give it
   only original captured sources and provenance, not generated names, summaries,
   assignments, decisions or feedback that quotes model output. Freeze questions,
   expected relationships, uncertainty, source support and hashes, then obtain
   independent source review. Disclose prior source/output exposure; do not call
   reused material blind. Include useful trajectories beyond 14 days, distinct
   developments, hard near-topic negatives, unresolved questions and supported
   corrections or disagreement when the sources permit. Do not force labels.
   Clearly separate any synthetic recovery/failure control from archive evidence.

5. Implement the smallest candidate change in the experiment worktree. Keep
   application structure simple, preserve provenance and chronology, and add
   meaningful offline regression/failure tests. Run applicable tests and lint.
   Obtain an independent correctness and simplicity review before live execution.
   Freeze code, tasks, schema, runner, source/label hashes and the execution plan.
   Use an existing reviewed compatible runner, or a small offline-tested research
   runner; do not add an orchestration framework or a second product workflow.

6. Compare baseline and candidate with identical snapshots, prehistory, order,
   batching, `gpt-6-astra`, medium reasoning and 360-second per-call deadlines.
   Default budget: at most **24 nested news-model CLI invocations combined**,
   normally up to 12 per arm. Any model-driven preparation, control or recovery
   replay also counts. Freeze the allocation before calls; reduce the planned
   scope beforehand if necessary. Do not silently extend the budget, add a new
   candidate, change the frozen plan mid-run or tune from outputs. Stop each arm
   at its first processing failure, with no implicit retries. A recovery test
   must be separately specified and budgeted before execution. Preserve partial
   output and proceed with the other planned arm only if its preflight is valid.

7. Review actual dated briefings and linked story pages against the frozen
   source-only rubric. Separate story identity from event identity, supported
   resolution from invented certainty, and new developments from repeated prose.
   Record missing developments, article omissions, source coverage, retrieval
   candidates present or absent, and whether negative cases had competing context.
   Separate incorrect decisions from unavailable or unprocessed cases. Preserve
   raw successes, failures, timing and reported usage; unknown usage stays unknown.
   Cached tokens are a subset of input; reasoning tokens a subset of output.
   Report news-model usage separately from coding/review-agent usage. Summed
   invocation times are not elapsed campaign time or a controlled speed comparison.

8. Obtain a separate independent review of the final evidence and exact candidate
   commit, including principal-level correctness and simplicity. The implementer
   or prompt author cannot supply its own independent endorsement. Record reviewer
   roles, exposure, limitations and any disagreement. Passing unit tests or
   selected identity counts is insufficient evidence of reader quality. Do not
   invent an overall accuracy percentage or claim that all story quality is fixed.

Deliver a reviewed commit and concise report linking the hypothesis, frozen plan,
sources, labels, both arms, failures, usage and independent reviews. State which
reader problem improved, what regressed or remains uncertain, and the measured
scope. Leave an unsupported change on its experiment branch. The user authorized
evidence-backed integration: qualified promotion is allowed only when independent
reviews explicitly support the exact change and its compatibility with existing
state. Prefer a reviewed draft when that evidence is incomplete. Never rewrite
accepted daily history, silently migrate its database, erase failures or promote
solely because a test suite or matching metric passes. Keep daily operations and
this experiment's states separate throughout.
Only integrate between daily invocations while holding the same outer dogfood
state lock. If daily processing is active, defer integration and report the
reviewed candidate; do not change application files underneath the running process.
