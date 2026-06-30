# Project Log

This log records meaningful project changes over time. It is not a release
changelog, test report, or session transcript.

Use this file to preserve the project arc: what changed, why it mattered, and
where to read the detailed rationale. ADRs, issue docs, and code remain the
source of truth for details.

Entries are newest first.

## 2026-06-30

Changed:

- Added shared number normalization for claim derivability and evidence-mode
  source agreement.
- Preserved decimal commas as decimals, so `1,5` no longer normalizes to `15`
  while thousands-separated values such as `1,000` still match `1000`.

Why it matters:

- Numeric grounding is part of the trust layer. A comma-decimal claim must not be
  accepted against integer evidence just because entity and word overlap are
  strong.
- Source-divergence notes now treat comma-decimal versus integer disagreements
  as real numeric divergence instead of silently collapsing them.

Links:

- [Claim derivability ADR](adr/0013-claim-evidence-derivability.md)
- [How it works: derivability gate](how-it-works.md)

## 2026-06-10

Changed:

- Added a static reviewed story-matching eval for Phase 2 of the June roadmap.
- Added seed datasets for cross-day story matches and broader arc assignments.
- Recorded baseline seed rates for false merges, false splits, and false arcs.

Why it matters:

- Story matching and arc assignment now have an inspectable regression harness
  before any prompt, model, or arc-gate changes.
- The first seed makes known failures measurable without adding LLM cost.

Links:

- [June 2026 roadmap](june_roadmap.md)
- [Evaluation harnesses](../evals/README.md)
- [South China Sea false-arc issue](issues/2026-05-28-false-arc-south-china-sea.md)

## 2026-06-09

Retrospective boundary:

- This file was created on 2026-06-09. Entries dated before 2026-06-09 were
  reconstructed retrospectively from GitHub PR metadata, local git history,
  ADRs, issue docs, and maintained project docs. Future entries should be
  written when meaningful project changes happen.

Changed:

- Created this project log as the durable history file for project-level changes.
- Removed superseded first-PR parent-attach code that was no longer used after
  explicit arc assignment shipped.
- Moved the newspaper/PDF rendering stack out of top-level `src/` and into
  `src/rendering/`.
- Marked the classifier-omission contamination issue resolved after the
  classifier retry/hard-fail path and `Uncategorized` quarantine behavior were
  already in place.

Why it matters:

- The repo now has one tracked place to understand the project timeline without
  reading every commit or local assistant note.
- Removing stale matching code makes the current arc-assignment path easier to
  audit.
- Keeping rendering under `src/rendering/` makes the main source tree reflect
  the core pipeline more clearly.

Links:

- [ADR 0015: Parent/child story arcs](adr/0015-important-parent-child-story-arcs.md)
- [ADR 0016: Briefing theme penalties and explicit story arcs](adr/0016-briefing-theme-penalties-and-explicit-story-arcs.md)
- [Classifier omissions issue](../issues/classifier-omissions-uncategorized-memory-contamination.md)

## 2026-06-05

Changed:

- Moved matching fallback policy into config.
- Fixed silent classifier and claim-verifier fallback behavior so missing or
  rejected model output does not quietly become trusted story memory.
- Documented the South China Sea false-arc case as a concrete regression target.
- Added story-match text-fetch totals to observability.

Why it matters:

- Silent fallback paths are dangerous for source-grounded event memory because
  they can turn missing model output into durable false history.
- The South China Sea case gives future arc-matching work a real failure mode
  instead of an abstract quality concern.

Links:

