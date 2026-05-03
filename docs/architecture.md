# Architecture

## Overview

The system converts RSS feeds into a local story-memory database and publishes daily intelligence briefings.

The core idea is **story continuity**: rather than summarizing today's articles in isolation, the pipeline matches each article against an ongoing story record and uses accumulated memory to generate briefings that show what changed, not just what happened.

---

## Pipeline

```text
Configured RSS feeds
  ↓
src/scraper.py          — fetch, normalize URLs, deduplicate
  ↓
src/classifier.py       — theme, story_label, importance (gpt-5.4-mini)
  ↓                       cached by content_hash + model + prompt_version
src/article_cache.py    — classification cache
  ↓
src/tracker.py          — consolidate same-day labels (gpt-5.5)
                          match today's labels to recent canonical labels (gpt-5.5)
                          upsert stories, story_daily, story_observations, articles
  ↓
src/claims.py           — extract atomic claims per tracked article (gpt-5.4-mini)
  ↓                       linked to story_id; enabled via --show-evidence
  ↓
src/top10.py            — aggregate by story, score, select sections
                          generate briefing text + delta_summary (gpt-5.5)
                          surface evidence spans if --show-evidence
  ↓
src/digest.py           — lightweight local digest (no LLM)
  ↓
src/newspaper.py        — render newspaper-style PDF
  ↓
briefings/              — published Markdown (committed to repo)
newspapers/             — published PDFs (committed to repo)
output/                 — local digests (git-ignored)
```

Conceptually, claims sit between articles and story arcs. In the current implementation, `src/claims.py` runs after `src/tracker.py` so each extracted claim can be written with the assigned `story_id`.

---

## Data model

### stories

The master record for each unique ongoing story.

```sql
story_id       INTEGER PRIMARY KEY AUTOINCREMENT
canonical_label TEXT NOT NULL      -- best-known name, updated by LLM consolidation
theme          TEXT                -- e.g. "Geopolitics & War", "Economy"
first_seen     DATE NOT NULL
last_seen      DATE NOT NULL
```

### story_daily

Daily aggregate metrics per story.

```sql
story_id       INTEGER NOT NULL
date           DATE NOT NULL
source_count   INTEGER             -- number of unique sources covering the story today
importance_avg REAL
labels_seen    TEXT                -- JSON array of label variants seen today
PRIMARY KEY (story_id, date)
```

### story_observations

Daily observation records — the memory layer.

```sql
observation_id INTEGER PRIMARY KEY AUTOINCREMENT
story_id       INTEGER NOT NULL
date           DATE NOT NULL
label_seen     TEXT
source_count   INTEGER
article_count  INTEGER
importance_avg REAL
summary        TEXT                -- LLM-generated briefing, written back after generation
delta_summary  TEXT                -- "what changed today", written back after generation
novelty_score  REAL                -- planned: not yet populated
created_at     TEXT DEFAULT CURRENT_TIMESTAMP
UNIQUE (story_id, date)
```

### articles

Full article records linked to stories.

```sql
id             TEXT                -- SHA256 of normalized URL
story_id       INTEGER
date           DATE
source         TEXT
title          TEXT
description    TEXT
url            TEXT
published_at   TEXT
importance     INTEGER
```

### article_story_links

Junction table: article ↔ story ↔ observation.

```sql
article_id     TEXT NOT NULL
story_id       INTEGER NOT NULL
observation_id INTEGER
relevance      REAL                -- currently always 1.0; future: partial relevance
PRIMARY KEY (article_id, story_id, observation_id)
```

### article_classifications

Classification cache.

```sql
article_id     TEXT PRIMARY KEY
url            TEXT NOT NULL
title          TEXT
description    TEXT
content_hash   TEXT NOT NULL       -- SHA256 of title + description
theme          TEXT NOT NULL
story_label    TEXT NOT NULL
importance     INTEGER NOT NULL
classifier_model TEXT NOT NULL
prompt_version TEXT NOT NULL
classified_at  TEXT DEFAULT CURRENT_TIMESTAMP
```

### claims

Atomic claim extraction results.

```sql
claim_id       INTEGER PRIMARY KEY AUTOINCREMENT
article_id     TEXT NOT NULL
story_id       INTEGER             -- populated directly (no back-fill; tracker runs first)
claim_text     TEXT NOT NULL
claim_type     TEXT                -- fact|number|quote|prediction|allegation|background
entities       TEXT                -- JSON array of named entities
evidence_span  TEXT                -- the exact sentence from the article supporting this claim
confidence     REAL
prompt_version TEXT
created_at     TEXT DEFAULT CURRENT_TIMESTAMP
```

### claim_extractions

Claim extraction cache records, including zero-claim outputs.

```sql
article_id     TEXT NOT NULL
prompt_version TEXT NOT NULL
story_id       INTEGER
content_hash   TEXT NOT NULL
claims_count   INTEGER NOT NULL
extracted_at   TEXT DEFAULT CURRENT_TIMESTAMP
PRIMARY KEY (article_id, prompt_version)
```

---

## Key design decisions

See `docs/adr/` for full decision records.

| Decision | Choice | Rationale |
|---|---|---|
| Storage | SQLite | Local-first, zero-dependency, sufficient for this scale |
| Story memory | Observation pattern | Daily snapshots allow temporal diffing without event sourcing complexity |
| LLM output | Structured JSON | Enables validation, caching, and downstream processing |
| Claim extraction timing | After tracker | `tracked` articles already carry `story_id`; no NULL → UPDATE needed |
| Claim validation and caching | article_id + prompt_version + content_hash | Stores only schema-valid claims whose evidence span appears in the extraction input; caches zero-claim results, invalidates changed article content, and updates cached claim `story_id` when tracking changes |
| Full-text claims | Selective, not default | Current extraction uses RSS title/description broadly; future full-text use should be limited to cases where evidence quality justifies token cost |
| Story matching | GPT-based label matching | Handles label variation and paraphrasing better than fuzzy string matching |

---

## LLM call summary

| Stage | Prompt | Model | Cached? | Per-run frequency |
|---|---|---|---|---|
| Classification | `CLASSIFIER_PROMPT` | gpt-5.4-mini | Yes, by content_hash | Once per new/changed article |
| Claim extraction | `CLAIMS_PROMPT` | gpt-5.4-mini | Yes, by article_id + prompt_version + content_hash | Once per new or changed article when `--show-evidence` is enabled |
| Same-day consolidation | `CONSOLIDATE_PROMPT` | gpt-5.5 | No | Once per run |
| Cross-day matching | `MATCH_PROMPT` | gpt-5.5 | No | Once per run |
| Briefing generation | `BRIEFING_PROMPT` | gpt-5.5 | No | Once per run (batched) |

---

## Output directories

| Directory | Contents | Git status |
|---|---|---|
| `briefings/` | Daily Markdown briefings | Committed |
| `newspapers/` | Daily newspaper PDFs | Committed |
| `output/` | Local digest Markdown | Ignored |
| `data/stories.db` | SQLite database | Ignored |
| `data/daily/` | Daily JSON article snapshots | Ignored |
| `logs/` | Scheduler logs | Ignored |

---

## Known limitations

- RSS descriptions are often truncated. Evidence spans in claims currently reflect the RSS title/description; fetched full article text is not yet consumed by `src/claims.py`.
- `novelty_score` field exists but is not yet populated.
- `sources` table (with reliability metadata) is planned but not yet implemented — sources are currently stored as bare strings.
- No cost or latency tracking yet (`runs` / `llm_calls` tables are planned).
- No contradiction detection yet.

See `docs/failure-modes.md` for a full list of failure modes.
