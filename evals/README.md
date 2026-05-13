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

Next, add 5-10 real reviewed cases from recent evidence runs, with full source text stored only where licensing and local use are acceptable. That should happen before using extracted claims for claim-backed source agreement or source-divergence notes.

## Prompt Regression Cases

`evals/datasets/claim_prompt_regressions_2026-05-13.jsonl` records targeted cases from reviewed claim failures. Use it when rerunning the current claim prompt against live or mocked LLM output.

Those cases cover:

- attribution-sensitive reporting that should not be flattened into confirmed fact
- identity background that should not gain unsupported roles
- multi-development sentences that should be split into atomic claims
- broad analysis theses that should not become event facts
