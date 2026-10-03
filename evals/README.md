# Synthetic evaluation corpus

Every item in `cases.json` is invented test material. The place names, publishers,
events, numbers, dates, and `example.test` URLs are not real news or evidence of
real events. There are 16 labeled cases containing 45 articles.

Cases cover same-event grouping, same-topic false merges, direct follow-ups,
entity overlap, contradictory reports, revised numbers, negation, dates,
multilingual reports, memory correction, multiple memory matches, and embedded
malicious instructions. Labels are human-reviewable expected partitions and
per-article continuation IDs. Ordinary tests check the scorer without a model.

`scoring.score_case(case, response)` returns a JSON-safe dictionary:

- `pairwise_tp`, `pairwise_fp`, and `pairwise_fn` count article pairs; precision,
  recall, and `pairwise_raw_f1` are the corresponding mathematical metrics.
  `pairwise_f1` is zero if coverage is malformed: omitted articles, duplicate IDs,
  unknown IDs, empty groups, or non-list/non-string membership. This prevents
  missing singletons from receiving a perfect pairwise result.
- `exact_partition` requires complete, unique membership in exactly the expected
  groups. Average this Boolean across trials for exact partition accuracy.
- `continuation_accuracy` counts correctly assigned prior-event IDs per input
  article. An omitted or duplicated article is wrong. Its denominator includes
  every input article, including articles that should start new events.
- `evidence_coverage` measures input articles with an exact nonempty quote in
  their assigned event. `evidence_quote_errors` counts malformed, nonexact, or
  wrongly attributed evidence items. Missing evidence reduces coverage and adds
  an error even if there is no quote item to count.
- `valid` checks the structural/evidence contract. `strict_pass` additionally
  requires the labeled partition and every continuation to match. Errors remain
  visible independently of the grouping and continuation metrics.

These checks cannot prove factual truth, useful quotes, faithful event labels,
real-world clustering quality, or protection from every prompt injection. Even
one exact word can pass a substring check. The model-generated label therefore
remains interpretation; the output quotes retain source attribution. A structurally
valid result can still merge different events. The labels detect such mistakes
only in these deliberately small cases. Repeated live trials assess variation
on this corpus, not generalization to a real news workload.
