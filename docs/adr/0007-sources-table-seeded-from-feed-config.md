# ADR 0007: Sources table seeded from feed config

**Date:** 2026-05-07
**Status:** Accepted

---

## Context

Phase 3 requires source-aware reasoning before claim-backed agreement or source-divergence notes. Before this change, sources existed only as plain strings on each article row (`articles.source`). That was enough to ingest feeds and render briefings, but it could not support:

- distinguishing a wire copy from independent reporting
- weighting agreement by source reliability
- attaching bias notes that survive across runs
- linking an article back to the feed configuration that produced it

The existing list of feeds lives in `src/scraper.py` as `SOURCES`. Article rows from earlier runs in `data/stories.db` predate any source model and cannot be retroactively classified.

---

## Decision

Add a `sources` table seeded idempotently from `scraper.SOURCES`, and a nullable `articles.source_id` foreign key. Keep `articles.source` as a string so older rows remain readable and so writes do not fail when a feed is renamed.

Schema:

- `sources` columns: `source_id`, `name` (unique), `rss_url`, `language`, `type`, `reliability`, `bias_notes`, `created_at`, `updated_at`.
- `articles.source_id INTEGER REFERENCES sources(source_id)` is added by `_ensure_column` in `src/tracker.py` and populated on insert when a row in `sources` matches the article's source name.
- `seed_sources()` in `src/sources.py` runs every pipeline start. It UPSERTs by `name`, refreshing fields owned by RSS configuration (`rss_url`, `language`, `updated_at`) and preserving fields that may be edited manually later (`reliability`, `bias_notes`).
- `_sources_schema_needs_rebuild()` upgrades pre-existing `sources` tables in place when their constraints predate the current schema. The rebuild is non-destructive: existing rows are copied with sensible defaults.

Defaults for new sources are `type='publication'`, `reliability='unknown'`, `bias_notes=''`.

2026-05-09 follow-up: ADR 0010 adds deterministic source support that consumes `articles.source_id` first and falls back to normalized source names for older rows.

2026-05-14 follow-up: evidence-mode claim-backed source agreement now consumes these source identities for exact repeated claims and conservative numeric divergence. Broader reliability weighting and independent-corroboration logic remain future work.

---

## Rationale

**Source metadata should be a row, not a string.** A string column cannot carry reliability, bias notes, or feed configuration. Once the system needs to weight agreement, it needs structure.

**Old article rows must keep working.** Pre-existing `articles` rows have a `source` string and no `source_id`. Forcing a migration would either invent metadata for old rows or destroy them. Nullable `source_id` lets old rows coexist with new ones; queries that need source metadata can join when the column is present and fall back to the string when it is not.

**Seeding lives next to the feed list.** The configured feeds are already in `src/scraper.py`. Seeding from that single source of truth avoids a separate config file that could drift. Manual edits to reliability or bias_notes survive re-seeding because the UPSERT only touches RSS-owned fields.

**Defaults are honest.** `reliability='unknown'` is explicit rather than fake. Future bias-aware logic can detect the absence and prompt a review instead of trusting an unset value.

**Foundation before consumption.** Wiring `source_id` into source-support logic is a separate decision with its own tradeoffs. Splitting them keeps each step independently testable and reviewable.

---

## Consequences

**Positive:**
- Source reliability and bias notes have a place to live before agreement logic exists
- New article writes carry both `source` and `source_id`, so future joins are cheap
- Manually edited reliability and bias notes survive subsequent runs
- Older databases continue to read without migration

**Negative:**
- Two columns describe the same fact (`articles.source` and `articles.source_id`); writers must keep them in sync
- Older article rows have `source_id IS NULL` permanently and cannot be retroactively classified by feed
- The source list must remain valid Python in `src/scraper.py`, not a runtime config file
- Default `reliability='unknown'` and `bias_notes=''` look populated but carry no signal until they are edited

---

## Review trigger

Revisit this decision when:
- claim-backed source-agreement logic needs more source metadata than source identity
- the configured feed list outgrows a single Python list and needs separate config
- reliability or bias notes need to evolve into an enum or scored field rather than free text
- a content-fingerprint deduplication layer changes how syndicated copies are counted
