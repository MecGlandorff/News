# News

## AI News Intelligence That Remembers What Changed

Most AI news tools summarize the article in front of them. **News** builds a local, source-grounded memory of real-world events: what happened today, what changed since the previous run, which sources support it, and where uncertainty remains.

It is a builder-grade prototype of an intelligence briefing system: RSS ingestion, structured LLM stages, SQLite event memory, evidence-span validation, story-match verification, run observability, Markdown briefings, and newspaper-style PDFs.

```text
Source -> Article -> Claim -> Story Arc -> Story Delta -> Briefing
```

> **Status:** Active prototype. Story memory, full-text claim grounding, claim/span derivability gate (deterministic + cheap LLM verifier), source metadata, source-identity support, LLM observability, estimated run cost, exact LLM response caching, default-on full-text story-match verification, and a repeatable claim-quality eval harness are implemented. Evidence-mode claim-backed source agreement now has a conservative first pass for exact repeated claims and numeric divergence; reviewed paraphrase verifier cases and broader date/status/attribution divergence are still in progress.

## Why it is great! 

- **Product idea:** source-grounded event memory, not another RSS summary feed.
- **System design:** explicit pipeline from source to article to claim to story delta to briefing.
- **AI discipline:** structured model outputs, prompt versions, schema validation, cache keys, and fallbacks.
- **Trust layer:** claims are kept only when an evidence span appears in the article **and** either (1) all numbers and a listed entity from the claim appear in the span, or (2) a cheap `gpt-5.4-nano` verifier confirms the span supports the claim.
- **Temporal memory:** story observations preserve what the system knew yesterday so today's briefing can explain movement.
- **Observability:** `runs` and `llm_calls` record model usage, cache hits, schema failures, scraper counts, claim metrics, latency, tokens, and estimated cost.
- **Regression posture:** the pytest suite covers scraper behavior, source seeding, caching, tracking, claims, observability, CLI behavior, and PDF output.

The flagship outcome is an intelligence-style briefing with status, confidence, source agreement, dispute labels, deltas, source links, and optional evidence spans.

## Product Snapshot

| Capability | What it does today |
|---|---|
| Story memory | Groups articles into continuing event arcs and compares against recent history |
| Daily delta | Writes "what changed today" instead of repeating generic summaries |
| Claim grounding | Uses `gpt-5.4-nano` with full article text when available; saves claims only when the evidence span is in the article and a hybrid deterministic + LLM-verifier gate decides the span supports the claim |
| Source support | Counts distinct source identities with `source_id` first and source-name fallback |
| Claim-backed agreement | In evidence mode, exact repeated claims can back `partial`/`broad`, and comparable numeric divergence can force `mixed` / `possible conflict` |
| Match verifier | Uses full article text and `gpt-5.4-nano` to reject adjacent-topic story merges |
| Local database | Keeps stories, articles, observations, claims, sources, runs, LLM calls, and exact LLM response cache rows in SQLite |
| Outputs | Publishes Markdown briefings, digest files, and newspaper-style PDFs |
| Inspectability | Includes ADRs, failure modes, model behavior docs, database queries, pipeline diagrams, and a claim-quality eval harness |

## Outputs

- [Recent generated Markdown briefing](briefings/briefing_20260511_2134.md)
- [Curated sample intelligence brief](sample_outputs/intelligence_brief.md)
- [Briefing archive](briefings/)
- [Newspaper archive](newspapers/)

The generated files show current pipeline behavior. The curated sample is the best compact showcase of the intended story-card shape.

## Sample Story Card

Trimmed from [sample_outputs/intelligence_brief.md](sample_outputs/intelligence_brief.md):

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

This is not a single-article summary. It is produced by story tracking, temporal memory, claim grounding, source aggregation, and briefing generation.

## How It Works

The run starts in `src/run.py` and moves through these stages:

