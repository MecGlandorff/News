# Architecture

This project turns RSS articles into local story memory and publishes daily intelligence briefings.

The important design choice is simple:

```text
Track stories, not articles.
```

Articles are the input. Story arcs are the memory layer. Briefings are the final artifact.

## What The System Does Today

The current pipeline fetches RSS items, classifies them, links them to continuing stories, extracts source-grounded claims when requested, and writes Markdown plus PDF outputs.

The main path is:

```text
Source
  -> Article
  -> Claim
  -> Story Arc
  -> Story Delta
  -> Briefing
```

In code, the run looks like this:

```text
Configured RSS feeds
  -> src/scraper.py       fetch feeds, normalize URLs, filter dates, deduplicate URLs
  -> src/classifier.py    classify theme, story label, and importance
  -> src/tracker.py       consolidate labels, match recent stories, write story memory
  -> src/claims.py        optionally extract claims and evidence spans
  -> src/top10.py         select stories and generate briefing cards
  -> src/digest.py        write a lightweight local digest
  -> src/newspaper.py     render a newspaper-style PDF
```

`src/tracker.py` and `src/top10.py` are orchestration modules. The more specific logic lives in smaller modules: `src/story_matching.py` handles same-day and cross-day label matching, `src/briefing_selection.py` handles story scoring and section selection, and `src/briefing_generation.py` handles briefing model input, structured output normalization, and fallbacks.

The local database is SQLite at `data/stories.db`. Runtime snapshots live under `data/daily/`. Public artifacts are written to `briefings/` and `newspapers/`.

## How Story Memory Works

Story memory is built in two layers.

First, `src/tracker.py` groups today's classified articles by story label. It asks the tracking model to consolidate same-day label variants, then asks whether today's labels continue recent canonical stories. The tracker is conservative about generic incident labels such as crashes, shootings, lawsuits, and attacks because false merges corrupt memory more severely than false splits.

Second, the tracker writes a daily observation for each story. This observation records the label seen today, source count, article count, average importance, and later the generated summary and `delta_summary`. The next run can use that saved memory to answer: what changed since the last observation?

The key tables are:

- `stories`: one row per ongoing story arc.
- `story_daily`: daily aggregate counts for each story.
- `story_observations`: the memory layer used for summaries and deltas.
- `articles`: fetched articles linked to stories for the run date.
- `article_story_links`: junction rows from article to story observation.

## How Source Grounding Works

Claim extraction is optional and enabled with `--show-evidence`.

When enabled, `src/claims.py` extracts structured claims from each tracked article. Each claim includes:

- `claim_text`
- `claim_type`
- `entities`
- `evidence_span`
- `confidence`

The claim layer validates model output before storage. A claim is saved only when its type is allowed, confidence is numeric and bounded, entities are strings, and the evidence span appears in the input sent to the model.

The `claims` and `claim_extractions` tables are created lazily by `src/claims.py`. A local database produced by runs without `--show-evidence` can have story, article, and classification tables without claim tables.

Current claim input is RSS title plus description. The scraper can fetch full article text with `--fetch-article-text`, but claim extraction does not yet consume that body text. This is intentional for now: broad full-text claim extraction should wait until cost and latency observability exists.

## How Briefings Are Built

`src/top10.py` aggregates tracked articles by canonical story and selects briefing-worthy stories. It prioritizes importance, source count, and movement signal while filtering out low-value sports, entertainment, and weak low-interest stories.

For selected stories, the briefing model returns structured story-card fields:

- `status`
- `confidence`
- `source_agreement`
- `dispute_flag`
- `delta_summary`
- `briefing`
- `open_questions`

The final Markdown renders those fields with source links, reported timestamps, and optional evidence spans. The generated summary and delta are written back to `story_observations`, so future runs can compare against previous context.

The PDF output uses the same briefing package. `src/newspaper.py` is a renderer, not a separate intelligence pipeline.

## What Is Weak Or Missing Today

The core story-memory flow exists, but several trust and observability layers are still incomplete.

