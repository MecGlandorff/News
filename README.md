# News

A small local news system: capture articles, group concrete events, remember
continuing events, and write a Markdown briefing with exact source quotations.
The AI work runs through **Codex CLI, GPT-6 Astra, medium reasoning**. There is no
OpenAI SDK integration or service to deploy.

This is the `from-scratch/main` rebuild. The previous implementation remains in
Git history and the original checkout. This version uses a new database; it does
not import the old database or reproduce every old feature.

## Experimental durable story trajectories

This branch adds a separate prototype for **ongoing stories with distinct
developments, sources, corrections and unresolved questions**. The existing
`run` command below remains available for comparison. The prototype has not yet
earned promotion through independent live evaluation.

```sh
python -m news story-run --input examples/day1.json --state .news/story-demo
python -m news story-run --input examples/day2.json --state .news/story-demo
python -m news story STORY_ID --state .news/story-demo
python -m news story STORY_ID --state .news/story-demo --as-of 2026-10-01
```

Each run writes a daily Markdown briefing linking to complete dated views of
the stories it touches. `story` renders every accepted observation of that story
offline. Dates are **observed on** dates: a report captured later can describe an
earlier occurrence. The source's stated occurrence date belongs in its quoted
evidence and summary, not an invented timestamp.

A story means a named ongoing matter, such as a particular court case or an
incident and its investigation. Related developments receive distinct stable
event IDs inside that story. Repeated reporting of one occurrence retains its
event ID. Sharing a person, organization or broad topic alone does not establish
story identity. Uncertain event identity is explicitly kept separate.

Events contain attributed observations. Each observation explains a source-backed
new development, additional reporting, correction, disagreement or unclear
change. Corrections and disagreements preserve both assertions with exact source
pointers; contradictory first reports and a later correction plus continued
disagreement can coexist within one event. A nullable unresolved question must
be supported by that observation's quotes. These are semantic model judgments,
not facts established by exact-string validation. Earlier dated questions remain
in the timeline; a later answer must be stated with its evidence. There is no
automatic claim that an unanswered question has been resolved.

The separate state contains `journal.sqlite3`, with an immutable accepted-run
journal and a disposable SQLite FTS5 index of **full captured source text**.
Capture identities include the complete article and capture day, so reused IDs,
URLs, changed publication dates and revised text retain distinct provenance.
The index is rebuilt from the accepted journal before each run. It has no age
cutoff, and as-of retrieval excludes future captures. This straightforward
prototype favors auditable state over indexing speed on a very large archive.

Retrieval uses up to 64 lexical terms from each current title and full text,
prioritizing title terms and rarer archive terms. It retrieves three captures per
article by default, plus recent captures of the same URL. This supplies candidates,
not automatic story links. A selected story supplies its origin, latest
observation, matching history, and recorded corrections, disagreements and sourced
unresolved questions. The full captured text of their evidence is included.
`--hits-per-article` adjusts the retrieval breadth; it must be 1–10. Lexical search
can miss paraphrases, translations or weakly named connections. Retrieval recall
must be evaluated separately from model decisions.

The canonical request is capped at 180,000 characters by default (at most 240,000
with `--max-context-chars`). If retained context cannot fit, the run stops before
the model call and keeps diagnostics. It does not silently remove origins or
corrections. Long or busy stories can reach this limit; use smaller batches and
inspect the recorded selection. There is one Codex call, no automatic retry.

`runs/<id>/` retains `input.json`, `retrieval.json` (queries, selected sources,
omissions and request size), raw `decision.json`, accepted `result.json`,
`briefing.md`, and `stories/<story_id>.md`. Transport artifacts live in `model/`.
Failures retain `failure.json`; only a row in the journal establishes acceptance.
Source/reference checks and all render writes succeed before that transaction
commits. Repeating the same snapshot, code, task and retrieval settings reuses its
accepted result without a model call. It restores that run's original story view,
including its same-day boundary, rather than introducing later observations.

Offline tests cover the representation, retrieval, provenance and failure
boundaries. They cannot establish good story grouping, meaningful summaries or
correct attribution of correction versus disagreement. Those require independent
source-only judgments and review of actual reader-facing timelines, including
quiet gaps beyond 14 days. Broad historical corpora and semantic questions stay
outside the application and ordinary tests.

## Start

