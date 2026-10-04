# Evaluation and remaining gaps

The rebuild is selected as the **primary system under test** after separate
correctness, simplicity and reader reviews. This advances the initial `27929e6`
baseline using measured memory and identity improvements. The substantive reader
gaps below remain open; overall story-evolution quality is not established.

The evaluated application is `c6c6bbc`, byte-identical to the application in
experiment `75729b5`. It has **1,288 physical Python lines in seven modules**,
26 prompt lines and 278 schema lines. All **171 offline tests**, Ruff checks and
format checks passed. Separate reviews covered correctness, simplicity, failure
handling and the integration. These checks do not establish model correctness.

## What the comparisons establish

The initial rebuild (`27929e6`) found 10 of 12 selected positive July connections
in each of two fresh replays, with no incorrect merges among seven selected
negative pairs. Preserving source history and removing the recent-memory count
cap (`2438f84`) recovered both missing connections in two replays of the same
158 captured articles. That experiment still expired memory after 14 days.

The current workflow follows ongoing stories containing distinct developments
and attributed, dated observations. Retrieval has no age cutoff. It retains
captured source versions and exposes what was selected or omitted. Generated
story/event labels add search vocabulary: fixed-context tests recovered known
cross-language misses, but lexical search still loses some useful context.

The old-system comparison uses preserved outputs from three earlier legacy
commits. The latest legacy checkout (`ee15c2e`) was not rerun. The later July
story study uses the same captured articles in sixteen smaller batches and
separates story identity from occurrence identity; its counts are not directly
interchangeable with the earlier nineteen event-pair questions.

Selected reader findings from the current candidate:

| Study | Finding | Limit |
| --- | --- | --- |
| Real trajectories spanning 18, 23 and 39 days | Thirteen of fifteen questions fully answered; two partial. The earlier false cohort correction is avoided. | Tenerife cohort clarification is omitted; an ICC development remains disconnected. Some earlier context is also missing, so there is no single proved cause. |
| Previously held-out 30-day slice, now reused | Seven of ten questions fully answered; three partial. Court/protest occurrences are more clearly distinguished. | Occupancy evolution, a November limit and inconsistent offense dates remain omitted. Non-extension of emergency/risk-area measures was visible in the prior candidate but is absent now: a substantive loss hidden by the unchanged coarse grade. |
| New archive challenge, ten captures over six dates | Eight reader questions fully answered; eleven story and nine scored event relations agree. A named case remains connected across nineteen selected days. | Two ambiguous event dimensions stay unscored. Two negative pairs lacked the competing source; four other negative story comparisons did supply the required competition. This is a selected single-variant run. |
| Synthetic correction and disagreement | All six questions fully answered. Correction, unresolved disagreement, distinct cohorts and an unrelated drill stay separate. | Invented sources test mechanisms, not archive accuracy. |
| Sparse history control | The original cancellation remains visible after an intentionally withheld seventeen-day gap. | The intervening tent-approval report starts a separate story despite available origin context. Its thin source supports cautious interpretation; this is a continuity/granularity tradeoff, not newly imposed binary gold. |

Reader grades are source-based agent judgments: 2 means the essential question
is supported, 1 partial, 0 wrong or absent. Missing or rejected inputs are
unavailable, not model errors or successful separations. Related questions and
repeated captures are not independent accuracy samples. No overall percentage
is calculated.

The preceding full candidate (`ff4e6ae`) completed all 54 invocations and all
35 selected July identity dimensions agreed. It nevertheless reused a mixed
liveblog as a certain occurrence while its own summary denied a single
identifiable occurrence. A stricter schema alone concealed the semantic problem
by changing the uncertainty flag. That candidate was not promoted.

The 52-word prompt clarification distinguishes document continuity from
occurrence identity. On an identical known payload, all three control answers
retained unsupported certainty; all three changed-prompt answers remained
conservative. Independent review checked all ten articles, not only the target.
A separate synthetic comparison confirmed that both prompts still allow later
source evidence to resolve an initially uncertain occurrence. These are narrow
mechanism checks, not a general quality endorsement.

The sparse-context diagnostic supplied the exact same saved prior context to
both prompts three times each. All six answers chose a separate story and an
uncertain event, faithfully reported the unanswered approval requests, and
withheld unsupported timing or causality. None emitted a link to the earlier
cancellation source. This preserves the reader continuity cost but provides no
observed prompt-specific difference on that fixed context. It cannot exclude
effects through earlier decisions in a complete trajectory.

