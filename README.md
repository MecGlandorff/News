# Daily News Intelligence Briefing

AI-assisted news pipeline that ingests RSS feeds, groups related coverage into ongoing stories, remembers story context across days, and publishes daily Markdown briefings plus newspaper-style PDFs.

This is not just a summarizer. The pipeline tracks whether stories are new, developing, steady, or cooling, then uses that continuity to produce more useful daily briefings.

## Latest Outputs

- [Latest Markdown briefing](briefings/briefing_20260430_2330.md)
- [Latest newspaper PDF](newspapers/newspaper_20260430_2330.pdf)
- [Briefing archive](briefings/)
- [Newspaper archive](newspapers/)

## Why It Is Interesting

- **Story continuity:** related articles are consolidated into canonical ongoing stories and matched against recent history.
- **Coverage movement:** stories are tagged as new, increasing, steady, or decreasing based on source pickup over time.
- **Briefing memory:** generated story summaries are saved back to the local story database, so future briefings can use prior context.
- **Source-aware synthesis:** each briefing includes source links, reported timestamps, importance, theme, and source count.
- **Dual publishing:** the same briefing package renders to Markdown and a custom newspaper-style PDF.
- **Local-first operation:** runtime state lives in SQLite and ignored local folders; public outputs can be committed separately.

## Pipeline

```text
RSS feeds
  -> article normalization and caching
  -> theme, story, and importance classification
  -> same-day story consolidation
  -> cross-day story matching
  -> briefing package with trend and previous context
  -> Markdown briefing + newspaper PDF
```

## Story Intelligence

The tracker keeps a compact local memory of each story:

- canonical story label
- first seen and last seen dates
- daily source count and average importance
- trend signal based on previous coverage
- article links and observations for each tracked date
- generated summary and delta memory for future context

Briefings surface that memory as an explicit delta line:

```md
**What changed today:** Police classified the Golders Green stabbing as terrorism, shifting the story from a local attack to a national security and antisemitism concern.
```

That makes each briefing read less like a daily snapshot and more like an intelligence update.

## What It Does

- Fetches articles from configured RSS feeds.
- Classifies each article by theme, story label, and importance using the OpenAI API.
- Tracks ongoing stories in a local SQLite database.
- Writes public briefing Markdown files to `briefings/`.
- Writes public newspaper PDF files to `newspapers/`.
- Writes local digest Markdown files to `output/`.
- Caches article classifications to reduce repeated OpenAI calls on reruns.

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

`OPENAI_API_KEY` is required for classification, story matching, and briefing generation. Running the pipeline makes OpenAI API calls and may incur API costs.

Model choices and story lookback are configured in `src/config.py`.

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
python -m src.run --db-off
python -m src.run --today 2026-04-18
```

By default, the scraper reads every item exposed by each configured RSS feed. Use `--max-per-source` to cap items per feed.

Full article-page fetching is off by default. To fetch article body text in addition to RSS metadata:

```bash
python -m src.run --fetch-article-text
```

Preview the newspaper PDF design without scraping or API calls:

```bash
python scripts/preview_newspaper.py
```

The preview PDF is written to `test_output/preview/newspaper_preview.pdf`.

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

Public briefing files in `briefings/` are intended to be committed and published with the GitHub repository.
Public newspaper PDF files in `newspapers/` are intended to be committed and clicked from the GitHub repository.

## Limitations

- RSS feed availability and formatting vary by source.
- LLM classifications and story labels can be imperfect.
- Cached story labels are reused for unchanged articles, then consolidated by the tracker.
- The project stores data locally and does not include a hosted UI.