Use Python 3.12+ on macOS or Linux and an authenticated Codex CLI. The transport
has been tested with **Codex CLI 0.160.0**. It uses explicit isolation settings
and strict configuration validation; unsupported CLI versions fail visibly.

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
codex login status
```

If needed, run `codex login`. The program uses the CLI's existing authentication;
model runs consume the usage associated with that account. It does not copy
authentication files or place credentials in the repository.

Run the two-day **invented** example:

```sh
news run --input examples/day1.json
news run --input examples/day2.json
```

Each command prints the run ID and path to its `briefing.md`. An identical input,
strategy and prompt configuration reuses its accepted run without a model call.
See the [generated day-two example](examples/briefing-day2.md).
Re-render any accepted run entirely offline:

```sh
news replay RUN_ID
```

## Capture news

Edit `feeds.json`, then capture a dated snapshot. The editorial timezone is
Europe/Brussels. Fetching is separate from AI processing, so every experiment can
use the same captured source text.

```sh
news fetch --day 2026-10-03 --max-per-feed 5 --output .news/articles-2026-10-03.json
news run --input .news/articles-2026-10-03.json
```

Choose the desired date; feed archives usually expose only recent items. `fetch`
uses RSS/Atom descriptions or embedded content, not an article-page scraper.
Missing dates, empty descriptions and invalid items are counted in the fetch
report. Any failed feed aborts capture instead of silently returning a partial
snapshot. Existing snapshot files are never overwritten. An empty capture is an
error, not an empty successful briefing.

You can supply captured full article text yourself in the same input format:

```json
{
  "day": "2026-10-01",
  "articles": [{
    "id": "a1",
    "source": "Example News",
    "url": "https://example.test/bridge",
    "published_at": "2026-10-01T08:00:00Z",
    "title": "Bridge closes",
    "text": "The Brook bridge closed after a truck collision."
  }]
}
```

IDs and URLs must be unique within the snapshot. Every article needs a timezone-
aware publication timestamp and source text. An article is assigned to one event;
multi-event digests should be split into articles before processing.

## How it works

```text
dated article snapshot + recent event memory
  -> versioned task file -> codex exec -> structured decision
  -> schema, coverage, exact-quote and reference checks
  -> one SQLite transaction -> deterministic Markdown
```

`single` makes one Codex call per batch. `staged` first selects exact evidence,
then groups events from that evidence; its final quotes must match both the
selected text and the original articles. To compare it in its own memory:

```sh
news run --input examples/day1.json --strategy staged --state .news/staged-demo
```

All application model calls use `gpt-6-astra` with medium reasoning. Prompts and
JSON schemas live in `news/tasks/`. Codex runs in a temporary directory with a
read-only sandbox, disabled browsing/tools and personal configuration discovery,
and no project instructions. Source text is passed through stdin as data. See
[the official exec documentation](https://developers.openai.com/codex/noninteractive).
One host-skill-discovery isolation flag is experimental in the tested CLI; its
warning is retained in call diagnostics.

The program rejects missing articles, duplicate assignments, unknown memory IDs,
nonexact quotations and malformed responses before changing event memory. Failed
calls are not retried automatically. The default deadline is 180 seconds per
call (`--timeout`); timeout and interruption terminate the subprocess group.

## State and limits

Runtime files live under `.news/` and are ignored by Git:

- `memory.sqlite3`: one append-only table of accepted inputs and results.
- `runs/<id>/`: captured input, accepted result and briefing, or a failure record.
- Each call subdirectory: complete prompt, input, schema, configuration, JSONL
  events, stderr, final response, duration and reported token usage.

One process may update a state directory at a time. New observations must arrive
in chronological order. Use a separate `--state` directory for alternative
strategies, backtests and experiments. Old successful runs remain replayable.
An unrelated or legacy SQLite database is rejected.

Each batch contains at most 50 articles, 20,000 characters per article and
120,000 characters overall. Matching sees every event observed within the recent
14-day window, with its latest evidence and distinct earlier quotes from that
window. Quotes retain source provenance and publication timestamps; `observed_on`
records the snapshot day, not the event date. Older observations expire even when
an event remains active. This is recent evidence, not complete lifetime history.

The complete article-plus-memory request is capped at 240,000 characters;
oversized requests stop before a model call and leave accepted state intact.
Events and source text are never silently removed to make a request fit. These
are bounded-workload limits, not a scalable retrieval architecture: busy windows
can exceed the cap before 14 days. Use isolated state for separate backtests.

The briefing identifies new and continuing events and reports how many quotes
differ from the previous observation. That is **textual change**, not a semantic
novelty judgment. Labels and continuity are model interpretations. Exact quotes
prove that text occurs in the captured source; they do not prove truth, relevance,
independent corroboration or the correctness of the label. The first version
does not generate confidence scores, source-agreement verdicts or PDFs.

## Tests and experiments

```sh
pytest -q
ruff check .
ruff format --check .
```

Ordinary tests are offline. They exercise real fake-CLI subprocesses, timeouts,
bad output, source validation, transactional memory, replay, feed parsing, the
CLI, and the independent evaluation scorer. CI runs the same checks without
Codex login or model access.

Live comparisons are explicit and run from the source checkout:

```sh
python -m evals.run --strategy single staged --repeats 2 \
  --max-calls 96 --max-seconds 1800 --timeout 120 \
  --output .news/experiments/comparison-01
```

The output directory must be new. The runner records source hashes, CLI/model
configuration, the corpus, each raw response, failures, timing and reported usage.
Rejected responses remain measurable; they cannot count as successful trials.
It never updates application memory. Exit status 1 means a failed trial or an
incomplete experiment, not lost artifacts. Budgets are ceilings, not guarantees
that a run will complete within account limits.

The [16-case corpus](evals/README.md) is explicitly synthetic and independently
labeled. Four additional longer holdout cases live in `evals/holdout.json`; run
them with `--cases evals/holdout.json`. Repetitions reveal variation on those cases.
They do not establish
general real-news quality. See [the recorded comparison](evals/RESULTS.md) for
the measured choice of default and remaining gaps.

For a new approach, create a Git worktree:

```sh
git worktree add -b experiments/my-approach ../News-my-approach from-scratch/main
```

Keep the corpus and model settings fixed and write a new task variant. Keep any
tuning data separate from later
holdout cases. Have another agent review failures and proposed changes before
merging the small changes that earned their place.