```text
RSS feeds
  -> src/sources.py      seed configured sources into SQLite
  -> src/scraper.py      fetch RSS, normalize URLs, filter dates, deduplicate URLs
  -> src/classifier.py   classify theme, story_label, and importance
  -> src/tracker.py      consolidate labels, match recent stories, write story memory
  -> src/story_matching.py optionally verify candidate matches with full article text
  -> src/claims.py       optionally extract validated claims and evidence spans
  -> src/top10.py        select stories and generate briefing cards
  -> src/digest.py       write local digest Markdown
  -> src/newspaper.py    render the PDF from the same briefing package
  -> src/observability.py record run totals, model calls, cache hits, and tokens
```

For the detailed code-path audit, read [docs/how-it-works.md](docs/how-it-works.md).

For the SQLite inspection guide, read [docs/database-guide.md](docs/database-guide.md).

## Story Memory

The tracker keeps a compact local memory of each event:

- canonical story label
- first seen and last seen dates
- daily source count and importance average
- trend signal: `new`, `up`, `steady`, or `down`
- linked articles and observations per day
- generated summary and `delta_summary` for the next run

Candidate cross-day matches are verified by default before memory is reused:

```bash
python -m src.run
```

That verifier uses `gpt-5.4-nano` and full article text for candidate matches. It asks whether today's article group continues the same real-world event, stores rows in `story_match_decisions`, and defaults to a new story when continuity evidence is weak. Use `--no-verify-story-matches` only when comparing against the older label-only match path.

## Source Grounding

Claim extraction is optional:

```bash
python -m src.run --show-evidence
```

When enabled, the claim layer extracts:

- `claim_text`
- `claim_type`
- `entities`
- `evidence_span`
- `confidence`

A claim is saved only if its `evidence_span` appears in the article input **and** the claim passes a derivability gate against that span:

1. If any number in `claim_text` is missing from `evidence_span`, the claim is dropped immediately (no LLM call).
2. If `claim_text` (normalized) appears in `evidence_span`, or if at least one listed entity from the claim appears in `evidence_span`, the claim is accepted deterministically.
3. Otherwise, a cheap `gpt-5.4-nano` verifier (`CLAIMS_VERIFIER_PROMPT_VERSION = "2026-05-14-v1"`, cached via `llm_response_cache`) decides whether the span supports the claim. Verifier failures default-reject.

Run totals are exposed in `--pipeline-report` as `Claim cheap accepts`, `Claim verifier calls`, `Claim verifier accepts`, and `Claim verifier rejects`. See [docs/adr/0013-claim-evidence-derivability.md](docs/adr/0013-claim-evidence-derivability.md).

With `--show-evidence`, the scraper fetches full article pages and claim extraction uses title, RSS description, and full article text when available. If full-text extraction fails, claims fall back to title and description.

To compare RSS-only claim quality against full-text evidence-run quality:

```bash
python -m evals.run_claim_quality_eval
```

The eval records expected-claim coverage, evidence validity, duplicate claims, token usage, latency, and estimated cost. See [evals/README.md](evals/README.md).

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

Copy `.env.example` to `.env` and add your OpenAI API key, or export it for the current shell:

```bash
export OPENAI_API_KEY="your-api-key"
```

`OPENAI_API_KEY` is required for classification, story tracking, claim extraction when enabled, and briefing generation. Running the pipeline makes OpenAI API calls and may incur API costs.

Model choices and the story lookback window live in [src/config.py](src/config.py). RSS feeds live in [src/scraper.py](src/scraper.py).

## Usage

Run the full pipeline:

```bash
python -m src.run
```

Useful options:

```bash
python -m src.run --max-per-source 5
python -m src.run --date 2026-05-07
python -m src.run --top-developments 5
python -m src.run --show-evidence
python -m src.run --fetch-article-text
python -m src.run --no-verify-story-matches
python -m src.run --pipeline-report
python -m src.run --db-off
python -m src.run --skip-digest
python -m src.run --skip-briefing
python -m src.run --skip-pdf
```

Notes:

