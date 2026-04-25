# News Scraper

RSS news scraper that classifies articles, tracks ongoing stories, and generates daily Markdown digests and briefings.

## What It Does

- Fetches articles from configured RSS feeds.
- Classifies each article by theme, story label, and importance using the OpenAI API.
- Tracks ongoing stories in a local SQLite database.
- Writes public briefing Markdown files to `briefings/`.
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
python -m src.run --today 2026-04-18
```

By default, the scraper reads every item exposed by each configured RSS feed. Use `--max-per-source` to cap items per feed.

Full article-page fetching is off by default. To fetch article body text in addition to RSS metadata:

```bash
python -m src.run --fetch-article-text
```

## Local Data

Generated runtime data is intentionally ignored by git:

- `data/`: SQLite database and daily JSON article snapshots.
- `output/`: local generated Markdown digests and older scratch outputs.
- `logs/`: local logs if you run scheduled jobs.

Public briefing files in `briefings/` are intended to be committed and published with the GitHub repository.

## Limitations

- RSS feed availability and formatting vary by source.
- LLM classifications and story labels can be imperfect.
- Cached story labels are reused for unchanged articles, then consolidated by the tracker.
- The project stores data locally and does not include a hosted UI.