- Source metadata is seeded into a `sources` table, and new article rows can store `source_id` alongside the source name. Source metadata is not yet used by source agreement logic.
- Source agreement is currently a briefing-level model label, not a claim-comparison result backed by a dedicated data model.
- Run observability stores `runs` and real model calls in `llm_calls`, and `--pipeline-report` reports token use, latency, cache hits, retries, and schema failures. EUR cost estimates are not implemented yet.
- There is no stored novelty score yet; novelty needs a clear claim-backed definition before becoming schema.
- Contradiction detection is not implemented.
- Full article text can be fetched, but claim extraction still uses RSS title and description.

These gaps matter because the project aims to produce auditable intelligence artifacts, not just summaries.

## What Should Happen Next

The next architecture work is closing out Phase 3 by making source metadata and observability load-bearing rather than just present.

The next source-model step should make source agreement consume `articles.source_id` where available and fall back to source names for older rows. Until then, the table does not affect story selection or briefing output.

The next observability refinement should expose scraper duplicate/failure counts and add cost estimates once model pricing is maintained somewhere explicit. The current report already covers article count, claim count, story count, model calls, cache hits, schema failures, token totals, and total latency.

Only after that should the project expand expensive evidence behavior, such as selective full-text claim extraction for lead stories or contradiction detection across claim sets.

## Why This Order Matters

Source metadata should come before source agreement because the system needs to know what kind of sources are agreeing. Five syndicated copies of one wire article should not count the same as five independent sources.

Observability should come before broader full-text claim extraction because full text increases token use and latency. The system should measure the cost before making a more expensive path common.

Claim comparison should come before contradiction prose because contradictions need durable records. A briefing label like `possible conflict` is useful, but it is not enough for auditability unless the system can point to the conflicting claims.

## Data Model Reference

### `sources`

Configured RSS source metadata. This is seeded from `src/scraper.py`; new article writes store `source_id` when a matching source row exists.

```sql
source_id   INTEGER PRIMARY KEY AUTOINCREMENT
name        TEXT NOT NULL UNIQUE
rss_url     TEXT NOT NULL
language    TEXT NOT NULL
type        TEXT NOT NULL
reliability TEXT NOT NULL DEFAULT 'unknown'
bias_notes  TEXT NOT NULL DEFAULT ''
created_at  TEXT DEFAULT CURRENT_TIMESTAMP
updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
```

### `stories`

Master record for each ongoing story.

```sql
story_id        INTEGER PRIMARY KEY AUTOINCREMENT
canonical_label TEXT NOT NULL
theme           TEXT
first_seen      DATE NOT NULL
last_seen       DATE NOT NULL
```

### `story_daily`

Daily aggregate metrics per story.

```sql
story_id        INTEGER NOT NULL
date            DATE NOT NULL
source_count    INTEGER
importance_avg  REAL
labels_seen     TEXT
PRIMARY KEY (story_id, date)
```

### `story_observations`

Daily story memory. This is where summaries and deltas are stored for future runs.

```sql
observation_id  INTEGER PRIMARY KEY AUTOINCREMENT
story_id        INTEGER NOT NULL
date            DATE NOT NULL
label_seen      TEXT
source_count    INTEGER
article_count   INTEGER
importance_avg  REAL
summary         TEXT
delta_summary   TEXT
created_at      TEXT DEFAULT CURRENT_TIMESTAMP
UNIQUE (story_id, date)
```

### `articles`

Fetched article records linked to a story.

```sql
id              TEXT
story_id        INTEGER
date            DATE
source_id       INTEGER
source          TEXT
title           TEXT
description     TEXT
url             TEXT
published_at    TEXT
importance      INTEGER
```

### `article_story_links`

Junction table from article to story observation.

```sql
article_id      TEXT NOT NULL
story_id        INTEGER NOT NULL
observation_id  INTEGER
relevance       REAL
PRIMARY KEY (article_id, story_id, observation_id)
```

### `article_classifications`

Classification cache.