- [GitHub PR #37: Fix silent classifier and claim verifier fallbacks](https://github.com/MecGlandorff/News/pull/37)
- [GitHub PR #36: Classifier omissions audit](https://github.com/MecGlandorff/News/pull/36)
- Commit `bdf3c81` - fix silent classifier and claim verifier fallbacks
- Commit `74c8f88` - move matching fallback policy into config
- Commit `4e1c597` - document South China Sea arc issue

## 2026-05-22

Changed:

- Replaced hard briefing theme exclusions with selection penalties so important
  Tech, Science, and exceptional Sports stories can still appear.
- Implemented explicit story arcs with `story_arcs`, `stories.arc_id`, and
  `stories.parent_story_id`.
- Documented the classifier-omission bug that created an `Uncategorized`
  memory-contamination arc.

Why it matters:

- Briefing selection stopped treating whole themes as impossible, while still
  keeping lower-priority themes demoted.
- Same-story identity stayed strict while broader arc context became explicit.
- The classifier omission audit turned a live memory-contamination failure into
  a documented issue with concrete repair criteria.

Links:

- [ADR 0016: Briefing theme penalties and explicit story arcs](adr/0016-briefing-theme-penalties-and-explicit-story-arcs.md)
- [Classifier omissions issue](../issues/classifier-omissions-uncategorized-memory-contamination.md)
- [GitHub PR #33: Fix/story issue](https://github.com/MecGlandorff/News/pull/33)
- [GitHub PR #34: Document classifier omission audit](https://github.com/MecGlandorff/News/pull/34)

## 2026-05-20

Changed:

- Switched the project default to Python 3.12.

Why it matters:

- The repo stopped depending on older Python behavior and aligned local setup,
  CI, typing, and linting around the target runtime.

Links:

- [GitHub PR #32: Switch project default to Python 3.12](https://github.com/MecGlandorff/News/pull/32)
- Commit `81e9b49` - switch project default to Python 3.12

## 2026-05-16

Changed:

- Added staged parent/child story developments on top of the existing story
  memory tables.
- Started separating concrete event identity from broader parent or arc context.
- Fixed a briefing-selection bug where article-format words could hide an
  important hard-news story.

Why it matters:

- The system no longer had to choose only between corrupting event identity by
  merging adjacent stories or losing continuity by marking every related update
  as unrelated.
- The Modena car-attack review showed that correct tracking is not enough if
  downstream selection filters can accidentally suppress source-backed hard news.

Links:

- [ADR 0015: Parent/child story arcs](adr/0015-important-parent-child-story-arcs.md)
- [GitHub PR #31: Add staged parent/child story developments](https://github.com/MecGlandorff/News/pull/31)
- Commit `6263011` - add staged story developments

## 2026-05-15

Changed:

- Enabled story-match verification by default.
- Reduced cross-day matching cost.
- Added claim/evidence derivability checks with a hybrid deterministic and
  verifier path.
- Added `--include-undated` handling for feed items without usable timestamps.

Why it matters:

- Story reuse became more conservative, which protects event memory from false
  merges.
- Claim extraction became more grounded because important claims must derive
  from evidence spans rather than unsupported model interpretation.
- Date handling became explicit instead of silently dropping every undated feed
  item.

Links:

- [ADR 0013: Claim evidence derivability gate](adr/0013-claim-evidence-derivability.md)
- [ADR 0014: Cross-day story matching cost control](adr/0014-crossday-match-cost-control.md)
- Commit `60ceb6b` - enable story-match verification by default
- Commit `18a3103` - add include-undated feed item option

## 2026-05-11

Changed:

- Added exact LLM response caching for repeatable matching and briefing calls.
- Added the first claim-quality eval posture and source-divergence direction.
- Added engineering baseline docs and run artifacts.

Why it matters:

- Matching, verification, and briefing could reuse exact prior model responses,
  reducing repeated cost.
- The project started treating AI behavior as something to evaluate with cases,
  not just prompts to tune.
- Source divergence was kept conservative instead of jumping to unsupported
  contradiction prose.

Links:

- [ADR 0011: Source divergence instead of a contradiction module](adr/0011-source-divergence-instead-of-contradiction-module.md)
- [ADR 0012: Exact LLM response cache](adr/0012-exact-llm-response-cache.md)
- Commit `a51c8dc` - exact LLM response cache
- Commit `eeb59bf` - claim quality eval and source divergence posture

## 2026-05-09

Changed:

- Shipped the Phase 3 foundation for observability, story-match verification,
  and full-text claim extraction.
- Added model cost reporting and source-support reporting.
- Added full-text claim extraction with a smaller model when evidence mode is
  enabled.

Why it matters:

- Phase 3 moved the project toward inspectable source-grounded behavior before
  making the pipeline more autonomous or expensive.
- Evidence-mode runs could extract claims from fuller article context while
  keeping ordinary runs cheaper.

Links:

- [ADR 0009: Full-text claim extraction with nano](adr/0009-full-text-claim-extraction-with-nano.md)
- [ADR 0010: Source support and cost reporting](adr/0010-source-support-and-cost-reporting.md)
- Commit `7b9cba6` - Phase 3 foundation
- Commit `f414379` - source observability costs

## 2026-05-07

Changed:

- Added run and LLM observability tables.
- Added the source metadata table seeded from RSS feed config.
- Aligned Phase 3 documentation around source modeling and observability.

Why it matters:

- Pipeline runs became inspectable by article counts, model calls, schema
  failures, latency, token use, and cache behavior.
- Sources gained durable metadata instead of existing only as article strings.

Links:

- [ADR 0006: Run and LLM observability](adr/0006-run-and-llm-observability.md)
- [ADR 0007: Sources table seeded from feed config](adr/0007-sources-table-seeded-from-feed-config.md)
- Commit `ffc26cd` - Phase 3 observability
- Commit `2ac1d2c` - Phase 3 source metadata

## 2026-05-05

Changed:

- Refactored the V2 story-memory pipeline.
- Hardened claim grounding and story matching.

Why it matters:

- The project moved from a daily briefing generator toward a persistent event
  memory system that can compare today's stories against prior observations.

Links:

- Commit `c3fa2c1` - refactor V2 story memory pipeline
- Commit `d1c6bf1` - harden claim grounding and story matching

## 2026-05-02

Changed:

- Added the V2 story-memory prototype.
- Recorded core architecture decisions: local-first SQLite, observation memory
  before vector search, structured JSON LLM outputs, selective full-text claim
  extraction, and no placeholder novelty score.

Why it matters:

- These decisions set the project's direction: local-first, source-grounded,
  structured, inspectable, and conservative about adding unsupported scores.

Links:

- [ADR 0001: Local-first SQLite storage](adr/0001-local-first-sqlite.md)
- [ADR 0002: Story memory via observation pattern, not vector search](adr/0002-story-memory-before-vector-search.md)
- [ADR 0003: Structured JSON outputs for all LLM calls](adr/0003-structured-llm-outputs.md)
- [ADR 0004: Selective full-text claim extraction](adr/0004-selective-full-text-claim-extraction.md)
- [ADR 0005: No placeholder novelty score](adr/0005-no-placeholder-novelty-score.md)
- Commit `ac1399c` - build V2 story memory prototype

## 2026-05-01

Changed:

- Added story delta summaries to briefings.

Why it matters:

- Briefings started answering the central product question more directly:
  what changed since the previous run?

Links:

- Commit `331ad40` - add story delta summaries to briefings

## 2026-04-28

Changed:

- Added newspaper-style PDF output.

Why it matters:

- The project gained a second polished artifact format while still using the
  same underlying briefing package.

Links:

- Commit `defd384` - add newspaper PDF output

## 2026-04-26

Changed:

- Published the initial news briefing project.
- Added existing briefing Markdown files.
- Prevented empty briefing summaries.
- Clarified briefing trend labels.
- Switched backbone models to GPT-5.5.

Why it matters:

- This established the first usable local news briefing workflow and the first
  iteration of the generated briefing artifacts.

Links:

- Commit `a7f3c8d` - publish news briefing project
- Commit `9abba4c` - prevent empty briefing summaries
- Commit `e8a2ce6` - clarify briefing trend labels
- Commit `e0fd679` - switch backbone models to GPT-5.5
