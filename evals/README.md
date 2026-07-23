# Evaluations

This directory contains small, inspectable evaluation harnesses for the news pipeline.

The goal is not a large benchmark. The goal is to catch obvious regressions in the behaviors that make the project source-grounded event memory.

## Claim Quality Eval

Run:

```bash
python -m evals.run_claim_quality_eval
```

By default this reads:

```text
evals/datasets/golden_claims.jsonl
```

and writes a JSON report to:

```text
evals/reports/
```

Use a custom output path when comparing reports:

```bash
python -m evals.run_claim_quality_eval \
  --dataset evals/datasets/golden_claims.jsonl \
  --output evals/reports/claim_quality_manual.json
```

This makes real OpenAI calls with the configured claim model and may incur API cost.

## What It Compares

The eval runs the same claim prompt and validation path twice for each case:

| Variant | Input | What it tests |
|---|---|---|
| `rss` | title plus RSS description | Cheap fallback quality |
| `full_text` | title, RSS description, and fetched article body | Evidence-run quality when body text is available |

The `full_text` variant is not body-only. It includes the RSS fields plus body text, matching production evidence runs.

## What It Measures

Each report records:

- article coverage: expected claims found out of all expected claims for the article
- available coverage: expected claims found out of claims that were actually available in that input variant
- evidence valid rate: model claims whose evidence span appears in the input
- duplicate claim count
- prompt and completion tokens when the API returns usage
- estimated EUR cost when pricing is available
- latency in milliseconds
- verifier calls, accepts/rejects, validation latency, and verifier tokens/cost when usage is available

Expected and extracted claims use maximum one-to-one matching, so one broad extracted claim cannot receive credit for several expected claims.

The difference that matters most right now is:

```text
full_text article coverage - rss article coverage
```

That shows whether full text adds grounded claims that RSS-only extraction could not see. If full text only increases tokens and latency without improving article coverage or evidence quality, it should not become broader or more automatic.

## Dataset Format

Each JSONL row is one case:

```json
{
  "case_id": "example",
  "article": {
    "title": "Title from RSS",
    "description": "Description from RSS",
    "text": "Fetched article body text"
  },
  "expected_claims": [
    {
      "id": "specific_claim",
      "required_terms": ["named entity", "important number"],
      "available_in": ["full_text"]
    }
  ]
}
```

`available_in` can contain `rss`, `full_text`, or both. Use `rss` only when the title or description contains the needed evidence. Use `full_text` when the claim depends on article body text.

## How To Read Results

Good full-text impact looks like:

- higher article coverage than RSS-only
- similar or better evidence valid rate
- few duplicates
- token and latency increase that is acceptable for evidence runs
- representative failures that are understandable from the report

Bad full-text impact looks like:

- more claims but no better expected-claim coverage
- many claims dropped because evidence spans are not in the input
- duplicate claims from long article bodies
- latency or cost increase without visible grounding improvement

## What Is Still Weak

The first dataset is intentionally small and fixture-style. It proves the harness and documents the scoring contract, but it is not yet enough to decide policy for all sources.

The biggest open gap is **real reviewed verifier accuracy**. The harness now executes the production validation path and records verifier work, but the checked-in dataset remains fixture-style. Add reviewed paraphrase cases where verifier accept/reject is the deciding signal before making the verifier or claim-backed agreement more authoritative.

Next, follow the [Phase 3 closure plan](../docs/phase3-closure-plan.md): collect a short daily run series and add 5-10 real reviewed cases from its evidence runs. Keep raw fetched article bodies under the ignored `evals/local/` directory unless redistribution is clearly permitted. Review the shipped similar-claim and date/status/attribution comparisons on those cases before loosening their deterministic matching or making evidence extraction more automatic.

## Saved-Snapshot Matching Reconstruction

The reconstruction harness replays stored occurrence and classification snapshots
through the production matching path in isolated SQLite copies:

```bash
python -m evals.run_matching_reconstruction \
  --start-date 2026-07-21 \
  --end-date 2026-07-22 \
  --work-dir evals/local/matching-reconstruction-manual \
  --sanitized-report evals/reports/phase3_matching_reconstruction_manual.md \
  --confirm-api-cost
```

The work directory must not already exist. The harness:

- opens `data/stories.db` read-only and creates a SQLite backup under the ignored
  `evals/local/` directory
