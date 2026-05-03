# News

A local-first AI news intelligence prototype that turns noisy RSS feeds into source-grounded, evolving story memory.

Most AI news tools summarize articles.
This project tracks stories.

It ingests RSS coverage, classifies articles, links them into continuing story arcs, extracts source-grounded claims, remembers what changed across runs, and publishes daily Markdown briefings plus newspaper-style PDFs.

## Latest Outputs

- [Latest Markdown briefing](briefings/briefing_20260502_2244.md)
- [Latest newspaper PDF](newspapers/newspaper_20260502_2244.pdf)
- [Sample intelligence brief](sample_outputs/intelligence_brief.md)
- [Briefing archive](briefings/)
- [Newspaper archive](newspapers/)

## Why It Is Interesting

- **Story memory:** articles are grouped into canonical stories and matched against recent history.
- **Daily deltas:** each story surfaces what changed today, not just what happened.
- **Claim extraction:** articles can be converted into atomic claims with evidence spans via `--show-evidence`.
- **Source-aware synthesis:** briefings include source links, reported timestamps, source counts, importance, and trend signals.
- **Local-first operation:** SQLite, local files, Markdown, and PDFs; no hosted service or heavy infrastructure.
- **Cost discipline:** high-volume calls use `gpt-5.4-mini`; stronger models are reserved for story reasoning and final prose.

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
  -> scrape, normalize URLs, deduplicate
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

Claims are stored only when the structured fields validate and the evidence span appears in the article input used for extraction. Evidence rendering does not fall back to model-restated claim text.

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
python -m src.run --today 2026-05-02
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

## Local Data

Generated runtime data is intentionally ignored by git:

- `data/`: SQLite database and daily JSON article snapshots.
- `output/`: local generated Markdown digests and older scratch outputs.
- `logs/`: local logs if you run scheduled jobs.

Public briefing files in `briefings/` are intended to be committed and published with the repository.
Public newspaper PDF files in `newspapers/` are intended to be committed and clicked from the repository.

## Documentation

- [Architecture](docs/architecture.md)
- [Model behavior](docs/model-behavior.md)
- [Evaluation plan](docs/evaluation.md)
- [Failure modes](docs/failure-modes.md)
- [Architecture decision records](docs/adr/)

## Current Limitations

- RSS feed availability and formatting vary by source.
- Story matching can over-merge distinct but similar stories.
- Claim extraction is cached by input content hash and caches zero-claim results, but it still uses RSS title/description rather than fetched full article text.
- Claim extraction does not yet consume fetched full article text.
- Source reliability metadata and source agreement detection are planned for Phase 3.
- Cost and latency tracking are planned but not implemented yet.
- The project stores data locally and does not include a hosted UI.
