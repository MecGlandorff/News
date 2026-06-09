# How The Project Works

This document is a code-path audit of the current pipeline. It explains what happens when you run `python -m src.run`, which files own each stage, which database tables are touched, where LLMs are called, and where the important trust boundaries are.

The project is not a generic article summarizer. It builds local memory of real-world news events.

```text
Source -> Article -> Claim -> Story Arc -> Story Delta -> Briefing
```

## In A Nutshell

One run answers a practical question: what changed in the news today, and what source-backed story memory should be updated?

This view is for non-technical readers. It shows the product behavior before the code-level path.

```mermaid
flowchart TD
    A[Start today's run] --> B[Read configured news sources]
    B --> C[Collect today's articles]
    C --> D[Save source names and article links]
    D --> E[Clean URLs and remove duplicates]
    E --> F[Fetch full article text when needed]
    F --> G[Classify what each article is about]
    G --> H[Group related articles into likely news events]
    H --> I[Compare events with recent story memory]

    I --> J{Looks like a continuing event?}
    J -- yes --> K[Update the existing story arc]
    J -- no --> L[Create a new story arc]

    K --> M[Record today's observations]
    L --> M
    M --> N[Work out what changed since the previous run]

    N --> O{Evidence mode on?}
    O -- no --> P[Keep article links and source signals]
    O -- yes --> Q[Extract specific claims from the article text]
    Q --> R[Require each claim to point to evidence text]
    R --> S[Drop claims that are not supported by their evidence]
    S --> T[Compare claim support across sources]
    T --> U[Flag repeated, divergent, or unresolved claims]

    P --> V[Choose the most useful stories for the briefing]
    U --> V
    V --> W[Build an auditable briefing]
    W --> X[Show status, confidence, source agreement, open questions, links, and evidence]
    X --> Y[Write Markdown briefing and newspaper PDF]
    Y --> Z[Record run totals for review]
    Z --> AA[Show pipeline report when requested]
```

## One Run At A Glance

`src/run.py` is the entrypoint. `main()` parses CLI flags, starts an observability run, executes the pipeline, writes outputs, finishes the run, and optionally prints `--pipeline-report`.

```mermaid
flowchart TD
    A[python -m src.run] --> B[start_run in src/observability.py]
    B --> C[seed sources in src/sources.py]
    C --> D[scrape RSS feeds in src/scraper.py]
    D --> E[classify articles in src/classifier.py]
    E --> F[track stories in src/tracker.py]
    F --> G{"--show-evidence?"}
    G -- yes --> H[extract claims in src/claims.py]
    G -- no --> I[skip claim extraction]
    H --> J[build briefing package in src/top10.py]
    I --> J
    J --> K[write digest Markdown]
    J --> L[write briefing Markdown]
    J --> M[write newspaper PDF]
    K --> N[finish_run and aggregate LLM totals]
    L --> N
    M --> N
    N --> O{"--pipeline-report?"}
    O -- yes --> P[print run totals]
    O -- no --> Q[end]
```

The main orchestration is intentionally boring:

1. `seed_source_metadata()`
2. `scrape_articles()`
3. `classify_scraped_articles()`
4. `track_stories()`
5. `maybe_extract_claims()`
6. `write_pipeline_outputs()`

That sequence is the spine of the system.

## Stage 1: Sources And RSS Ingestion

Owned by:

- `src/run.py`
- `src/sources.py`
- `src/scraper.py`

Each run first calls `sources.seed_sources()`. This seeds the configured RSS feeds from `src/scraper.py` into the `sources` table. Seeding is idempotent and preserves manually editable metadata such as reliability and bias notes.

Then `scraper.scrape_all()` fetches feed items. For each source it:

- fetches the RSS feed with retry-enabled `requests`
- parses title, link, description, and `pubDate`
- filters by `--date` / `--today` when supplied; `--include-undated` keeps feed items with missing or unparseable timestamps in that date-filtered batch
- normalizes URLs by removing tracking parameters
- deduplicates exact normalized URL repeats
- creates a stable article ID from the normalized URL hash
- optionally fetches full article text with `--fetch-article-text` or `--show-evidence`

The article object passed downstream contains:

```text
id, source, language, title, description, url, published_at, text
```

Important boundary:

- RSS title and description are always available inputs when the feed provides them.
- Full article text is optional and may be empty because extraction can fail, a source can block scraping, or a page may not expose a usable `<article>` or `<main>` body.
- Claim extraction uses full article text when `--show-evidence` is enabled and body extraction succeeds.
- Full article text is also used by the default-on story-match verifier for candidate matches.

