# Durable story evolution experiment

The target is an ongoing story containing distinct, sourced developments. It must
explain what changed and what remains unresolved, preserve early causal anchors
after quiet periods, and avoid turning a shared person or topic into a story link.
The existing fourteen-day event projection is an intermediate comparison system.

## Frozen evaluation

Before any outputs, an agent selected 34 archived title/RSS captures across 20
capture dates. A separate agent checked every source reference and all 15 reader
questions. The three selected trajectories span 18 days (Music On), 23 days
(Hondius) and 39 days (Hungary's political transition). This is purposive evidence,
not representative news accuracy. A separate artificial sparse scenario replays
three genuine Music On captures with a deliberately created 17-day ingestion gap.
It has one fully applicable original question and is reported separately.

The input corpus, original rubric, role distinctions, source hashes and review
notes are frozen under `.news/long-horizon/`. Models receive only article
snapshots and the application's ordinary retrieved history. They never receive
the evaluation rubric, source-selection notes or expected answers.

Run the unchanged recent-event implementation and the durable-story prototype
from separate empty states, with identical chronological snapshots. Use
`gpt-6-astra`, medium reasoning and a 360-second call deadline. Each main replay
has a ceiling of 20 calls; each sparse replay has a ceiling of three. Stop at the
first failure, retain partial results, and never retry invisibly. Revisions or
repetitions use separately named output directories. These compare product
behaviors; they are not an isolated retrieval ablation or latency benchmark.

## What the review measures

The reviewer reads the actual Markdown outputs against each frozen question,
using source captures and the journal to verify claims. Hidden stored sources
cannot substitute for a useful reader-facing timeline. Report each question as
missing/wrong (0), substantially correct but incomplete (1), or fully supported
with required dated anchors and uncertainty (2). Do not convert a sum into an
overall system-quality percentage.

Report story membership and event identity separately. Distinct connected
developments should share a story without becoming one event. Describe incorrect
story merges, missed connections, duplicate or missing developments, retrieval
availability, unsupported facts, false closure, and chronology errors explicitly.
Capture dates mean "observed on"; source-stated event dates can be earlier. Refund
promises are not completed payments, and tests of different patient groups do
not establish a contradiction. The selected archive includes no explicit
publisher correction notice; correction behavior also needs synthetic tests.

Record calls, failures, execution duration, input/output tokens, missing usage,
complete request size and actual retrieval diagnostics. No hit in a lexical
index proves neither that a story is new nor that no relevant history exists.
Review candidate availability separately from the model's use of candidates.

Promotion requires an independently reviewed, simple implementation plus
evidence of improved durable linking and useful timelines without material
unsupported claims or new incorrect merges in the measured cases. The short
July audit alone cannot satisfy this gate. Full-feed workload limits, lexical
retrieval misses, selected sources and agent judgment remain explicit limits;
passing three selected trajectories would not certify general product quality.

## Runner

`evals.evolution` validates prepared-file hashes, source references, chronology,
rubric/review bindings and the call ceiling before model execution. It preserves
daily briefings and, for the story engine, full story timelines alongside model
artifacts and a report. Semantic review remains a separate artifact.
Links in the collected daily briefings open the story as known at that run.
The separate `timelines/` exports contain each story's full accepted history at
the end of the replay; they must not be mistaken for what an earlier run knew.

```sh
python -m evals.evolution \
  --prepared .news/long-horizon/prepared \
  --rubric .news/long-horizon/rubric.json \
  --review .news/long-horizon/label-cross-review.json \
  --output .news/experiments/long-stories-01 \
  --engine stories --max-calls 20 --timeout 360
```

Use `--engine events` in the recent-memory worktree for its unchanged event
pipeline. For the sparse scenario substitute its own `prepared` directory and
rubric, retain the shared independent review, use a fresh output path and a
three-call ceiling. All results remain experimental until measured and reviewed.
