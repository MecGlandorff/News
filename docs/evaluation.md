# Evaluation Plan

The project should evaluate the behaviors that make it more than an article summarizer: story clustering, claim extraction, evidence grounding, temporal diffing, claim-backed source agreement/source divergence, and briefing quality.

Use [how-it-works.md](how-it-works.md) as the current behavior baseline before turning any item here into an eval.

The near-term goal is not a large benchmark. The goal is a small, inspectable eval harness that catches obvious regressions before adding more AI behavior.

---

## Priority evals

### 1. Story clustering

Question: did the system group articles into the right ongoing story?

Useful checks:

- pairwise precision / recall / F1 on article pairs
- false-merge examples where similar topics are distinct stories
- false-split examples where the same event receives multiple labels

Current motivating failure: a sample output grouped an "OpenAI Shooter Lawsuit" memory with White House Correspondents' Dinner shooting coverage. That should become a golden false-merge case.

Second motivating failure: Run #2 on 2026-05-07 attached Al Jazeera's `Palestinians expose torture and sexual violence in Israeli detention` to `Gaza flotilla raid`. The correct behavior is not to reuse the flotilla story, because the article is adjacent Gaza/Israel detention context rather than the same flotilla event.

For story-match verification, evaluate both the final match result and the stored verifier decision:

- accepted vs rejected candidate
- `relationship`
- `confidence`
- continuity evidence quality
- reject reason quality
- whether full article text changed the decision compared with RSS-only context

Current harness:

```bash
python -m evals.run_story_match_eval
```

This is an executable acceptance-gate replay. It reads reviewed rows from
`evals/datasets/story_match_cases.jsonl` and
`evals/datasets/arc_assignment_cases.jsonl`, runs the stored response shape
through the current acceptance code, and compares that result with the reviewed
expectation. It does not call an LLM or measure current prompt/model quality.
The first seed is small and failure-heavy, so use it as a gate regression and
review queue, not as a representative production rate.

### 2. Claim extraction

Question: did the system extract source-supported atomic claims?

Useful checks:

- valid JSON shape
- allowed `claim_type`
- non-empty `claim_text`
- evidence span present in article input when possible
- confidence is numeric and bounded
- no duplicate claims within one article

Current harness:

```bash
python -m evals.run_claim_quality_eval
```

This compares two input variants for the same configured claim prompt and model:

| Variant | Input | Purpose |
|---|---|---|
| `rss` | title plus RSS description | Measures the cheap fallback path |
| `full_text` | title, RSS description, and fetched body text | Measures evidence-run quality when body text is available |

The important distinction is between:

- available coverage: claims found out of claims visible in that input variant
- article coverage: claims found out of all expected claims for the article

RSS-only extraction can have good available coverage while still having lower article coverage because the feed summary did not contain the relevant source detail. Full-text extraction is only worth the extra cost when it improves article coverage, preserves evidence validity, and does not create many duplicates.

### 3. Citation and evidence accuracy

Question: can every important generated statement be traced back to source material?

Useful checks:

- supported / unsupported / missing evidence labels
- briefing claims that lack matching article claims
- evidence spans that do not appear in the source input
- high-confidence claims from weak or single-source reporting

### 4. Temporal diffing

Question: does `delta_summary` describe what changed today rather than repeating old context?

Useful checks:

- new vs repeated development classification
- stale previous-context leakage
- "First detected today" used only when no previous context exists
- continuing stories correctly compare against the last observation

### 5. Briefing quality

Question: is the final briefing useful, concise, and honest about uncertainty?

Useful rubric dimensions:

- current development is clear
- source support is visible
- uncertainty is not flattened
- source divergence is surfaced cautiously when claim comparison supports it
- "what to watch next" does not invent unsupported predictions
- prose remains concise

---

## Eval directory

The first checked-in harness is the RSS-vs-full-text claim-quality eval:

```bash
python -m evals.run_claim_quality_eval
```

It reruns the configured claim prompt on small golden cases and compares RSS-only
input against RSS plus full article text. It records coverage, evidence validity,
duplicates, token use, latency, and estimated cost.

`evals/datasets/claim_prompt_regressions_2026-05-13.jsonl` records targeted
cases from the first reviewed failures. Those cases should be used when rerunning
the current claim prompt against live or mocked LLM output.

Planned broader shape:

```text
evals/
  datasets/
    claim_prompt_regressions_2026-05-13.jsonl
    arc_assignment_cases.jsonl
    golden_claims.jsonl
    article_pairs.jsonl
    story_match_cases.jsonl
    golden_story_clusters.jsonl
    golden_citations.jsonl
    temporal_diff_cases.jsonl
  reports/
  run_claim_quality_eval.py
  README.md
```

Implemented first:

```text
evals/
  datasets/
    arc_assignment_cases.jsonl
    golden_claims.jsonl
    story_match_cases.jsonl
  reports/
  run_claim_quality_eval.py
  run_story_match_eval.py
  README.md
```

Keep datasets small at first. Ten high-quality examples per behavior are more useful than a large noisy fixture set.

---

## Metrics

| Subsystem | Metric |
|---|---|
| Article deduplication | precision / recall / F1 |
| Story clustering | pairwise precision / recall / F1 |
| Story-match verification | accepted / rejected accuracy, false-merge rate, false-split rate |
| Story-arc assignment | false-arc rate, missed-arc rate |
| Claim extraction | validity / coverage / semantic match |
| Citation accuracy | supported / unsupported / missing |
| Temporal diffing | new-vs-repeated accuracy |
| Source divergence | precision-oriented review of claim pairs with different numbers, statuses, or attributions |
| Briefing quality | rubric score with cited examples |
| Cost | cost per run / cost per 100 articles |
| Latency | seconds per stage |

---

## Acceptance standard

Before adding a major AI subsystem, define at least one way to evaluate it.

Examples:

- before source agreement detection, create claim-pair examples where sources agree, differ, or merely repeat the same wire copy
- before loosening source-divergence matching, add real number/date/status/attribution examples with expected labels
- after enabling story-match verification by default, keep reviewing accepted and rejected match cases from recent newspapers before making the verifier more permissive
- before making evidence extraction part of ordinary runs or making claim-backed agreement more authoritative, measure claim quality improvement against token and latency increase

---

## Reporting

Eval reports should be static files under `evals/reports/`.

Each report should include:

- date
- git commit or working-tree note
- dataset version
- model names
- prompt versions
- headline metrics
- representative failures
- estimated cost and latency when available

Representative failures matter. They show whether the system is becoming more trustworthy or merely scoring well on easy cases.
