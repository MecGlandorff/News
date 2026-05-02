# Evaluation Plan

The project should evaluate the behaviors that make it more than an article summarizer: story clustering, claim extraction, evidence grounding, temporal diffing, contradiction detection, and briefing quality.

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

### 2. Claim extraction

Question: did the system extract source-supported atomic claims?

Useful checks:

- valid JSON shape
- allowed `claim_type`
- non-empty `claim_text`
- evidence span present in article input when possible
- confidence is numeric and bounded
- no duplicate claims within one article

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
- conflicts are surfaced
- "what to watch next" does not invent unsupported predictions
- prose remains concise

---

## Planned eval directory

```text
evals/
  datasets/
    article_pairs.jsonl
    golden_story_clusters.jsonl
    golden_claims.jsonl
    golden_citations.jsonl
    temporal_diff_cases.jsonl
  reports/
  run_eval.py
  metrics.py
  README.md
```

Keep datasets small at first. Ten high-quality examples per behavior are more useful than a large noisy fixture set.

---

## Metrics

| Subsystem | Metric |
|---|---|
| Article deduplication | precision / recall / F1 |
| Story clustering | pairwise precision / recall / F1 |
| Claim extraction | validity / coverage / semantic match |
| Citation accuracy | supported / unsupported / missing |
| Temporal diffing | new-vs-repeated accuracy |
| Contradiction detection | precision-oriented score |
| Briefing quality | rubric score with cited examples |
| Cost | cost per run / cost per 100 articles |
| Latency | seconds per stage |

---

## Acceptance standard

Before adding a major AI subsystem, define at least one way to evaluate it.

Examples:

- before source agreement detection, create claim-pair examples where sources agree, differ, or merely repeat the same wire copy
- before contradiction detection, create numeric/date/status conflict examples with expected labels
- before full-text claim extraction for all articles, measure claim quality improvement against token and latency increase

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
