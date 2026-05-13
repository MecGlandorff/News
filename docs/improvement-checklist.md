# Improvement Checklist

This document is the repo's practical hardening plan.
- what the system already does
- where the current weaknesses are
- what should be improved next
- why the order of work matters

This file tracks the implementation work needed to make decisions real, inspectable, and measurable.

It follows the writing standard in `docs/communication.md`: explain what exists now, what is weak now, what should happen next, why it comes next, and what done looks like.

## What the system already does

These pieces are already in place and should be protected as the project evolves.

- [x] Tracks stories across days instead of only summarizing articles
- [x] Stores local story memory in SQLite
- [x] Extracts structured claims with evidence spans
- [x] Validates LLM JSON outputs before using them
- [x] Caches article classification results
- [x] Caches claim extraction results, including zero-claim outputs
- [x] Produces Markdown briefings and newspaper-style PDFs

## What still needs hardening

The current prototype is directionally strong, but several important parts are still incomplete or only partially implemented.

- [ ] Full-text claim extraction is enabled for evidence runs, and its cost/latency is visible; the repeatable quality harness and prompt-regression cases exist, but real reviewed current-prompt cases still need to be run
- [x] Run observability covers token use, latency, cache hits, schema failures, retries, EUR estimates, and scraper duplicate/failure counts
- [x] Source metadata is modeled as a first-class table, and source identity is used before source-name fallback
- [ ] Source agreement is surfaced in the briefing, but not yet backed by a dedicated comparison layer
- [ ] Source-divergence notes are not implemented; a dedicated contradiction module/table is no longer Phase 3 scope
- [ ] Evaluation coverage is still early; claim-quality comparison is operational, while story, citation, temporal, and source-divergence evals are still planned

## Priority order

The order below matters. The project should measure its pipeline before making expensive behavior broader by default.

- [x] 1. Add observability tables for runs and LLM calls
- [x] 2. Add a pipeline report that shows counts, latency, and estimated cost by stage
- [x] 3. Define and document full-text claim extraction for evidence runs
- [x] 4. Implement full-text claim extraction behind `--show-evidence`
- [x] 5. Add a repeatable claim-quality comparison harness
- [ ] 6. Run real reviewed claim-quality cases and decide whether full-text impact is worth the cost
- [ ] 7. Add stronger source agreement and lightweight source-divergence handling

## 1. Observability

The project should be able to explain what a pipeline run cost, how long each stage took, and where failures happened.

### Runs table

- [x] Add a `runs` table
- [x] Track `run_id`
- [x] Track `started_at` and `finished_at`
- [x] Track the pipeline date being processed
- [x] Track returned article count
- [x] Track duplicate count
- [x] Track saved claim count
- [x] Track tracked story count
- [x] Track failed fetch count
- [x] Track LLM call count
- [x] Track schema-validation failure count
- [x] Track retry count
- [x] Track estimated cost
- [x] Track total latency in milliseconds

### LLM call logging

- [x] Add an `llm_calls` table
- [x] Log `run_id`
- [x] Log `task_type` such as classification, claim extraction, tracking, or briefing
- [x] Log model name
- [x] Log input tokens
- [x] Log output tokens
- [x] Estimate cost from logged token usage and explicit pricing
- [x] Log latency in milliseconds
- [x] Log cache-hit totals where relevant
- [x] Log whether schema validation passed
- [x] Log retry count
- [x] Log error type or error message where relevant

### Pipeline report

- [x] Add a `--pipeline-report` CLI flag
- [x] Print article, claim, and story counts by stage
- [x] Print estimated cost by stage
- [x] Print total latency
- [x] Break out claim extraction cost separately
- [x] Break out briefing generation cost separately
- [x] Make the report work when `--db-off` is used

## 2. Claim extraction quality

Claim extraction is already structured and validated. Evidence runs now fetch full article text and use it when available, while preserving the RSS title/description fallback.

### Current protected behavior

These behaviors already exist and should remain true after refactoring:

- [x] Use structured JSON output for claims
- [x] Validate claims before storage
- [x] Require the evidence span to appear in the extraction input
- [x] Cache by `article_id + prompt_version`
- [x] Use a content hash to invalidate stale claim results
- [x] Cache zero-claim results
- [x] Keep cached claims aligned with the current `story_id`

### Full-text claim extraction

The richer path is gated behind `--show-evidence`; ordinary runs do not extract claims.