- `--today` is a backwards-compatible alias for `--date`.
- `--db-off` uses a temporary SQLite database/cache and leaves `data/stories.db` untouched.
- `--show-evidence` fetches article bodies for claim extraction and falls back to RSS title/description when body text is unavailable.
- `--fetch-article-text` fetches article bodies even when evidence extraction is disabled.
- Story-match verification is on by default and does not require `--show-evidence`; `--no-verify-story-matches` disables it for comparison runs.
- `--pipeline-report` prints run totals, scraper counts, claim metrics, model tokens, latency, and estimated EUR cost after success or failure.

Example audit run:

```bash
python -m src.run --date 2026-05-07 --fetch-article-text --show-evidence --pipeline-report
```

## Local Data

Generated runtime data is intentionally local:

- `data/stories.db`: SQLite story memory, article rows, claims, source metadata, runs, LLM call logs, and exact LLM response cache rows.
- `data/daily/`: JSON snapshots of classified articles for each run date.
- `run_artifacts/`: Markdown run reports written from observability rows.
- `output/`: generated digest Markdown and scratch outputs.
- `briefings/`: generated Markdown briefings intended to be browsed or published.
- `newspapers/`: generated newspaper-style PDFs intended to be browsed or published.

The `claims` and `claim_extractions` tables are created lazily. A database from runs without `--show-evidence` can therefore contain story and article tables without claim tables.

## Documentation

Start with [docs/README.md](docs/README.md).

Core docs:

- [How the project works](docs/how-it-works.md)
- [Database guide](docs/database-guide.md)
- [Architecture reference](docs/architecture.md)
- [Model behavior](docs/model-behavior.md)
- [Evaluation plan](docs/evaluation.md)
- [Evaluation harnesses](evals/README.md)
- [Failure modes](docs/failure-modes.md)
- [Architecture decision records](docs/adr/)

## Current Limitations

- Article deduplication is URL-based; content fingerprinting across syndicated copies is planned.
- Story matching can over-merge adjacent topics when the verifier is disabled. Exact verifier responses can be reused for identical prompts, but there is no semantic verifier-decision cache.
- Claim extraction is cached and evidence-validated; the derivability gate is deterministic-first and falls back to a `gpt-5.4-nano` verifier for paraphrase-style claims. Evidence runs use fetched full text when available, and RSS-vs-full-text quality can be compared with `evals.run_claim_quality_eval`.
- Source metadata is seeded and attached to new articles; deterministic source support uses `source_id` first.
- Evidence-mode source agreement is claim-backed for exact repeated non-background claims and conservative numeric divergence. It does not infer source independence, and ordinary runs still use source identity plus briefing defaults.
- EUR cost estimates use explicitly maintained pricing and a static USD-to-EUR rate.
- Scraper duplicate/failure counts are surfaced in `--pipeline-report`.
- The project has no hosted UI; the core artifact is local Markdown/PDF plus SQLite memory.

## Roadmap

**Phase 1 - Ingestion and classification: done.**
Multi-source RSS scraping, URL normalization, URL deduplication, and cached article classification.

**Phase 2 - Story memory and claim grounding: done.**
Canonical labels, same-day consolidation, recent-history matching, daily observations, delta summaries, structured claim extraction, and evidence-span validation.

**Phase 3 - Source modeling and observability: in progress.**
Source metadata, source-identity support, full-text evidence extraction, scraper observability, cost estimates, run observability, exact LLM response caching, the claim-quality comparison harness, and the first evidence-mode claim-backed source-agreement slice have shipped. Next work is running real reviewed claim cases and broadening claim comparison beyond exact repeats and numeric divergence.

**Phase 4 - Evaluation and hardening: later.**
Reviewed claim-quality cases, broader source-divergence handling, story-matching fixtures, and regression evals should land before the system becomes more autonomous.

Out of scope for now: real-time push, multi-user accounts, social signals, paid-source ingestion, cloud deployment, Kubernetes, Terraform, or a heavy frontend.