- rebuilds the selected dates independently for reasoning efforts `none` and `low`
- never replaces the active database
- checks SQLite integrity and foreign keys for each reconstruction
- scores reviewed same-day, same-story, and same-arc cases
- records model calls, tokens, latency, and estimated EUR matching cost
- reports non-ok runs, LLM errors, schema failures, and application retries
- requires `--confirm-api-cost` because it makes real OpenAI calls

Review rows can use `review_status: "insufficient_evidence"` with a required
`evidence_gap`. Such cases remain visible and fail-closed but are excluded from recall
and corruption scoring; this prevents missing source metadata from being mislabeled as
a model-quality failure.

The checked-in [July 23 report](reports/phase3_matching_reconstruction_2026-07-23.md)
replayed 158 occurrences and reviewed 16 cases. Of 15 scorable cases, `low` had zero
corrupting accepts and recovered four of five clear positives for EUR 0.1920. `none`
had one corrupting accept and recovered three for EUR 0.1793. Both efforts had zero
LLM errors and schema failures. The approved gate therefore selected `low`; the active
database remained unchanged.

## Prompt Regression Cases

`evals/datasets/claim_prompt_regressions_2026-05-13.jsonl` records targeted cases from reviewed claim failures. Use it when rerunning the current claim prompt against live or mocked LLM output.

Those cases cover:

- attribution-sensitive reporting that should not be flattened into confirmed fact
- identity background that should not gain unsupported roles
- multi-development sentences that should be split into atomic claims
- broad analysis theses that should not become event facts

## Story Matching Eval

Run:

```bash
python -m evals.run_story_match_eval
```

By default this reads:

```text
evals/datasets/story_match_cases.jsonl
evals/datasets/arc_assignment_cases.jsonl
```

and writes a JSON report to:

```text
evals/reports/
```

Use `--no-write` when you only want the headline rates:

```bash
python -m evals.run_story_match_eval --no-write
```

This eval does not make OpenAI calls. It replays each reviewed historical
response through the current story-match or arc-assignment acceptance function,
then compares that executable result with the reviewed expectation. It catches
gate regressions, but it does not measure current live prompt/model quality.

## What It Measures

The story-match dataset scores cross-day same-story decisions:

- false merge: observed accepted, reviewer expected new story
- false split: observed rejected, reviewer expected same story
- false-merge rate: false merges out of observed accepted matches
- false-split rate: false splits out of expected matches

The arc-assignment dataset scores broader story-arc attachments:

- false arc: observed attached to an arc, reviewer expected `NEW_ARC`
- missed arc: observed `NEW_ARC`, reviewer expected an existing arc
- false-arc rate: false arcs out of observed arc attachments

The first checked-in seed is intentionally small and failure-heavy. Use it as a
regression baseline and review queue, not as a representative production rate.

## Story Dataset Format

Each JSONL row is one reviewed same-story case:

```json
{
  "case_id": "example",
  "case_type": "story_match",
  "source": "story_match_decisions 2026-05-28",
  "run_date": "2026-05-28",
  "today_label": "Today label",
  "candidate_label": "Candidate memory label",
  "observed_decision": {
    "accepted": true,
    "relationship": "same_event",
    "confidence": "high"
  },
  "expected_decision": {
    "accepted": true,
    "relationship": "same_event"
  },
  "review_note": "Why the expected label is correct."
}
```

## Arc Dataset Format

Each JSONL row is one reviewed arc-assignment case:

```json
{
  "case_id": "example",
  "case_type": "arc_assignment",
  "source": "story_developments 2026-05-27",
  "run_date": "2026-05-27",
  "today_label": "Today label",
  "candidate_arc_label": "Candidate arc label",
  "observed_decision": {
    "accepted": true,
    "relationship": "same_arc",
    "confidence": "high"
  },
  "expected_decision": {
    "accepted": false,
    "relationship": "new_arc"
  },
  "review_note": "Why this should or should not attach."
}
```

## How To Read Results

High false-merge or false-arc rates mean the system is corrupting story memory
by attaching distinct events to the same story or arc. High false-split or
missed-arc rates mean the system is losing continuity. For the current Phase 2
seed, the false-arc failures matter most because Phase 3b must decide whether
to fix or simplify the arc layer.