## Stage 2: Classification

Owned by:

- `src/classifier.py`
- `src/article_cache.py`
- `src/config.py`
- `src/llm.py`

Classification assigns each article:

```text
theme, story_label, importance
```

The classifier uses `gpt-5.4-mini` by default. It asks for structured JSON and parses with `parse_json_object()`.

Before calling the model, `article_cache.get_cached_classifications()` checks `article_classifications` by:

```text
article_id + classifier_model + prompt_version + content_hash
```

The content hash is built from RSS title and description. If the article content changed, the cache is ignored and the article is reclassified.

Trust boundary:

- The classifier decides grouping labels and importance, not facts.
- It does not produce claims.
- It does not write final briefing prose.
- Cache hits are counted on the current `runs` row, but they are not inserted into `llm_calls`.

## Stage 3: Story Tracking

Owned by:

- `src/tracker.py`
- `src/story_matching.py`
- `src/config.py`

Tracking turns classified articles into local story memory.

```mermaid
flowchart TD
    A[classified articles] --> B[write data/daily/YYYY-MM-DD/articles.json]
    B --> C[group by story_label]
    C --> D[consolidate same-day labels]
    D --> E[load recent stories from lookback window]
    E --> F[match today's labels to recent canonical stories]
    F --> G{"verifier enabled?"}
    G -- no --> H[persist story assignments]
    G -- yes --> I[ensure full article text for candidates]
    I --> J[verify candidate continuity with gpt-5.4-nano]
    J --> H
    H --> K[stories]
    H --> L[story_daily]
    H --> M[story_observations]
    H --> N[articles]
    H --> O[article_story_links]
    J --> P[story_match_decisions]
```

The tracker first saves the classified article snapshot under `data/daily/<date>/articles.json`. Then it groups today's articles by `story_label` and asks the tracker model to consolidate same-day label variants. This reduces duplicate arcs such as two labels for the same election result or diplomatic meeting.

Next it loads recent story options from SQLite. The lookback window comes from `DEFAULT_LOOKBACK_DAYS`. Recent options include:

- `story_id`
- canonical label
- last seen date
- previous summary
- previous delta summary
- a few recent article titles

The cross-day matcher decides whether today's labels continue recent canonical stories or should become new stories.

### Default Story-Match Verification

Story-match verification is enabled by default. It adds a second check before a candidate match can reuse old memory. Use `--no-verify-story-matches` only for comparison runs against the older label-only match path.

The verifier receives:

- today's article title and RSS description
- today's article date
- full article text when available
- compact recent story memory
- candidate story label and `story_id`

It returns structured fields:

```text
same_event, relationship, confidence, article_dates,
candidate_last_seen, continuity_evidence, reject_reason
```

Only `same_event`, `same_story_arc`, or `direct_follow_up` decisions with enough confidence and continuity evidence are accepted. `adjacent_topic`, `broader_context`, `uncertain`, malformed, or weak decisions default to a new story.

The verifier exists because broad topical similarity can corrupt memory. A real motivating failure was the 2026-05-07 case where an article about alleged abuse of Palestinian detainees in Israeli detention was attached to the existing `Gaza flotilla raid` story. The correct behavior is to treat that as adjacent Gaza/Israel detention context unless there is concrete continuity evidence tying it to the flotilla event.

Audit trail:

- every verifier decision is stored in `story_match_decisions`
- run totals include accepted and rejected match checks
- exact verifier model responses can be reused for identical prompts through `llm_response_cache`, but stored decision rows are audit records, not a semantic match cache

## Stage 4: Claims And Evidence

Owned by:

- `src/claims.py`
- `src/briefing_generation.py`

Claims are optional and enabled with:

```bash
python -m src.run --show-evidence
```

For each tracked article, `claims.extract_and_save_claims()` builds the extraction input from title, RSS description, and fetched full article text when available:

```text
title

description

full article text
```

It then checks `claim_extractions` by:

```text
article_id + prompt_version + content_hash
```

If the cache is valid, the model call is skipped and the current story ID is updated if tracking changed. Zero-claim outputs are cached too.

If the article is not cached, the claim extractor asks the model for:

```text
claim_text, claim_type, entities, evidence_span, confidence
```

Allowed claim types are:

```text
fact, number, quote, prediction, allegation, background
```

Validation is strict. A claim is dropped unless:

- `claim_text` is non-empty
- `claim_type` is allowed
- `entities` is a list of non-empty strings
- `confidence` is numeric and in `[0.0, 1.0]`
- `evidence_span` is non-empty
- `evidence_span` appears in the extraction input
- `claim_text` is *derivable* from `evidence_span` under the hybrid gate below