```sql
article_id        TEXT PRIMARY KEY
url               TEXT NOT NULL
title             TEXT
description       TEXT
content_hash      TEXT NOT NULL
theme             TEXT NOT NULL
story_label       TEXT NOT NULL
importance        INTEGER NOT NULL
classifier_model  TEXT NOT NULL
prompt_version    TEXT NOT NULL
classified_at     TEXT DEFAULT CURRENT_TIMESTAMP
```

### `claims`

Validated claim extraction results.

```sql
claim_id        INTEGER PRIMARY KEY AUTOINCREMENT
article_id      TEXT NOT NULL
story_id        INTEGER
claim_text      TEXT NOT NULL
claim_type      TEXT
entities        TEXT
evidence_span   TEXT
confidence      REAL
prompt_version  TEXT
created_at      TEXT DEFAULT CURRENT_TIMESTAMP
```

### `claim_extractions`

Claim extraction cache records, including zero-claim results.

```sql
article_id      TEXT NOT NULL
prompt_version  TEXT NOT NULL
story_id        INTEGER
content_hash    TEXT NOT NULL
claims_count    INTEGER NOT NULL
extracted_at    TEXT DEFAULT CURRENT_TIMESTAMP
PRIMARY KEY (article_id, prompt_version)
```

### `runs`

One row per pipeline execution.

```sql
run_id              INTEGER PRIMARY KEY AUTOINCREMENT
started_at          TEXT NOT NULL
finished_at         TEXT
run_date            TEXT
cli_args            TEXT NOT NULL
git_sha             TEXT
articles_returned   INTEGER
claims_saved        INTEGER
stories_touched     INTEGER
llm_calls_count     INTEGER
llm_errors_count    INTEGER
llm_cache_hits      INTEGER
schema_failures     INTEGER
retry_count         INTEGER
prompt_tokens       INTEGER
completion_tokens   INTEGER
total_latency_ms    INTEGER
status              TEXT NOT NULL
error_message       TEXT
```

### `llm_calls`

Real model calls only. Cache hits are counted on `runs`, not inserted here.

```sql
call_id             INTEGER PRIMARY KEY AUTOINCREMENT
run_id              INTEGER NOT NULL
model               TEXT NOT NULL
purpose             TEXT NOT NULL
prompt_version      TEXT
latency_ms          INTEGER
prompt_tokens       INTEGER
completion_tokens   INTEGER
schema_failure      INTEGER NOT NULL
retry_count         INTEGER NOT NULL
error_type          TEXT
error_message       TEXT
created_at          TEXT NOT NULL
```

## LLM Call Reference

| Stage | Model | Output | Cached |
|---|---|---|---|
| Classification | `gpt-5.4-mini` | theme, story label, importance | Yes |
| Claim extraction | `gpt-5.4-mini` | structured claims | Yes |
| Same-day consolidation | `gpt-5.5` | label groups | No |
| Cross-day matching | `gpt-5.5` | label matches | No |
| Briefing generation | `gpt-5.5` | story-card fields and prose | No |

All LLM stages should return JSON objects and pass through `parse_json_object()` before downstream code uses the response.
Fresh calls go through the observed chat helper in `src.llm`, which records token and latency metadata when a run context is active.

## Output Reference

| Path | Purpose | Git status |
|---|---|---|
| `briefings/` | Public Markdown briefings | Committed |
| `newspapers/` | Public newspaper PDFs | Committed |
| `output/` | Local digest Markdown | Ignored |
| `data/stories.db` | Local SQLite database | Ignored |
| `data/daily/` | Daily article snapshots | Ignored |
| `logs/` | Scheduler logs | Ignored |

## What Done Looks Like

The architecture is doing its job when a reviewer can trace one story from source material to final output:

```text
RSS source
  -> normalized article
  -> validated claim and evidence span
  -> story arc
  -> daily observation
  -> delta summary
  -> briefing section
```

The next version should make that trace more inspectable by adding source metadata, run observability, and claim-backed agreement or contradiction records.

See `docs/failure-modes.md`, `docs/model-behavior.md`, and `docs/adr/` for related tradeoffs.
