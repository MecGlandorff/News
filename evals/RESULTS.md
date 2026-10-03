# Experiment results — 2026-10-03

**Keep `single` as the default.** Both approaches passed every labeled trial.
The staged approach added a model call without a measured quality gain on either
corpus. It remains an explicit option for further experiments.

All calls selected `gpt-6-astra`, medium reasoning, using Codex CLI 0.160.0.
Prompts, schemas and model settings stayed fixed during measurement. Separate
subagents operated the single and staged worktrees. A third agent authored the
labels and reviewed the implementation. Holdout labels were fixed before that
agent inspected live results. No prompts were tuned against the holdout.

| Corpus and approach | Passing trials | Codex calls | Total seconds | Input tokens | Output tokens |
|---|---:|---:|---:|---:|---:|
| 16 short cases × 2, single | 32/32 | 32 | 323.780 | 285,278 | 4,901 |
| 16 short cases × 2, staged | 32/32 | 64 | 588.664 | 579,606 | 8,362 |
| 4 longer holdouts × 2, single | 8/8 | 8 | 116.466 | 78,826 | 2,083 |
| 4 longer holdouts × 2, staged | 8/8 | 16 | 283.444 | 155,892 | 6,134 |

All four runs completed. Across **80 trials and 120 Codex invocations**, exact
grouping and per-article continuation matched the labels; there were no execution
failures or quote-validation errors. Reported input totals include cached input.
They are usage observations, not monetary cost estimates. Runs overlapped on the
same machine; timing is an observation, not a controlled throughput benchmark.

The staged approach took 1.82 times as long on short cases and 2.43 times as long
on the holdout. Its extraction retained 96.45% of short-source characters: ordinary
articles passed through unchanged, while the injected instruction was removed.
On the longer cases it retained 41.61%, but that reduction did not improve the
measured decisions. A second Codex session still added input and output tokens.

Repeated calls were not byte-for-byte deterministic. Single-pass labels varied
in 7/16 short cases and 2/4 holdouts; quotes varied in 2/16 and 1/4 respectively.
Staged holdout evidence varied in 2/4 cases. Event partitions and prior-event
assignments stayed consistent. The application reuses accepted identical runs;
the experiment runner deliberately makes fresh calls for each repetition.

## Evidence and scope

[results.json](results.json) retains all 80 final responses, scores, durations,
summaries and experiment manifests. Those manifests include corpus/source hashes,
CLI version, model configuration and limits. Full call logs, prompts, schemas and
metadata remain in the ignored runtime directories of the experiment worktrees:

```text
../experiments/single-pass/.news/experiments/single-02/
../experiments/single-pass/.news/experiments/single-holdout-01/
../experiments/staged/.news/experiments/staged-01/
../experiments/staged/.news/experiments/staged-holdout-01/
```

Paths above are relative to the project root in the local worktree setup. The
portable JSON record is committed; those raw runtime directories are not.
Configuration smoke tests, the interrupted preliminary `single-01` run, and the
two-day application demo are excluded from the comparison counts.

The final validators rechecked all 80 saved responses, including both original
and selected evidence in the staged results, and all 120 saved request payloads
passed the final size bound. An additional size check added after measurement
rejects extraction that expands a later request; it changes no prompt or decision
on these recorded inputs.

All 20 scenarios are **synthetic**. The short set contains 45 articles; the four
holdouts contain 12 articles of 1,530–1,676 characters each. They exercise event
identity, conflicting reports, revisions, multilingual reports, malicious source
instructions and late context. They cannot establish real-world accuracy,
independent corroboration, usefulness on full-length journalism or performance
with large histories. Exact quote validation proves text occurrence, not truth
or relevance. Manual review of selected outputs found appropriate quotes and
conservative labels; it is not an exhaustive semantic evaluation.

## Independent implementation review

The requested principal-engineer review found no unresolved substantive blockers
at implementation commit `7064889` **within the documented macOS/Linux,
small-workload scope**. The reviewer independently ran all 209 offline tests and
the Ruff and whitespace checks. This is a scoped code review, not a certification
of model accuracy.

Issues found and fixed included lost rejected responses in evaluation metrics,
invalid gold labels reaching paid execution, incomplete staged-evidence checks,
unbounded historical/expanded request sizes, malformed URLs, Atom XHTML word
boundaries, and UTF-16 DTD rejection. The fixes have regression tests. The reviewer
specifically confirmed the final expanded-request guard and the identical output
schema for both approaches.

Operational checks also passed: real Codex execution over the invented two-day
example retained event identity; rerunning day two reused its accepted result;
offline replay reproduced the briefing; three public feeds supplied six captured
articles; and a built wheel loaded the CLI with all six task resources. CI is
configured for offline checks but has not been run remotely or pushed.

## Next useful experiment

Keep a manually reviewed capture of real articles across multiple days as a new
holdout, including uncertain matches and sources that revise earlier reports.
Measure event continuity and whether the selected quotes explain developments.
Add complexity only when a specific observed failure needs it. PDF rendering can
be added after the Markdown workflow earns its place in daily use.
