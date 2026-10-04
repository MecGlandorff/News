# Preserved experiments

This candidate keeps one story workflow. Research code, source-only rubrics and
earlier implementations remain in their original Git branches and worktrees;
cleanup does not erase their evidence or promote this candidate to main.

| Experiment | Frozen code / branch | Evidence retained in its worktree |
| --- | --- | --- |
| One-pass versus extraction/grouping | `experiments/single-pass`, `experiments/staged` | `evals/RESULTS.md`, `.news/experiments/` |
| Recent event memory and archive replays | `experiments/memory-context` | `evals/MEMORY_EXPERIMENT.md`, `.news/backtests/` |
| Durable story prototype | `bd1bc6d`, `experiments/story-evolution` | `.news/long-horizon/`, `.news/scale-probe/`; frozen source rubrics, failures and the simulated storage workload |
| Structural schema constraint | `78bd767`, `experiments/story-schema` | `.news/experiments/`; original failure, frozen-payload comparisons and full replay |
| Claim-scope prompt | `bed5507`, `experiments/story-meaning` | `evals/STORY_MEANING.md`, `.news/experiments/main-story-meaning-01/` |
| FTS compaction | `ed4ce83`, `experiments/story-index` | `.news/index-probe/`; 16-pass control/variant reports, independent review and reproduction caveat |
| Untouched archive holdout | `experiments/story-evolution` | `.news/heldout-evolution/`; source-only input/rubric freeze and independent source review before outputs |
| Uncertain event identity | `20daf42`, `experiments/event-schema` | `evals/EVENT_SCHEMA.md`; preserved July rejection, compatibility checks, separate schema-only diagnostic |
| Generated-label retrieval | `6baaa70`, `experiments/story-retrieval` | `evals/RETRIEVAL_EXPERIMENT.md`; 91 fixed-context comparisons, alternative queries, capacity checks and preserved originals |
| Clean release candidate | `experiments/release-candidate` | Fresh frozen-corpus replays and independent review; not yet promoted |

These local experiment worktrees are siblings of this checkout. `.news` artifacts
are intentionally ignored and are not part of a fresh Git clone. Preserve them
when archiving this work; the runner manifests bind source, prompt, schema and
input hashes. Recorded branch names are locators; frozen commits and hashes are
the reproducibility anchors.

The candidate uses the task from `bed5507`, the event schema from `20daf42`,
the index compaction from `ed4ce83` and generated-label indexing from `6baaa70`.
The clean codebase was reviewed at `f4f9a90`; this integration still needs its
separate review and fresh live evidence. An exact-quote
guard cannot reject every semantic false merge or wrong correction label. The
schema experiments preserve that limitation explicitly. A completed replay,
passing pair cases or a fast synthetic index probe is not overall product-quality
evidence. Promotion requires independent review of the cleaned code and actual
reader-facing outputs against frozen source questions.

The index comparison originally ran against unmodified `bd1bc6d`. Reproduction
must use that baseline as documented in its separate `REPRODUCTION.md`; invoking
the old probe against an already optimized checkout would contaminate its control.
