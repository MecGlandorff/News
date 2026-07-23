# News

## Source-Grounded Event Memory

Most AI news tools summarize the article in front of them. **News** builds a local, source-grounded memory of real-world events: what happened today, what changed since the previous run, which sources support it, and where uncertainty remains.

It is a local-first intelligence briefing system with RSS ingestion, structured LLM stages, SQLite event memory, evidence-span validation, story-match verification, run observability, Markdown briefings, and newspaper-style PDFs.

```text
Source -> Article -> Claim -> Story Arc -> Story Delta -> Briefing
```

> **Status:** Active development. The Phase 3 foundation is implemented: append-only article occurrences, stored-snapshot replay, conservative claim/span verification, source metadata, run-scoped observability, bounded exact-response caching, evidence-gated story/arc matching, executable acceptance-gate evals, and claim-backed source support/divergence. The matching reconstruction passed; a fresh daily run series and real reviewed claim cases remain the gate before Phase 4.

## Why It Exists

- **Product idea:** source-grounded event memory, not another RSS summary feed.
- **System design:** explicit pipeline from source to article to claim to story delta to briefing.
- **AI discipline:** structured model outputs, prompt versions, schema validation, cache keys, and fallbacks.
- **Trust layer:** only near-verbatim claims are accepted deterministically. Quantity, unit, direction, and negation mismatches are rejected; every other paraphrase goes through a cached `gpt-5.4-nano` verifier that defaults to reject.
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
| Claim-backed agreement | Current-day claims support agreement; seven days of older claims are dated context only. Exact/similar multi-source support and precise number/date/status/attribution divergence are compared without claiming source independence |
| Story and arc matching | Retrieves candidates from article evidence, asks pinned `gpt-5.4-mini-2026-03-17` for strict structured decisions at `low` reasoning, and applies a deterministic fail-closed evidence gate. Same story and same named arc are separate decisions |
| Local database | Keeps append-only occurrence snapshots plus derived stories, observations, claims, sources, run history, LLM calls, and bounded exact-response cache rows in SQLite |
| Outputs | Publishes Markdown briefings, digest files, and newspaper-style PDFs |
| Inspectability | Includes ADRs, failure modes, model behavior docs, database queries, pipeline diagrams, and a claim-quality eval harness |

## Outputs

- [Recent generated Markdown briefing](briefings/briefing_20260511_2134.md)
- [Curated sample intelligence brief](sample_outputs/intelligence_brief.md)
- [Briefing archive](briefings/)
- [Newspaper archive](newspapers/)

The archives intentionally retain historical generated behavior. The curated sample is the best compact showcase of the intended story-card shape.

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
  -> src/tracker/occurrences.py preserve source snapshots and replay metadata
  -> src/tracker/        retrieve and judge same-day, cross-day, and named-arc candidates
  -> src/tracker/matching/ enforce grounded anchors, conflicts, and fail-closed ambiguity
  -> src/claims/         optionally extract validated claims and evidence spans
  -> src/briefing/       select stories and generate briefing cards
  -> src/digest.py       write local digest Markdown
  -> src/rendering/newspaper.py render the PDF from the same briefing package
  -> src/observability/  record run totals, model calls, cache hits, and tokens
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

Evidence-gated matching is enabled by default before memory is reused:

```bash
python -m src.run
```

The matcher builds compact profiles from classifier labels, RSS titles and
descriptions, and recent source-grounded memory. Deterministic retrieval supplies a
small candidate set; pinned `gpt-5.4-mini-2026-03-17` judges same-story or same-arc
semantics with strict JSON Schema; and a deterministic gate verifies shared anchors,
conflicts, container type, and ambiguity. Exact URL duplicates are the narrow
deterministic acceptance. Weak, conflicting, malformed, or multiply accepted cases
remain a new story or arc.

Matching does not fetch article bodies. Missing RSS evidence can therefore cause an
honest false split instead of a guessed merge. Decisions are auditable in
`same_day_match_decisions`, `story_match_decisions`, and `story_arc_decisions`. Use
`--no-verify-story-matches` only for comparison with the legacy label-first path.

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

A claim is saved only if its `evidence_span` appears in the bounded article input **and** the claim passes a versioned derivability policy:

1. Missing quantities or explicit negation, direction, or unit conflicts are rejected without an LLM call.
2. A normalized near-verbatim claim contained in the span is accepted deterministically.
3. Every other paraphrase, including entity-overlap and anaphoric cases, goes to the cached verifier. Malformed output, uncertainty, and network failures reject the claim.

