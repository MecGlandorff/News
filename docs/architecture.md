# Architecture

This project turns RSS articles into local story memory and publishes daily intelligence briefings.

For a step-by-step runtime walkthrough, read [how-it-works.md](how-it-works.md).
For practical SQLite inspection queries, read [database-guide.md](database-guide.md).

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
  -> src/sources.py       seed source metadata and attach source_id where possible
  -> src/scraper.py       fetch feeds, normalize URLs, filter dates, deduplicate URLs
  -> src/classifier.py    classify theme, story label, and importance
  -> src/tracker.py       consolidate labels, match recent stories, write story memory
  -> src/story_matching.py optionally verify candidate story matches with full article text
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

When `--verify-story-matches` is enabled, the tracker verifies candidate cross-day matches before it reuses an existing story ID. The verifier uses `gpt-5.4-nano`, the current article title, RSS description, normalized article date, full article text when available, and compact recent story memory. If full text is missing, the tracker fetches it only for candidate matches. Accepted matches require structured same-event evidence; adjacent, broad-context, uncertain, malformed, or weak decisions become new stories instead of corrupting existing memory.

Second, the tracker writes a daily observation for each story. This observation records the label seen today, source count, article count, average importance, and later the generated summary and `delta_summary`. The next run can use that saved memory to answer: what changed since the last observation?

The key tables are:

- `stories`: one row per ongoing story arc.
- `story_daily`: daily aggregate counts for each story.
- `story_observations`: the memory layer used for summaries and deltas.
- `articles`: fetched articles linked to stories for the run date.
- `article_story_links`: junction rows from article to story observation.
- `story_match_decisions`: optional verifier audit rows for accepted and rejected candidate story matches.

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

When `--show-evidence` is enabled, scraping fetches full article text and claim extraction uses title, RSS description, and full article text when available. If body extraction fails or a source blocks scraping, the claim extractor falls back to title and RSS description. The claim model is `gpt-5.4-nano`; classification remains on RSS title/description with `gpt-5.4-mini`.

Evidence-mode briefings also receive a deterministic `claim_source_agreement` summary. The current first pass is deliberately narrow: exact repeated non-background claims across distinct source identities can back `partial` or `broad`, and comparable numeric claims with different values can force `mixed` plus `possible conflict`. This uses saved claims and source identity only; it does not infer independent corroboration or confirmed contradiction.

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

When evidence-mode claim comparison produces a source-agreement label, `src/briefing_generation.py` overrides the model's `source_agreement` with the deterministic label. Numeric divergence also overrides `dispute_flag` to `possible conflict`.

The PDF output uses the same briefing package. `src/newspaper.py` is a renderer, not a separate intelligence pipeline.

## What Is Weak Or Missing Today

The core story-memory flow exists, but several trust and observability layers are still incomplete.

- Source metadata is seeded into a `sources` table, and new article rows can store `source_id` alongside the source name. Deterministic source support uses `source_id` first and falls back to source names for older rows.
- Evidence-mode source agreement is claim-backed for exact repeated claims and conservative numeric divergence, but it is not a general agreement model and does not infer independent source corroboration.
- Run observability stores `runs` and real model calls in `llm_calls`, exact response reuse in `llm_response_cache`, and `--pipeline-report` reports scraper counts, claim metrics, token use, latency, cache hits, retries, schema failures, story-match verifier counts, and estimated EUR cost.
- There is no stored novelty score yet; novelty needs a clear claim-backed definition before becoming schema.
- Source-divergence notes currently cover numeric divergence only; date, status, and attribution comparison are still missing. A dedicated contradiction module/table is no longer Phase 3 scope.
- Full-text claim extraction is enabled for evidence runs, but its cost and quality impact still need review against run telemetry.
- Story-match verifier decisions are stored for audit, exact verifier responses can be cached for identical prompts, and verifier behavior still needs evaluation against a curated fixture set.

These gaps matter because the project aims to produce auditable intelligence artifacts, not just summaries.

## What Should Happen Next

The next architecture work is closing out Phase 3 by making source metadata and observability load-bearing rather than just present.

The next source-model step should review the first claim-backed agreement slice on real evidence runs and then decide whether to compare dates, statuses, and attributions.

The next observability refinement should compare the quality impact of full-text `gpt-5.4-nano` claim extraction against its measured token and latency cost.

