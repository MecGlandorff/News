# ADR 0019: Occurrence-backed stored-snapshot replay

**Date:** 2026-07-11

## Status

Accepted.

## Context

The mutable `articles` table was sufficient for current briefings but unsafe for historical reruns. Rewriting an earlier date could delete story rows referenced by later hierarchy and could not reproduce the evidence originally captured.

## Decision

Store append-only `article_occurrences` separately from derived classifications, the current assignment projection, and run-scoped assignment history. If story verification fetches a richer body, preserve that as a second occurrence and assign the enriched snapshot. `python -m src.run --replay YYYY-MM-DD` rebuilds derived tracking rows chronologically from the selected date through the latest replayable date, inside one transaction and without network access.

Replay preserves raw occurrences, claims, completed run history, and reviewed observation prose. It uses the latest currently assigned occurrence for each article/date and fails before deletion if the start date or required classification/parent context is missing.

## Consequences

- Same-day reruns and historical reconstruction share stable occurrence identity.
- Repeated URLs on different days or with changed captured content remain distinguishable.
- Replay reproduces stored interpretations; it does not silently rerun newer prompts against historical material.
- Same-day rebuilding clears only the mutable assignment projection; raw occurrences and run-scoped assignment history remain available for audit.
- Legacy article rows are backfilled as `legacy_metadata_only` occurrences when the tracker schema opens.
