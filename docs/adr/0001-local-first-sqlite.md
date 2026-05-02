# ADR 0001: Local-first SQLite storage

**Date:** 2026-05-02  
**Status:** Accepted

---

## Context

The pipeline needs persistent storage for story memory across runs. Options considered:

- SQLite (local file)
- PostgreSQL (local or hosted)
- JSON files only
- Vector database (e.g. Chroma, Weaviate)

The primary use case is a single-user, single-machine pipeline that runs once or twice daily.

---

## Decision

Use SQLite via Python's standard `sqlite3` module.

---

## Rationale

**Zero infrastructure.** SQLite requires no server process, no credentials, no network, and no Docker setup. A single `stories.db` file contains all pipeline state.

**Sufficient at this scale.** The pipeline processes ~200–300 articles per day. Even at 10× growth, SQLite handles this comfortably. Query patterns are simple: point lookups by story_id, date-range scans, small joins.

**Local-first is a feature.** Runtime data (the database, daily JSON snapshots, logs) is git-ignored by design. Only published outputs (Markdown briefings, PDFs) are committed. This keeps the repo clean and means the pipeline works offline.

**Python-native.** `sqlite3` is in the standard library. No dependency to install, no ORM to configure.

---

## Consequences

**Positive:**
- No infrastructure to manage or secure
- Database is a single portable file
- Easy to inspect with any SQLite browser
- Easy to back up (`cp data/stories.db data/stories.db.bak`)
- Schema evolution via `ALTER TABLE` is straightforward for a prototype

**Negative:**
- No concurrent write access (one writer at a time)
- No built-in full-text search (would need FTS5 extension or external index)
- Migrations are manual (no migration framework)
- Not a natural fit if the system grows to multiple machines or users

---

## Alternatives rejected

**PostgreSQL:** Requires a running server. Unnecessary operational overhead for a single-user prototype.

**JSON files only:** Querying story history across dates would require loading and scanning all files. No good support for transactional writes.

**Vector database:** Useful for semantic retrieval, but story matching is currently handled by the tracker LLM prompt. A vector DB adds infrastructure without clear benefit until retrieval becomes a bottleneck.

---

## Review trigger

Revisit this decision if:
- The pipeline needs to run on multiple machines simultaneously
- Full-text semantic search becomes a core requirement
- The story count exceeds ~100,000 records with complex query patterns