### Derivability Gate

Span containment is necessary but not sufficient: a model could pair any article sentence with any claim and pass substring validation. The derivability gate in `_derivability_check()` and `_classify_claim()` decides whether the span actually supports the claim. See [docs/adr/0013-claim-evidence-derivability.md](adr/0013-claim-evidence-derivability.md).

1. **Deterministic reject** — if any number in `claim_text` (integer, decimal, percentage, comma-separated, normalized by stripping commas) does not appear in `evidence_span`, drop the claim immediately. No LLM call.
2. **Deterministic accept** — if `claim_text` (normalized) is contained in `evidence_span`, or if entity overlap is backed by enough non-entity lexical overlap, accept immediately ("cheap_accept").
3. **LLM verifier** — for the ambiguous middle, including weak entity-only or anaphoric spans, call `gpt-5.4-nano` with `CLAIMS_VERIFIER_PROMPT_VERSION = "2026-05-14-v1"` through `create_cached_chat_completion`, asking whether the span supports the claim. Verifier failures (network, parse, unexpected payload) default to reject.

The verifier runs **outside** the SQLite transaction so its network call does not hold a write lock. Run totals expose `claim_derivable_accepts`, `claim_verifier_calls`, `claim_verifier_accepts`, and `claim_verifier_rejects`.

```mermaid
flowchart TD
    A[tracked article] --> B[build title + description + optional full-text input]
    B --> C[hash input]
    C --> D{cached extraction?}
    D -- yes --> E[increment cache hits]
    D -- no --> F[call claim model]
    F --> G[parse JSON]
    G --> H[validate fields]
    H --> I{evidence span in input?}
    I -- no --> K[drop claim]
    I -- yes --> M{number in claim missing from span?}
    M -- yes --> K
    M -- no --> N{verbatim or strong entity overlap?}
    N -- yes --> J[save claim: cheap_accept]
    N -- no --> O[gpt-5.4-nano verifier]
    O -- supported --> J2[save claim: verifier_accept]
    O -- not supported / error --> K
    J --> L[save claim_extractions row]
    J2 --> L
    K --> L
```

Important boundary:

- Claim extraction is extraction, not interpretation.
- Evidence-mode source agreement uses saved claims only for a narrow deterministic comparison step: exact repeated non-background claims and comparable numeric divergence.
- The claims table does not prove truth, source independence, or confirmed contradiction.
- Full text can be empty when scraping fails; in that case the claim extractor falls back to title and RSS description.

## Stage 5: Briefing Package And Outputs

Owned by:

- `src/briefing_selection.py`
- `src/briefing_generation.py`
- `src/top10.py`
- `src/digest.py`
- `src/rendering/newspaper.py`

`run_pipeline()` writes three possible artifacts:

- digest Markdown in `output/`
- briefing Markdown in `briefings/`
- newspaper PDF in `newspapers/`

The important detail is that `src/top10.py` builds one briefing package and reuses it for Markdown and PDF output. This prevents the PDF from becoming a separate intelligence pipeline.

Story selection works like this:

- aggregate tracked articles by canonical story
- compute source count, average importance, themes, trend, previous context, and observation IDs
- score by importance, source count, and movement
- select lead stories plus politics/economy/other sections
- exclude low-value categories from lead placement when appropriate

Briefing generation uses one batched model call for displayed stories. The model returns structured story-card fields:

```text
status, confidence, source_agreement, dispute_flag,
delta_summary, briefing, open_questions
```

The allowed labels are normalized and defaults are supplied when the model omits or malforms a field. If a displayed story comes back without briefing text, the system retries missing stories and then falls back to deterministic text if needed.

When evidence mode is enabled, saved claims are also summarized before the briefing call. The first claim-backed source-agreement pass is deterministic and narrow:

- exact repeated non-background claims across distinct source identities can move agreement to `partial` or `broad`
- multiple claim-bearing source identities without exact repeats stay conservative at `partial`
- numeric claims with otherwise similar wording but different numbers create lightweight source-divergence notes and force `mixed`
- claim-backed labels override the model's briefing-level `source_agreement`; numeric divergence forces `possible conflict`
- this adds no new LLM call and no new database table

After briefing generation, `save_observation_memory()` writes the generated summary and `delta_summary` back to `story_observations`. That is what lets the next run compare today's reporting against previous context.

Trust boundary:

- The briefing is the final prose layer.
- It may synthesize across articles and claims, but it should not invent unsupported facts.
- Without evidence mode, `source_agreement` and `dispute_flag` remain briefing-level signals backed by source identity and prompt constraints.
- With evidence mode, the deterministic claim-backed summary can override these labels when comparable saved claims exist.