- [x] Implement full-text claim extraction for evidence runs
- [x] Keep ordinary runs claim-free unless `--show-evidence` is enabled
- [x] Fetch full text when `--show-evidence` is enabled
- [x] Only use full text when fetched article text is actually present and usable
- [ ] Record which input source was used for each extraction: `rss` or `full_text`
- [x] Add a harness that compares RSS-only and full-text claim extraction
- [ ] Measure quality improvement against token and latency cost on real reviewed cases

### Future control policy

If evidence runs become too expensive, the repo should explicitly define which articles qualify for richer claim extraction.

- [ ] Decide whether full text should be limited by article importance
- [ ] Decide whether full text should be limited by final briefing inclusion
- [ ] Decide whether both rules should be supported
- [ ] Define what happens when an article qualifies but body text is missing
- [ ] Define what happens when fetched text is too short, poor quality, or fetch failed

### Fallback behavior

This should be documented clearly so reviewers can understand how the system degrades when richer evidence input is unavailable.

- [x] Document that the pipeline falls back to RSS title/description when full text is unavailable
- [x] Document whether fallback is automatic or treated as a warning
- [ ] Count fallback events once observability exists
- [ ] Ensure fallback does not break the run

## 3. Source modeling

Right now sources are mostly plain strings. That is enough to ingest feeds, but not enough for source-aware reasoning.

- [x] Add a `sources` table
- [x] Seed it from the configured RSS source list
- [x] Add source `type` such as wire, publication, blog, company, government, or unknown
- [x] Add source `reliability`
- [x] Add optional `bias_notes`
- [x] Add nullable `articles.source_id` while preserving raw source names for compatibility
- [x] Use `articles.source_id` in source-support logic, with a source-name fallback for older rows

## 4. Source agreement and source-divergence handling

The briefing currently surfaces agreement-style labels, but those labels are still prompt-level signals rather than outputs of a dedicated comparison layer.

### Source agreement

- [ ] Compare claims within a story across multiple sources
- [ ] Distinguish repeated reporting from independent corroboration
- [ ] Mark single-source claims clearly
- [ ] Surface source agreement using claim-level backing rather than prompt-only synthesis

### Source divergence

- [ ] Compare claim pairs for different numbers, dates, statuses, or attributions when the source-agreement layer already has comparable claims
- [ ] Record lightweight source-divergence notes in the comparison output
- [ ] Avoid a dedicated contradiction module or `contradictions` table in Phase 3
- [ ] Surface divergence cautiously as a note, not as confirmed contradiction prose

## 5. Briefing quality

The end product should read like an auditable intelligence artifact rather than a generic article summary.

- [ ] Ensure major briefing statements can be traced back to source evidence
- [ ] Avoid confident prose that is not clearly supported
- [ ] Make uncertainty visible rather than smoothing it away
- [ ] Distinguish reported claims from confirmed facts
- [ ] Surface open questions consistently
- [ ] Improve source agreement labels so they are backed by the underlying data model

## 6. Evaluation

The repo should be able to show that key AI behaviors are improving rather than merely changing.

- [x] Add an `evals/` directory
- [x] Add a small golden dataset for claim extraction
- [ ] Add a story-clustering evaluation set
- [ ] Add a citation-support evaluation set
- [ ] Add a temporal-diffing evaluation set
- [x] Add metrics for evidence support rate
- [ ] Measure the quality lift from full-text claims on reviewed real cases
- [ ] Measure missed-claim recall from full-text claims
- [x] Measure the token-cost increase from full-text claims
- [x] Measure the latency increase from full-text claims
- [x] Write an evaluation README with success criteria

## 7. Documentation alignment

The repo already communicates a strong architectural idea. The remaining work is to keep implementation details aligned with that story.

- [x] Keep the README aligned with actual claim-extraction behavior
- [x] Update architecture docs when observability lands
- [x] Update model-behavior docs when claim-input rules change
- [x] Update ADR 0004 only if the decision changes or the implementation plan needs clarification
- [ ] Add one polished sample output that demonstrates evidence, uncertainty, and story deltas together

## Short version

If only a few improvements happen next, they should be these:

- [x] Add run-level observability
- [x] Add `--pipeline-report`
- [x] Implement full-text claim extraction for evidence runs
- [ ] Back source agreement with claim-level comparison
- [ ] Add evals that measure quality against cost and latency
