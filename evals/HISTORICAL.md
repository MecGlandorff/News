# Historical RSS comparison — 2026-10-03

The original project retains 41 daily article snapshots with 18,912 rows, spanning
April 18 through July 22, 2026. These are snapshot rows, not a count of unique
articles. July 21–22 contains 158 rows and a pre-existing reviewed matching set.

This experiment feeds those captured sources through the rebuild and compares
event assignments with preserved old runs. It does not fetch current versions of
article pages or rerun the latest legacy application.

## Completed baseline

Both fresh rebuild replays assigned all 158 articles and passed source-quote and
coverage validation. On the selected 19-pair audit, both preserved ten of twelve
positive connections and avoided all seven labeled incorrect merges.

| Saved implementation / fresh replay | Selected positives matched | Incorrect merges / 7 negatives | Selected label agreement | Legacy-label agreement |
|---|---:|---:|---:|---:|
| Original live runs, `0b693b0` | 11/12 | 4 | 14/19 | 5/10 |
| July 23 keyed reconstruction, `a31b2a2` | 8/12 | 0 | 15/19 | 9/10 |
| Earlier July 23 reconstruction, `ede09e4` | 9/12 | 0 | 16/19 | 10/10 |
| Rebuild `27929e6`, repetition 1 | 10/12 | 0 | 17/19 | 7/10 |
| Rebuild `27929e6`, repetition 2 | 10/12 | 0 | 17/19 | 7/10 |

These selected counts do **not** establish general superiority. The three legacy
positive labels are disputed from RSS evidence, and all twelve additional
positive labels are independent-agent judgments rather than human ground truth.

Both new replays missed the Gandhi arrest/release follow-up and the Hegseth
hearing update. Their predecessor events were absent from the later model input.
In repetition 1, eligible memory before the four batches contained 0, 38, 58 and
101 events, but the application exposed only 0, 30, 30 and 30. Two correctly
separated negative pairs also lacked a predecessor in memory; only five of the
seven negative checks actually presented both sides to the matcher.

The evidence history has a separate problem: a later observation replaced the
earlier Gandhi arrest quote with a broader protest quote. Increasing capacity
alone is therefore not an established fix. The Hegseth event retained only a
headline, omitting funding detail available in its captured RSS description.

| Fresh rebuild replay | Calls | Failed calls | Runtime seconds | Input tokens | Cached input tokens | Output tokens |
|---|---:|---:|---:|---:|---:|---:|
| Repetition 1 | 4 | 0 | 552.975 | 84,683 | 19,968 | 13,374 |
| Repetition 2 | 4 | 0 | 546.041 | 85,427 | 13,312 | 13,023 |

Input totals include cached input. All eight calls used `gpt-6-astra`, medium,
Codex CLI 0.160.0, with a 180-second deadline. Timing measures these calls, not a
controlled comparison against the old pipeline's full runtime or monetary cost.
The slowest first-replay call took 174.8 seconds, close to that deadline.

[historical-results.json](historical-results.json) preserves the labels, scores,
context-availability diagnostics and provenance without publishing the source
article archive. Full local artifacts remain at
`../experiments/historical/.news/historical/` relative to the clean worktree.
The initial runner is retained at `replay-01/runner.py` and commit `aa2f189`;
subsequent runner changes clarify accounting and reject null legacy assignments.
Application code and task files stayed fixed throughout measurement. The
comparison harness has six offline regression tests and was independently
reviewed; the complete offline suite passed 215 tests before live measurement.

## Protocol

- Use a read-only SQLite backup and copies of the two daily JSON snapshots.
- Include all 158 articles, including the 30 with empty RSS descriptions.
- Use captured titles plus HTML-stripped RSS descriptions as evidence. Exclude
  later full bodies and generated themes, importance, labels and assignments.
- Preserve snapshot order when making bounded batches: 50, 28, 50, 30 articles.
  The application sorts each batch by article ID before processing.
- Start each repetition with empty application state and replay days in order.
  Keep the shipped single-pass prompt, `gpt-6-astra` / medium, 50-article bound
  and 30-event memory. No prompt tuning against observed results.
- Preserve failed attempts, accepted inputs, outputs, model configuration,
  timing, usage and source hashes. The original checkout and database stay intact.

The existing review has 16 relations. Five concern broader story arcs that the
rebuild does not implement; one was already marked insufficient evidence. The
remaining ten are retained as **agreement with legacy review labels**, not
unquestionable ground truth. An independent agent reviewed only raw title/RSS
evidence before seeing new results. It found seven supported conservative
nonmatches and disputed all three positive exact-event labels. That seven-case
subset can test false merges but cannot measure recall or overall accuracy.

The same reviewer then froze twelve additional source-supported positive pairs,
covering ten same-day matches and two cross-day developments. It did not inspect
old assignments or new outputs to select or label them. Combined with the seven
supported negatives, they form a selected 19-pair audit. These are agent-reviewed
labels with shared articles, not independent statistical samples or human gold.
The original ten labels remain visible separately.

Old saved results came from multiple implementation versions. Live July 21–22
assignments and later July 23 reconstruction experiments must be shown separately;
neither should be presented as a fresh run of today's legacy checkout. Earlier
matching stages also consumed generated labels and different candidate histories,
so this is a comparison of whole pipelines on captured sources, not a controlled
comparison of the two models alone.

## Reproduction

The ignored archive directory contains `source-archive.db`, the two
`data/daily/YYYY-MM-DD/articles.json` snapshots and the original review file at
`evals/datasets/matching_reconstruction_review_2026-07-21_22.jsonl`. Its manifest
records source hashes. Historical databases and copyrighted source text are not
bundled into the clean application's Git history.

```sh
python -m evals.historical \
  --archive .news/historical --prepared .news/historical/prepared \
  --output .news/historical/replay-01 --repeats 2 --max-calls 8 --timeout 180
```

The prepared directory is created if absent. The output directory must be new.
The call budget is a ceiling, and the runner stops on its first pipeline failure.
Use a fresh output directory for a documented follow-up experiment.

## Interpretation limits

This two-day slice is a regression sample, not a representative benchmark of the
whole archive. Some review case names describe older revisions of rolling
headlines. Liveblogs can contain multiple developments, while the rebuild assigns
each captured item to one event. Empty descriptions provide only title evidence.

The old system had a broader history and different retrieval. None of its 5,421
pre-period stories was inside the 14-day window before July 21, so this audit
does not establish a recent-memory warm-start advantage for the old run. The rebuild's
30-event memory can omit relevant predecessors even within these two days;
missing candidates must be distinguished from an incorrect model decision.
Same-day memory ties are ordered by generated event ID, so repetitions can expose
different candidates. These limitations matter for the original workload, where
daily snapshots commonly contain several hundred articles.