## Stage 6: Observability

Owned by:

- `src/observability.py`
- `src/llm.py`
- model-calling modules

`main()` starts a run before the pipeline begins:

```text
runs.status = running
```

Every real LLM call records one `llm_calls` row when a current run ID exists. Cache hits update the `runs` row instead of inserting fake call rows. Cache hits can come from article classification, claim extraction, or exact LLM response reuse for matching and briefing calls.

At the end, `finish_run()` aggregates LLM rows into the run:

- call count
- error count
- schema failures
- retries
- prompt tokens
- completion tokens
- total latency
- estimated cost from explicit model pricing

Scraper and claim-extraction counters are written to the run as the pipeline executes. Cache hits remain aggregate run totals and are not inserted as fake `llm_calls` rows.

```mermaid
flowchart TD
    A[start_run] --> B[runs row: running]
    B --> C[set current run_id]
    C --> D[model call through create_chat_completion]
    D --> E[llm_calls row]
    C --> F[classification, claim, or exact response cache hit]
    F --> G[increment runs.llm_cache_hits]
    E --> H[finish_run]
    G --> H
    H --> I[aggregate tokens, failures, retries, latency]
    I --> J{"--pipeline-report?"}
    J -- yes --> K[print report]
```

Current report shape:

```text
Run #42 (2026-05-07, ok, 74.2s)
Articles returned:      231
Duplicate URLs skipped: 12
Feed fetch failures:    1
Outside date skipped:   44
Undated included:      0 (0 missing, 0 unparseable)
Undated skipped:       5 (4 missing, 1 unparseable)
Article text fetched:   90
Article text failures:  18
Claims saved:           612
Claims extracted:       112
Claims cached:          35
Claims invalid:         24
Claim failures:         2
Zero-claim results:     19
Claim cheap accepts:    584
Claim verifier calls:   42
Claim verifier accepts: 28
Claim verifier rejects: 14
Stories touched:        38
Story match checks:     14
Story match accepted:   10
Story match rejected:   4
LLM calls:              28
LLM errors:             0
LLM cache hits:         9
Schema failures:        0
Retries:                0
Tokens:                 prompt 18420 / completion 3910
Estimated cost:         EUR 0.21
  claim: 7 calls, tokens 7200/1300, latency 9.4s, EUR 0.01
Novelty audit:
New parent ratio:      2/8 (25.0%)
High-signal not displayed: 1
High-signal new parent arcs: 2
New parent arcs with prior candidates: 1
Rejected related matches: 3
```

Cost estimates use explicitly maintained model pricing in `src/config.py` and the token totals stored in `llm_calls`. The novelty audit is review telemetry only: it surfaces suspicious selection and parent/child cases without changing story memory or briefing output.

## What Costs Money

Potentially expensive paths:

- article classification for uncached articles
- same-day consolidation
- cross-day story matching
- default-on story-match verification
- optional claim extraction
- briefing generation

Cost controls today:

- classification cache
- claim extraction cache
- zero-claim cache
- exact LLM response cache for matching, verification, and briefing prompts
- batched briefing generation
- `--max-per-source` for smaller runs
- `--db-off` for isolated experiments
- `--pipeline-report` for scraper counts, claim metrics, token, latency, cost, and novelty-audit inspection

The most expensive failure mode is not just token spend. A false story merge can corrupt memory across future runs, which is why conservative matching and verifier audit rows matter.

## Current Weak Points

The current system is useful, but several important trust layers are incomplete:

- Source metadata is stored and deterministic source support uses `source_id` with a source-name fallback.
- Evidence-mode source agreement is claim-backed only for exact repeated non-background claims and conservative numeric divergence.
- There is no dedicated contradiction module/table. Numeric divergence is surfaced as `possible conflict`, not confirmed contradiction.
- Evidence runs use full article text for claim extraction when body text is available.
- The derivability gate is in place, but the verifier's paraphrase decisions are asserted by tests with mocks, not measured against reviewed paraphrase cases in `evals/datasets/golden_claims.jsonl`. There is also no per-claim audit row recording which path (cheap accept, verifier accept, verifier reject) decided a saved claim.
- Exact LLM responses for matching, briefing, and the claim verifier can be cached, but there is no semantic story-match decision cache.
- Article deduplication is URL-based, not content-fingerprint-based.
- Date, status, and attribution divergence are not compared yet.

These are the right next improvements because they make the system more inspectable, grounded, and hard to fool.