The validation-policy version is part of claim cache reuse, so tightening local rules cannot silently reuse claims accepted under an older policy. Claim input is capped at 20,000 characters and truncation is reported.

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
python3.12 -m venv .venv
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
python -m src.run --date 2026-05-07 --include-undated
python -m src.run --top-developments 5
python -m src.run --show-evidence
python -m src.run --fetch-article-text
python -m src.run --no-verify-story-matches
python -m src.run --pipeline-report
python -m src.run --replay 2026-05-07
python -m src.run --db-off
python -m src.run --skip-digest
python -m src.run --skip-briefing
python -m src.run --skip-pdf
```

Notes:

- `--today` is a backwards-compatible alias for `--date`.
- `--include-undated` only affects date-filtered runs; it keeps feed items with missing or unparseable published dates under the selected run date.
- `--db-off` uses a temporary SQLite database/cache and leaves `data/stories.db` untouched.
- `--show-evidence` fetches article bodies for claim extraction and falls back to RSS title/description when body text is unavailable.
- `--fetch-article-text` fetches article bodies even when evidence extraction is disabled.
- Evidence-gated matching is on by default and does not require `--show-evidence`; `--no-verify-story-matches` selects the legacy comparison path.
- `--pipeline-report` prints run totals, scraper counts, claim metrics, model tokens, latency, and estimated EUR cost after success or failure.
- `--replay DATE` makes no network calls. It transactionally rebuilds derived tracking state from that date forward using stored occurrence, classification, and assignment snapshots, and fails before changing state if a required snapshot is missing.
- `--replay` cannot be combined with `--date`/`--today` or `--db-off`.

Example audit run:

```bash
python -m src.run --date 2026-05-07 --fetch-article-text --show-evidence --pipeline-report
```

## Local Data

Generated runtime data is intentionally local:

- `data/stories.db`: SQLite occurrence snapshots, derived story memory, claims, source metadata, runs, LLM call logs, and exact LLM response cache rows.
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
- Evidence-gated matching is precision-first and can over-split when a feed retains only a thin headline or when several candidates clear the gate. It does not fetch body text at matching time, and there is no semantic decision cache. Disabling it restores the less safe legacy label-first path.
- Claim extraction is cached and evidence-validated; the derivability gate is deterministic-first and falls back to a `gpt-5.4-nano` verifier for paraphrase-style claims. Evidence runs use fetched full text when available, and RSS-vs-full-text quality can be compared with `evals.run_claim_quality_eval`.
- Source metadata is seeded and attached to new articles; deterministic source support uses `source_id` first.
- Evidence-mode source agreement is claim-backed for current-day exact and conservative similar-claim support. Precise number, date, status, and attribution differences produce source-divergence notes. It does not infer source independence or confirmed contradiction.
- Historical claims are available to evidence briefings for seven editorial days but are explicitly context-only and cannot strengthen current agreement.
- The editorial day is `Europe/Brussels`; stored timestamps remain UTC.
- EUR cost estimates use explicitly maintained pricing and a static USD-to-EUR rate.
- Scraper duplicate/failure counts are surfaced in `--pipeline-report`.
- The project has no hosted UI; the core artifact is local Markdown/PDF plus SQLite memory.

## Roadmap

**Phase 1 - Ingestion and classification: done.**
Multi-source RSS scraping, URL normalization, URL deduplication, and cached article classification.

**Phase 2 - Story memory and claim grounding: done.**
Canonical labels, same-day grouping, recent-history matching, daily observations, delta summaries, structured claim extraction, and evidence-span validation.

**Phase 3 - Source modeling and observability: implementation complete, fresh review series pending.**
Source metadata, occurrence-backed evidence, stored-snapshot replay, run-scoped observability, bounded caching, conservative derivability, claim-backed agreement/source divergence, and evidence-gated matching have shipped. The [saved-snapshot matching reconstruction](evals/reports/phase3_matching_reconstruction_2026-07-23.md) selected `low` reasoning with zero reviewed corrupting accepts and 80% recall on five scorable positives; one multiple-candidate continuation stayed fail-closed. The remaining [Phase 3 closure review](docs/phase3-closure-plan.md) is a fresh daily run series plus real claim-verifier and source-comparison review.

**Phase 4 - Evaluation and hardening: later.**
Only after Phase 3's real-case review should deeper citation, temporal, story-matching, and source-divergence evals make the system more autonomous.

Out of scope for now: real-time push, multi-user accounts, social signals, paid-source ingestion, cloud deployment, Kubernetes, Terraform, or a heavy frontend.

## License

MIT. See [LICENSE](LICENSE).
