# ADR 0021: Domain package boundaries

**Date:** 2026-07-12

## Status

Accepted.

## Context

Phase 3 established replay, evidence validation, source comparison, and detailed
run reporting. The implementation was protected by tests, but several modules
had grown past 700–1,600 lines and mixed schema setup, orchestration, model
calls, deterministic policy, queries, and rendering.

A large rewrite would make trust-sensitive behavior difficult to review. Keeping
the monoliths would make later changes equally risky.

## Decision

Organize the implementation around four stable domain packages:

- `src/observability/` owns run state, LLM-call records, audits, cost summaries,
  and report rendering.
- `src/tracker/` owns story orchestration, matching, persistence, immutable
  occurrences, and stored-snapshot replay.
- `src/claims/` owns extraction inputs, derivability, verifier behavior, caching,
  and claim persistence.
- `src/briefing/` owns selection, model generation, deterministic grounding,
  package assembly, and Markdown rendering.

Package roots expose the small orchestration APIs used by `src/run.py`. Internal
submodules receive paths, clients, callbacks, or connections explicitly where
that prevents hidden coupling. Cross-domain submodule imports are limited to the
few real data contracts: tracker occurrences for claim foreign keys, tracker
replay for the CLI, and briefing selection for observability audits.

The refactor preserves runtime dictionaries, SQLite schema, prompts, models,
cache keys, CLI flags, output formats, and public generated artifacts. Removed
top-level modules are not kept as permanent compatibility shims.

## Consequences

- Trust-sensitive policy can be reviewed separately from persistence and prose.
- Tests mirror the owning domains while pipeline and CLI tests remain at the
  repository root.
- Import-boundary tests reject removed module paths and accidental private
  cross-domain dependencies.
- Package facades add a small amount of indirection, but avoid a service
  container, repository framework, or one-function modules.
- Future behavior changes should target the owning submodule and remain separate
  from structural refactors.