The next story-matching refinement should build a small reviewed fixture set from recent generated newspapers. It should include true continuations and false merges, including the 2026-05-07 Gaza detention/flotilla failure, before the verifier is enabled by default.

Only after that should the project expand expensive evidence behavior further, such as broader claim comparison for non-numeric source-divergence notes.

## Why This Order Matters

Source metadata should come before claim-backed source agreement because the system needs to know what kind of sources are agreeing. Five syndicated copies of one wire article should not count the same as five independent sources.

Observability should guide broader evidence behavior because full text increases token use and latency. The system should measure the cost and quality of evidence runs before making that path common.

Claim comparison should come before source-divergence prose because divergence notes need structured backing. A briefing label like `possible conflict` is useful, but it is not enough for auditability unless the system can point to the claims that differ. The current numeric first pass follows that rule but does not yet cover dates, statuses, or attributions.

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

### `story_match_decisions`

Audit rows written when `--verify-story-matches` checks candidate cross-day matches.

```sql
decision_id          INTEGER PRIMARY KEY AUTOINCREMENT
run_id               INTEGER
run_date             TEXT NOT NULL
today_label          TEXT NOT NULL
candidate_label      TEXT NOT NULL
candidate_story_id   INTEGER
accepted             INTEGER NOT NULL
same_event           INTEGER NOT NULL
relationship         TEXT NOT NULL
confidence           TEXT
article_dates        TEXT
candidate_last_seen  TEXT
continuity_evidence  TEXT
reject_reason        TEXT
verifier_model       TEXT
prompt_version       TEXT NOT NULL
created_at           TEXT DEFAULT CURRENT_TIMESTAMP
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
story_match_verifications INTEGER
story_match_accepts INTEGER
story_match_rejections INTEGER
duplicate_url_skips INTEGER
feed_fetch_failures INTEGER
article_text_fetch_successes INTEGER
article_text_fetch_failures INTEGER
claim_articles_extracted INTEGER
claim_articles_cached INTEGER
claim_invalid_dropped INTEGER
claim_extraction_failures INTEGER
claim_zero_results INTEGER
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

### `llm_response_cache`

Exact response cache for same-day matching, cross-day matching, optional story-match verification, and briefing generation. The cache key is the full request shape, not a semantic similarity key.

```sql
cache_id         INTEGER PRIMARY KEY AUTOINCREMENT
purpose          TEXT NOT NULL
model            TEXT NOT NULL
prompt_version   TEXT NOT NULL
request_hash     TEXT NOT NULL
request_json     TEXT NOT NULL
response_content TEXT NOT NULL
hit_count        INTEGER NOT NULL DEFAULT 0
created_at       TEXT DEFAULT CURRENT_TIMESTAMP
last_used_at     TEXT
UNIQUE (purpose, model, prompt_version, request_hash)
```

## LLM Call Reference

| Stage | Model | Output | Cached |
|---|---|---|---|
| Classification | `gpt-5.4-mini` | theme, story label, importance | Yes |
| Claim extraction | `gpt-5.4-nano` | structured claims | Yes |
| Same-day consolidation | `gpt-5.5` | label groups | Exact response cache |
| Cross-day matching | `gpt-5.5` | label matches | Exact response cache |
| Story-match verification | `gpt-5.4-nano` | continuity decisions | Exact response cache |
| Briefing generation | `gpt-5.5` | story-card fields and prose | Exact response cache |

All LLM stages should return JSON objects and pass through `parse_json_object()` before downstream code uses the response.
Fresh calls go through the observed chat helper in `src.llm`, which records token and latency metadata when a run context is active.

## Output Reference

| Path | Purpose | Git status |
|---|---|---|
| `briefings/` | Public Markdown briefing archive | Committed unless left as local generated output |
| `newspapers/` | Newspaper-style PDFs | Ignored by default |
| `output/` | Local digest Markdown | Ignored |
| `data/stories.db` | Local SQLite database | Ignored |
| `data/daily/` | Daily article snapshots | Ignored |
| `run_artifacts/` | Markdown run reports from observability rows | Ignored |
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

The next version should make that trace more inspectable by reviewing evidence-mode claim-backed agreement on real cases and expanding source-divergence comparison beyond numeric claims when it can stay precise.

See `docs/failure-modes.md`, `docs/model-behavior.md`, and `docs/adr/` for related tradeoffs.
