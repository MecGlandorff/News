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
| Daily capture, recovery and routine preparation | `experiments/dogfood-routines` | `.news/live-smoke/`, `.news/live-reviewed/`, `.news/validation/` and `.news/final-review.*`; operational checks, raw feeds, bounded model runs and independent review |

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

## Dogfooding operations, 2026-10-05

The daily wrapper retains source versions, freezes small chronological batches,
reconciles acceptance from the story journal, and reports partial coverage and
unknown usage. It does not change the story task, schema or retrieval algorithm.
The application now has 1,955 physical Python lines in eight modules. All 228
offline tests and Ruff checks passed. Separate reviews covered the source
collector, launch accounting, recovery, dates, provenance and simplicity.

Two explicitly bounded live checks used the configured NOS, BBC and Guardian
feeds and `gpt-6-astra` with medium reasoning:

| Check | Captured versions | Accepted / pending batches | Known input / output tokens | Run seconds |
| --- | ---: | --- | --- | ---: |
| Initial wrapper, batch size 3, one-call ceiling | 96 | 1 / 31 | 10,119 / 524 | 21.160302 |
| Reviewed wrapper, batch size 8, one-call ceiling | 97 | 1 / 12 | 11,012 / 1,245 | 33.741413 |

Each check made one CLI invocation, reported its usage, and stopped at its
declared budget with an explicitly partial briefing. The sources changed between
captures; these are operational checks, not a controlled quality comparison.
The reviewed check preserved all 97 source versions' text, URLs and publication
timestamps, all raw feed hashes, processing-ID mappings and dated output links.
Its `report.json` SHA-256 is
`31b5b1c674ddb66985981e75629aef42426c1dd1642b88da31f0e871636f8dad`.

The [routine setup](DOGFOOD.md) is prepared for daily 18:00 and Sunday 10:00 in
Europe/Brussels. Scheduling is not activated: this session cannot control the
Codex app or access a supported local scheduling tool. End-to-end execution from
the scheduled-task environment remains unverified. Story-quality limitations in
`EVALUATION.md` remain open.
