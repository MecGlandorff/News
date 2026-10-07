# News

Capture news sources, follow ongoing stories through distinct developments, and
write a Markdown briefing with a dated, sourced timeline for each story.
AI processing uses **Codex exec, GPT-6 Astra, medium reasoning**. There is one
workflow, one accepted-run SQLite journal, and no service to deploy.

This rebuild is the **primary system under test**. Evaluations support specific
memory and identity improvements; overall story quality remains unproven.
Earlier implementations and research remain on their experiment branches;
see [measured results and remaining gaps](EVALUATION.md) and
[the experiment index](EXPERIMENTS.md). Use a fresh state directory: this
workflow does not import the old event database.

## Start

Use Python 3.12+ on macOS or Linux, SQLite with FTS5, and an authenticated Codex CLI.
The transport was exercised with Codex CLI 0.160.0. It validates strict isolation
settings; incompatible CLI versions fail visibly.

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
codex login status
news run --input examples/day1.json --state .news/story-demo
news run --input examples/day2.json --state .news/story-demo
```

The example articles are invented. Each `run` prints its run ID, story IDs and
the path to `briefing.md`. The briefing links to complete dated pages for the
stories it touches. Runs use your Codex account's model usage; authentication
files are not copied into the project. Each batch attempt starts at most two Codex CLI
invocations: a proposal and a separate story-coherence review. The application
does not retry. Codex may reconnect internally, as
recorded in its raw logs. An interrupted invocation may not report token usage.

Read a story offline, optionally as known on a particular capture day:

```sh
news story STORY_ID --state .news/story-demo
news story STORY_ID --state .news/story-demo --as-of 2026-10-01
```

`python -m news` exposes the same commands as `news`.

## Daily dogfooding

The daily runner collects available RSS versions, freezes a queue of small batches,
and calls the same story workflow with persistent memory:

```sh
.venv/bin/python -m news daily --state .news/dogfood
```

Open `.news/dogfood/latest.md` or `index.md`, and keep reader feedback in
`.news/dogfood/feedback.md`. Default limits are 8 articles per batch, 12 batch
attempts per invocation (at most 24 model calls), with a shared 360-second deadline
for each proposal and review. Failed or rejected batches stop the
queue; the next invocation resumes its oldest pending input. Accepted inputs are
recognized from the journal even after a code change, so a scheduling retry does
not repeat them. Experiments require separate state.

The [dogfooding guide](DOGFOOD.md) contains daily and weekly Codex routine prompts,
the selected schedule, source limitations and independent evaluation rules.
The prompts are prepared; scheduling still requires activation in the desktop app.
This command adds operational capture and reporting, not a new quality result.

## Capture sources

Edit `feeds.json`, then fetch a snapshot separately from model processing:

```sh
news fetch --day 2026-10-03 --max-per-feed 3 --output .news/articles-2026-10-03.json
news run --input .news/articles-2026-10-03.json
```

Choose the intended date. Fetching selects that publication day in the
Europe/Brussels timezone; feeds usually expose only recent items. It reads
RSS/Atom descriptions or embedded content, not article web pages. Namespace-aware
fields prevent media credits from replacing article descriptions. The report
counts invalid items, date exclusions, duplicates and configured-limit omissions.
A failed feed aborts capture. Existing snapshot files are never overwritten.

You can also supply captured source text directly:

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

IDs and URLs must be unique within a batch. Publication timestamps need a
timezone and cannot fall after the capture day. Older published articles are
allowed in supplied snapshots. Each article is assigned once, so a multi-event
digest cannot be assigned independently to several events. Prefer individual
source articles; the application does not split digests or create fragment provenance.

## Stories and evidence

A story is a named ongoing matter: for example, an incident and its investigation
or a particular court case. Separate developments have stable event identities
within the story. Repeated reporting of one occurrence keeps that event identity.
Sharing an actor or broad topic does not by itself establish continuity.

Attributed observations explain new developments, additional reporting,
corrections, disagreement or unclear change. Corrections and disagreements retain
the compared assertions and their source pointers. Unresolved questions remain
in their dated observations; later answers need their own sourced explanation.

**Observed on** means capture date, not occurrence date. Publication times and
source-stated event dates stay separate. A captured version is identified by its
complete article and capture day, preserving revised text and reused IDs or URLs.

Evidence identifies the exact `title` or `text` field; old references without a
field remain body-text references. Headlines are attributed source claims, not
independent corroboration. Citations label the field and retain publication and
observation dates.

Schema, coverage, exact-quote and reference checks run before acceptance. A
separate model call then checks whether the proposed events belong to the same
source-supported matter. For reused stories it receives every accepted event and
original source, including history omitted from the proposal's retrieval context.
Any unsupported, uncertain, incomplete or failed review rejects the whole batch
before journal insertion. Both outputs remain available for diagnosis.

This is an automatic semantic check, not a guarantee of factual accuracy or
correct grouping. It checks stories touched by the proposal, not the entire old
archive, and does not repair old accepted assignments. Reader feedback should
lead to general mechanisms and frozen regression tests; never manually patch
story assignments, the journal or generated briefings.

## State and limits

The default state directory is `.news/`. It contains:

- `journal.sqlite3`: accepted inputs and decisions, plus a disposable FTS5 index
  of full captured source text and generated story/event titles. Only a journal
  row establishes acceptance.
- `runs/<id>/`: `input.json`, retrieval diagnostics, raw decision, materialized
  result, `briefing.md`, and `stories/<id>.md` as known at that run.
- `runs/<id>/model/` and `review/`: each call's exact prompt, schema, configuration,
  raw output, diagnostics, timing and reported usage. `review-input.json` and
  `review.json` retain the semantic check. Failed attempts retain `failure.json`.

New batches must be chronological; one process may update a state directory at
a time. Validation completes before the acceptance transaction; inserting the
accepted run and rendering its outputs occur inside that transaction.
Failed artifacts may exist without an accepted journal row. An identical snapshot,
code, task and retrieval configuration reuses its accepted result without another
model call and restores that run's original dated view. Code/task changes alter
this reuse key; use separate state for comparisons. No database migration occurs.

Retrieval has no age cutoff. It rebuilds and compacts the index from the journal
before each run, excludes future captures, and uses up to 64 lexical terms per
article. By default it selects three matches plus recent versions of the same
URL. A selected story supplies its origin, latest observation, relevant history,
corrections, disagreements and recorded unresolved questions. Diagnostics expose
selection and omissions. Lexical search can miss weakly named links or paraphrases.
Generated titles add search vocabulary but are not captured evidence. A wrong
title can retrieve unrelated material; quote validation does not prove relevance.

Hard input limits are 50 articles per batch, 20,000 characters per article and
120,000 characters per snapshot. The compact canonical retained JSON payload is
limited to 180,000 characters by default; `--max-context-chars` permits at most
240,000. This count excludes the fixed task/schema and serialization whitespace.
`--hits-per-article` accepts 1–10. The same cap applies separately to the full
review payload, including the proposed decision. Oversized context stops before
that call; the proposal may already have incurred usage. Histories are never
silently trimmed to fit. One long story can exceed the review cap even in a
single-article batch; smaller batches cannot always unblock it. Start with small batches
and inspect the saved diagnostics; an article-count limit alone cannot guarantee
that a busy story's history fits.

The default shared proposal/review deadline is 180 seconds (`--timeout`, 1–1800).
The daily command defaults to 360 seconds per batch. Large batches have
timed out in experiments. Timeouts and interruptions stop the subprocess group;
the program neither retries nor splits a failed batch automatically.

Full journal projection and index rebuilding remain a bounded-workload design.
The simulated 17,478-capture storage probe measured a median 2.47 seconds for the
earlier compaction prototype, but its 50-article request exceeded the context
cap; one fixed 10-article query fit. Those synthetic identity assignments measure
storage/retrieval cost, not story quality or a general capacity guarantee.

## Development

```sh
python -m pip install -r requirements-dev.txt
pytest -q
ruff check .
ruff format --check .
```

Ordinary tests are offline. They exercise fake-CLI subprocesses, timeouts,
feed/input validation, story identity, provenance, corrections and disagreement,
dated rendering, retrieval and transaction failures. CI runs the same checks.
Live research runners, frozen corpora and failed outputs are preserved separately
in [the experiment index](EXPERIMENTS.md); they are not alternative product paths.
