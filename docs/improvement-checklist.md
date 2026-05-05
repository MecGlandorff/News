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

- [ ] Claim extraction still relies on RSS title/description rather than article body text
- [ ] There is no run-level observability for token use, cost, or latency
- [ ] Source metadata is not yet modeled as a first-class table
- [ ] Source agreement is surfaced in the briefing, but not yet backed by a dedicated comparison layer
- [ ] Contradiction detection is not implemented
- [ ] Evaluation coverage is still mostly planned rather than operational

## Priority order

The order below matters. The project should measure its pipeline before making expensive behavior broader by default.

- [ ] 1. Add observability tables for runs and LLM calls
- [ ] 2. Add a pipeline report that shows counts, cost, and latency by stage
- [ ] 3. Define and document selective full-text claim extraction rules
- [ ] 4. Implement selective full-text claim extraction for the most valuable stories
- [ ] 5. Add stronger source agreement and contradiction handling
- [ ] 6. Add evaluation coverage for quality, cost, and latency tradeoffs

## 1. Observability

The project should be able to explain what a pipeline run cost, how long each stage took, and where failures happened.

### Runs table

- [ ] Add a `runs` table
- [ ] Track `run_id`
- [ ] Track `started_at` and `finished_at`
- [ ] Track the pipeline date being processed
- [ ] Track fetched article count
- [ ] Track duplicate count
- [ ] Track extracted claim count
- [ ] Track tracked story count
- [ ] Track failed fetch count
- [ ] Track LLM call count
- [ ] Track schema-validation failure count
- [ ] Track retry count
- [ ] Track estimated cost
- [ ] Track total latency in milliseconds

### LLM call logging

- [ ] Add an `llm_calls` table
- [ ] Log `run_id`
- [ ] Log `task_type` such as classification, claim extraction, tracking, or briefing
- [ ] Log model name
- [ ] Log input tokens
- [ ] Log output tokens
- [ ] Log estimated cost
- [ ] Log latency in milliseconds
- [ ] Log cache-hit status where relevant
- [ ] Log whether schema validation passed
- [ ] Log retry count
- [ ] Log error type or error message where relevant

### Pipeline report

- [ ] Add a `--pipeline-report` CLI flag
- [ ] Print article, claim, and story counts by stage
- [ ] Print estimated cost by stage
- [ ] Print latency by stage
- [ ] Break out claim extraction cost separately
- [ ] Break out briefing generation cost separately
- [ ] Make the report work when `--db-off` is used

## 2. Claim extraction quality

Claim extraction is already structured and validated, but the evidence quality is limited because the extractor currently works from RSS title and description rather than full article text.

### Current protected behavior

These behaviors already exist and should remain true after refactoring:

- [x] Use structured JSON output for claims
- [x] Validate claims before storage
- [x] Require the evidence span to appear in the extraction input
- [x] Cache by `article_id + prompt_version`
- [x] Use a content hash to invalidate stale claim results
- [x] Cache zero-claim results
- [x] Keep cached claims aligned with the current `story_id`

### Selective full-text claim extraction

The next step is not "use full text everywhere." The next step is "use full text where it materially improves the final intelligence artifact."

- [ ] Implement selective full-text claim extraction
- [ ] Keep RSS title/description as the default broad extraction path
- [ ] Only use full text when `--fetch-article-text` is enabled
- [ ] Only use full text when fetched article text is actually present and usable
- [ ] Record which input source was used for each extraction: `rss` or `full_text`
- [ ] Measure quality improvement before expanding beyond the selected scope

### Selection policy

The repo should explicitly define which articles qualify for richer claim extraction.

- [ ] Decide whether full text is triggered by article importance
- [ ] Decide whether full text is triggered by final briefing inclusion
- [ ] Decide whether both rules should be supported
- [ ] Define what happens when an article qualifies but body text is missing
- [ ] Define what happens when fetched text is too short, poor quality, or fetch failed

### Fallback behavior

This should be documented clearly so reviewers can understand how the system degrades when richer evidence input is unavailable.

- [ ] Document that the pipeline falls back to RSS title/description when full text is unavailable
- [ ] Document whether fallback is automatic or treated as a warning
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
- [ ] Use `articles.source_id` in source-agreement logic, with a source-name fallback for older rows

## 4. Source agreement and contradiction handling

The briefing currently surfaces agreement-style labels, but those labels are still prompt-level signals rather than outputs of a dedicated comparison layer.

### Source agreement

- [ ] Compare claims within a story across multiple sources
- [ ] Distinguish repeated reporting from independent corroboration
- [ ] Mark single-source claims clearly
- [ ] Surface source agreement using claim-level backing rather than prompt-only synthesis

### Contradictions

- [ ] Add a contradiction-detection module
- [ ] Add a `contradictions` table
- [ ] Compare claims for conflicts in number, date, status, attribution, or causality
- [ ] Record contradiction severity
- [ ] Surface contradictions explicitly in the briefing

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

- [ ] Add an `evals/` directory
- [ ] Add a small golden dataset for claim extraction
- [ ] Add a story-clustering evaluation set
- [ ] Add a citation-support evaluation set
- [ ] Add a temporal-diffing evaluation set
- [ ] Add metrics for evidence support rate
- [ ] Measure the quality lift from selective full-text claims
- [ ] Measure the token-cost increase from selective full-text claims
- [ ] Measure the latency increase from selective full-text claims
- [ ] Write an evaluation README with success criteria

## 7. Documentation alignment

The repo already communicates a strong architectural idea. The remaining work is to keep implementation details aligned with that story.

- [ ] Keep the README aligned with actual claim-extraction behavior
- [ ] Update architecture docs when observability lands
- [ ] Update model-behavior docs when claim-input rules change
- [ ] Update ADR 0004 only if the decision changes or the implementation plan needs clarification
- [ ] Add one polished sample output that demonstrates evidence, uncertainty, and story deltas together

## Short version

If only a few improvements happen next, they should be these:

- [ ] Add run-level observability
- [ ] Add `--pipeline-report`
- [ ] Implement selective full-text claim extraction for the most valuable stories
- [ ] Back source agreement with claim-level comparison
- [ ] Add evals that measure quality against cost and latency
