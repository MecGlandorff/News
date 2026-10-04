# Preserved experiments

The primary checkout keeps one story workflow. Research code, source-only rubrics
and earlier implementations remain in their original Git branches and worktrees.
[The evaluation summary](EVALUATION.md) records the selected improvements and
remaining reader gaps; cleanup does not erase the earlier evidence.

| Experiment | Frozen code / branch | Evidence retained in its worktree |
| --- | --- | --- |
| One-pass versus extraction/grouping | `experiments/single-pass`, `experiments/staged` | Each `evals/README.md`; `.news/experiments/single-02/report.json` and `.news/experiments/staged-01/report.json` in their respective worktrees, plus earlier/holdout attempts |
| Recent event memory and archive replays | `experiments/memory-context` | `evals/MEMORY_EXPERIMENT.md`, `.news/backtests/` |
| Durable story prototype | `bd1bc6d`, `experiments/story-evolution` | `.news/long-horizon/`, `.news/scale-probe/`; frozen source rubrics, failures and the simulated storage workload |
| Structural schema constraint | `78bd767`, `experiments/story-schema` | `.news/experiments/`; original failure, frozen-payload comparisons and full replay |
| Claim-scope prompt | `bed5507`, `experiments/story-meaning` | `evals/STORY_MEANING.md`, `.news/experiments/main-story-meaning-01/` |
| FTS compaction | `ed4ce83`, `experiments/story-index` | `.news/index-probe/`; 16-pass control/variant reports, independent review and reproduction caveat |
| Initially held-out archive slice, now reused | `experiments/story-evolution` | `.news/heldout-evolution/`; source-only input/rubric freeze and independent source review before its first outputs |
| Uncertain event identity | `20daf42`, `experiments/event-schema` | `evals/EVENT_SCHEMA.md`; preserved July rejection, compatibility checks, separate schema-only diagnostic |
| Generated-label retrieval | `6baaa70`, `experiments/story-retrieval` | `evals/RETRIEVAL_EXPERIMENT.md`; 91 fixed-context comparisons, alternative queries, capacity checks and preserved originals |
| Clean release candidate | `ff4e6ae`, `experiments/release-candidate` | `CANDIDATE_RESULTS.md`; promotion withheld after unsupported occurrence certainty survived passing identity checks |
| Document versus occurrence identity | `75729b5`, `experiments/occurrence-prompt` | `OCCURRENCE_RESULTS.md`, `occurrence-results.json`; matched prompt trials, preserved incomplete replay, fresh complete repeat and newly reviewed source challenge |

From the primary `News-worktrees/from-scratch` checkout, these local experiment
worktrees are under its sibling `News-worktrees/experiments/` directory. `.news`
artifacts are intentionally ignored and are not part of a fresh Git clone. Preserve them
when archiving this work; the runner manifests bind source, prompt, schema and
input hashes. Recorded branch names are locators; frozen commits and hashes are
the reproducibility anchors.

The selected application uses the claim-scope task paragraph from `bed5507` and the
occurrence-identity paragraph from `75729b5`, the event schema from `20daf42`,
the index compaction from `ed4ce83` and generated-label indexing from `6baaa70`.
The clean codebase was reviewed at `f4f9a90`; the integration and prompt-only
clean successor `c6c6bbc` have separate correctness/simplicity reviews. Independent
reader reviews support continued dogfooding with the limitations recorded in
`EVALUATION.md`. An exact-quote
guard cannot reject every semantic false merge or wrong correction label. The
schema experiments preserve that limitation explicitly. A completed replay,
passing pair cases or a fast synthetic index probe is not overall product-quality
evidence. Promotion requires independent review of the cleaned code and actual
reader-facing outputs against frozen source questions.

The index comparison originally ran against unmodified `bd1bc6d`. Reproduction
must use that baseline as documented in its separate `REPRODUCTION.md`; invoking
the old probe against an already optimized checkout would contaminate its control.