The first full replay of this prompt stopped in July after thirteen accepted
batches. Invocation fourteen logged connection resets and timed out at 360
seconds; no decision or completion usage was received. Its ten captures were
not accepted, and the final twenty were unprocessed. Among covered questions,
thirteen story and fifteen event relations agree; seven dimensions remain
unavailable or unprocessed. The later liveblog capture was not reached.
The failure, partial outputs and independent reviews are preserved. A separate
fresh repeat with unchanged code, sources, ordering, model and deadline completed
all sixteen batches and 158 captures. All seventeen story and eighteen event
identity dimensions agree, with no missing outputs. All five negative story
pairs again lacked the competing prior context; their agreement is not evidence
of resisting those false merges when the alternatives are present. Separate
review of the dated pages found all thirty-five selected reader questions
supported, with exact source pointers.

The mixed Guardian liveblog now has separate uncertain identities despite the
earlier capture being available. This avoids the prior unsupported certain reuse,
but the document revisions are no longer one navigable trajectory. An annual
Amazon fire-loss summary remains factually supported while its certain occurrence
container is debatable. The same issue appears in the prior candidate; it is an
exploratory granularity concern, not a demonstrated new false merge or new primary
label. Neither a missing date alone nor a successful schema check settles
occurrence identity.

## Recorded runtime and usage

Counts below are Codex CLI invocations. Codex can reconnect internally; the
application does not retry. Reported input includes cached input, and reported
output includes reasoning output. An incomplete invocation's usage is unknown,
not zero. Coding/review-agent usage and unreported backend usage are excluded.
Run durations overlapped; their sums are not elapsed campaign time or controlled
speed comparisons.

| Experiment | Invocations | Known input tokens | Known output tokens | Sum run seconds | Invocations with unknown usage |
| --- | ---: | ---: | ---: | ---: | ---: |
| Prior full candidate | 54 | 1,096,645 | 60,171 | 1,941.611 | 0 |
| Initial occurrence campaign, incomplete | 52 | 1,013,441 | 49,923 | 2,094.142 | 1 |
| Fresh unchanged July repeat | 16 | 485,682 | 37,845 | 1,148.842 | 0 |
| New archive challenge | 6 | 78,157 | 2,740 | 349.045 | 0 |
| Matched liveblog prompt diagnostic | 6 | 133,355 | 13,200 | 396.474 | 0 |
| Later-disambiguation comparison | 4 | 40,559 | 1,193 | 54.846 | 0 |
| Matched sparse-context diagnostic | 6 | 64,579 | 1,887 | 85.717 | 0 |

## Evidence locations

The primary checkout is `News-worktrees/from-scratch`. Paths below are relative
to its sibling `News-worktrees/experiments` directory. Worktree/branch names are
locators; frozen commits, source manifests and SHA-256 bindings identify exact
evidence. Raw `.news` contents are local ignored artifacts, not included in a
fresh Git clone. Preserve these worktrees when archiving the research.

- `historical/evals/HISTORICAL.md`: preserved legacy comparison.
- `memory-context/evals/MEMORY_EXPERIMENT.md`: matched July and additional
  April/May slices, including unsuccessful shorter-deadline attempts.
- `story-retrieval/evals/RETRIEVAL_EXPERIMENT.md`: fixed-context retrieval
  comparisons, alternatives and capacity limits.
- `event-schema/evals/EVENT_SCHEMA_RESULTS.md`: valid outputs with unsupported
  certainty; schema success is not source support.
- `release-candidate/CANDIDATE_RESULTS.md` and `candidate-results.json`:
  the unpromoted full candidate, independent reader findings and raw-file index.
- `occurrence-prompt/OCCURRENCE_RESULTS.md` and `occurrence-results.json`:
  the full prompt experiment account, failures, usage and evidence hash index.
- `occurrence-prompt/.news/trajectory-campaign/`, `.news/july-repeat/`,
  `.news/occurrence-probe/`, `.news/sparse-prompt-probe/`,
  `.news/disambiguation-comparison/`, `.news/archive-challenge/` and
  `.news/experiments/`: unchanged source labels, protocols, failures, usage and
  separate semantic reviews for this candidate.
- `occurrence-prompt/.news/promotion-independent-review.json`: the independent
  assessment of gains, regressions and limits for use as the primary system
  under test.
- `final-story/.news/integration-checks/`: byte equivalence, offline validation
  and the independent integration/simplicity review.

The work supports further dogfooding with explicit limits. Lexical retrieval,
thin RSS excerpts, missed updates and variable narrative selection still limit
story evolution. Recovering from an already accepted incorrect interpretation
needs dedicated evaluation. Full-journal projection and context limits constrain
scale; the simulated 50-article archive request exceeded the context cap.

The next quality experiments should measure coverage of meaningful developments
within each article, recovery from earlier mistaken interpretations, and difficult
alternative story links when both candidates are actually supplied. Freeze source
expectations before new outputs and retain omissions within otherwise passing
grades. The longer-term goal remains useful, sourced story evolution; the current
results do not establish that this goal is achieved overall.
