# News

A small local news system: capture articles, group concrete events, remember
continuing events, and write a Markdown briefing with exact source quotations.
The AI work runs through **Codex CLI, GPT-6 Astra, medium reasoning**. There is no
OpenAI SDK integration or service to deploy.

This is the `from-scratch/main` rebuild. The previous implementation remains in
Git history and the original checkout. This version uses a new database; it does
not import the old database or reproduce every old feature.

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
120,000 characters overall. Matching sees the last observation of up to 30 events
observed within 14 days. The complete article-plus-memory request is capped at
240,000 characters; oversized requests stop before a model call. Source text is
never silently truncated to fit. These are small-workload limits, not a scalable
retrieval architecture.

The briefing identifies new and continuing events and shows which quoted text
differs from the previous observation. That is **textual change**, not a semantic
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
labeled. Repetitions reveal variation on those cases. They do not establish
general real-news quality. See [the recorded comparison](evals/RESULTS.md) for
the measured choice of default and remaining gaps.

For a new approach, create a Git worktree, keep the corpus and model settings
fixed, and write a new task variant. Keep any tuning data separate from later
holdout cases. Have another agent review failures and proposed changes before
merging the small changes that earned their place.
