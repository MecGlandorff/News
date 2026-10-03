# Historical RSS comparison — 2026-10-03

The original project retains 41 daily article snapshots with 18,912 rows, spanning
April 18 through July 22, 2026. These are snapshot rows, not a count of unique
articles. July 21–22 contains 158 rows and a pre-existing reviewed matching set.

This experiment feeds those captured sources through the rebuild and compares
event assignments with preserved old runs. It does not fetch current versions of
article pages or rerun the latest legacy application.

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
