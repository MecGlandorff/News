# News

> **Status:** Active prototype. Story memory is working end-to-end; the claim-grounding path is implemented and tested behind `--show-evidence`. Selective full-text evidence extraction, source-agreement detection, and cost/latency telemetry are in progress. See the [Roadmap](#roadmap).

A local-first AI news intelligence prototype that turns noisy RSS feeds into source-grounded, evolving story memory.

Most AI news tools summarize articles.
This project tracks stories.

It ingests RSS coverage, classifies articles, links them into continuing story arcs, extracts source-grounded claims, remembers what changed across runs, and publishes daily Markdown briefings plus newspaper-style PDFs.

## Outputs

- [Latest generated Markdown briefing](briefings/briefing_20260504_2218.md)
- [Latest generated newspaper PDF](newspapers/newspaper_20260504_2218.pdf)
- [Curated sample intelligence brief](sample_outputs/intelligence_brief.md)
- [Briefing archive](briefings/)
- [Newspaper archive](newspapers/)

The latest generated briefing shows the current daily pipeline output. The curated sample is the stronger showcase artifact: it demonstrates the intended story-card shape with status, confidence, source agreement, deltas, evidence, and source links.

## Sample Output

A curated story card from [sample_outputs/intelligence_brief.md](sample_outputs/intelligence_brief.md), trimmed for length:

> ### COVERAGE DECREASING US troop presence in Germany
> _Geopolitics & War / USA Politics - importance 3.9 - 7 sources - latest reported 2026-05-03 13:39 UTC_
>
> **Status:** Escalating | **Confidence:** High | **Source agreement:** Broad | **Dispute:** None
>
> **What changed today:** Trump's announced 5,000-troop withdrawal became a wider threat to cut further, while Dutch officials and senior Republicans warned that deterrence and US operational reach could suffer.
>
> **Evidence:** BBC News reports that Germany troop cuts send the wrong signal to Russia; NOS quotes Dutch concern about keeping "het hoofd koel"; de Volkskrant notes congressional limits on removing many troops.
>
> _Sources: The Guardian, Al Jazeera, de Volkskrant, NOS, BBC News._

Note the trend tag, explicit `What changed today` delta, bounded uncertainty labels, evidence spans, and source links. None of these come from a single article; they are emitted by the story-memory, claim-grounding, and briefing layers.

## Why It Is Interesting

- **Story memory:** articles are grouped into canonical stories and matched against recent history.
- **Daily deltas:** each story surfaces what changed today, not just what happened.
- **Claim extraction:** articles can be converted into atomic claims with evidence spans via `--show-evidence`.
- **Story-card briefings:** output surfaces status, confidence, source agreement, dispute flags, and open questions.
- **Source-aware synthesis:** briefings include source links, reported timestamps, source counts, importance, and trend signals.
- **Local-first operation:** SQLite, local files, Markdown, and PDFs; no hosted service or heavy infrastructure.
- **Cost discipline:** high-volume calls use `gpt-5.4-mini`; stronger models are reserved for story reasoning and final prose.

## Design Decisions

These are the load-bearing tradeoffs. They are documented in more detail as ADRs under [docs/adr/](docs/adr/).

- **Local-first storage over a hosted backend.** SQLite plus Markdown files on disk. Trades the convenience of a UI and multi-user access for transparency, cheap iteration, git-diffable outputs, and zero infrastructure to keep alive.
- **URL deduplication now, content fingerprinting later.** The scraper currently deduplicates exact repeated feed items by normalized URL. Classification and claim extraction use content hashes for cache invalidation, but article-level content fingerprinting across syndicated copies is still future work. This keeps ingestion simple while making the current limitation visible.
- **Tiered model routing.** `gpt-5.4-mini` for high-volume per-article classification; stronger models reserved for story-level reasoning and final briefing prose. Tradeoff: occasional miscategorization at the cheap tier, accepted because story-level reasoning is where reasoning quality actually shows up to a reader.
- **Same-day story consolidation before memory match.** Articles are merged into canonical labels within a day before being matched against history. Costs one extra LLM pass per run but materially reduces duplicate story arcs in the long-term memory.
- **Evidence spans validated against source text, not trusted from the model.** A claim is only persisted when its `evidence_span` is found verbatim in the input used to extract it. Drops some genuine-but-paraphrased claims; eliminates a class of hallucination that would otherwise be invisible to a reader of the briefing.
- **Claim extraction on RSS title/description first, full text deferred.** Selective full-text extraction is gated on cost-and-latency observability landing (Phase 3) so we can measure what we are buying before turning it on for every article. Tradeoff: weaker evidence on stories where the headline does not carry the substance.
- **Briefings as the contract, not the database.** The Markdown briefing is the human-facing artifact and the test surface; the SQLite schema is allowed to change as long as the briefing remains stable and sourced. This keeps schema refactors cheap.

## Pipeline

```text
Source
  -> Article
  -> Claim
  -> Story Arc
  -> Story Delta
  -> Briefing
```

Current implementation:

```text
RSS feeds
  -> scrape, normalize URLs, deduplicate exact URL repeats
  -> classify theme, story_label, importance
  -> consolidate same-day story labels
  -> match stories against recent memory
  -> optionally extract claims and evidence spans
  -> generate story deltas and briefing prose
  -> write Markdown briefing and newspaper PDF
```

See [docs/architecture.md](docs/architecture.md) for the database model and pipeline details.

## Story Intelligence

The tracker keeps a compact local memory of each story:

- canonical story label
- first seen and last seen dates
- daily source count and average importance
- trend signal: new, increasing, steady, or decreasing
- article links and observations for each tracked date
- generated summary and delta memory for future context

Briefings surface that memory as an explicit delta:

```md
**What changed today:** Police classified the Golders Green stabbing as terrorism, shifting the story from a local attack to a national security and antisemitism concern.
```

That makes the output read less like a daily article summary and more like an intelligence update.

## Source Grounding

The claim layer is the bridge from article text to auditable briefing output.

With `--show-evidence`, the pipeline extracts structured claims:

- `claim_text`
- `claim_type`
- `entities`
- `evidence_span`
- `confidence`

> **Hallucination guard:** a claim is persisted only when its `evidence_span` is found verbatim in the article input used for extraction. Model-paraphrased spans are dropped, never silently substituted, and the briefing never falls back to model-restated claim text. This drops some genuine-but-rephrased claims on purpose — the alternative is unfalsifiable evidence in the briefing.

The near-term strategy is intentionally cost-conscious: broad claim extraction uses RSS title/description by default and is cached by input content hash. A future pass should use full article text selectively for high-value evidence work when `--fetch-article-text` is enabled. Full-text claim extraction for every article is deferred until cost and latency observability exists.

## Setup

Create a virtual environment and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

For tests:

```bash
pip install -r requirements-dev.txt
pytest
```

## Configuration

Copy `.env.example` to `.env` and add your OpenAI API key:

```bash
OPENAI_API_KEY=your-api-key
```

Or set the key for your current shell session:

```bash
export OPENAI_API_KEY="your-api-key"
```

`OPENAI_API_KEY` is required for classification, story tracking, claim extraction when enabled, and briefing generation. Running the pipeline makes OpenAI API calls and may incur API costs.

Model choices and story lookback are configured in [src/config.py](src/config.py).
RSS sources are configured in [src/scraper.py](src/scraper.py); the current list contains 21 feeds. Each run seeds those feeds into the local `sources` table for later source-aware reasoning.

## Usage

Run the full pipeline:

```bash
python -m src.run
```

Useful options:

```bash
python -m src.run --max-per-source 5
python -m src.run --skip-briefing
python -m src.run --skip-pdf
python -m src.run --skip-digest
python -m src.run --db-off
python -m src.run --date 2026-05-02
python -m src.run --top-developments 5
```

Append extracted claim evidence spans to the Markdown briefing:

```bash
python -m src.run --show-evidence
```

Fetch full article-page text in addition to RSS metadata:

```bash
python -m src.run --fetch-article-text
```

Current note: the scraper can fetch full article text, but claim extraction still uses title/description until selective full-text evidence extraction is wired in.

Use both once selective full-text evidence extraction lands and you want higher-quality evidence for the current run:

```bash
python -m src.run --show-evidence --fetch-article-text
```

Preview the newspaper PDF design without scraping or API calls:

```bash
python scripts/preview_newspaper.py
```

For a cheap real newspaper test that does not touch the normal story database:

```bash
python -m src.run --db-off --max-per-source 1 --top-developments 5 --skip-digest --skip-briefing
```

`--db-off` uses a temporary database and classification cache for that run, leaving `data/stories.db` untouched.
`--today` is kept as a backwards-compatible alias for `--date`.

## Local Data

Generated runtime data is intentionally ignored by git:

- `data/`: SQLite database and daily JSON article snapshots.
- `output/`: local generated Markdown digests and older scratch outputs.
- `logs/`: local logs if you run scheduled jobs.

Public briefing files in `briefings/` are intended to be committed and published with the repository.
Public newspaper PDF files in `newspapers/` are intended to be committed and clicked from the repository.

The `claims` and `claim_extractions` tables are created lazily when a run uses `--show-evidence`. A local database from a normal run can therefore contain story and article tables without claim tables.

## Documentation

- [Architecture](docs/architecture.md)
- [Model behavior](docs/model-behavior.md)
- [Evaluation plan](docs/evaluation.md)
- [Failure modes](docs/failure-modes.md)
- [Architecture decision records](docs/adr/)

## Current Limitations

- RSS feed availability and formatting vary by source.
- Article deduplication is URL-based today; content fingerprinting across syndicated copies is planned.
- Story matching can over-merge distinct but similar stories.
- Claim extraction is cached by input content hash and caches zero-claim results, but it still uses RSS title/description rather than fetched full article text.
- Claim extraction does not yet consume fetched full article text.
- Source metadata is seeded, and new article rows include nullable `source_id` when a source row exists. Source agreement detection is not claim-backed yet.
- Current source agreement and dispute labels are briefing-level signals, not yet backed by a dedicated contradiction table.
- Cost and latency tracking are planned but not implemented yet.
- The project stores data locally and does not include a hosted UI.

## Roadmap

The project is structured in phases so each layer builds on auditable output from the previous one.

**Phase 1 — Ingestion & classification (done).** Multi-source RSS scraping, URL normalization, URL-based deduplication, and theme/importance classification with a content-hash cache.

**Phase 2 — Story memory & claim grounding (current).** Canonical story labels, same-day consolidation, recent-history matching, daily delta summaries, and structured claim extraction with evidence-span validation against source text.

**Phase 3 — Source-aware reasoning (next).**
- Source metadata seeded from the 21 configured RSS feeds in `src/scraper.py`, with nullable `articles.source_id` populated for new rows when a seeded source matches. Done as a foundation step; source agreement does not use it yet.
- Content fingerprinting or source-aware weighting for syndicated copies, after the source model exists.
- Selective full-text claim extraction gated on a per-article value heuristic, behind `--fetch-article-text`.
- Claim-backed source agreement and, later, a dedicated contradiction table backing dispute labels that are currently briefing-level only.
- Cost and latency telemetry per pipeline stage; budget caps and per-run cost summaries.

**Phase 4 — Evaluation & hardening (later).**
- Held-out evaluation set for story matching, classification, and claim grounding with regression tracking.
- Failure-mode test fixtures based on issues found in production runs (see [docs/failure-modes.md](docs/failure-modes.md)).
- Optional hosted read-only UI for browsing the briefing archive; the core pipeline stays local-first.

Out of scope for now: real-time push, multi-user accounts, social signals, paid-source ingestion.
