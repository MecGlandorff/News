# Classifier Omissions Causing Uncategorized Memory Contamination

## Status

OPEN.

This issue documents a run-quality finding from the May 22 audit of pipeline run `23`.
The immediate symptom appeared in run `23`, but the root contamination was created by
the prior successful run on `2026-05-21`.

## Why This Matters

The project is source-grounded event memory. If the classifier omits article IDs and
the pipeline silently falls back to `story_label="Uncategorized"`, unrelated articles
can be stored under one fake story. That corrupts future memory because later articles
can attach to the bad arc as if it were a real continuing story.

False splits are tolerable. A false generic bucket is worse because it creates a
high-source, high-article "story" with no real-world event identity.

## Evidence

### Run 23, 2026-05-22

Pipeline report:

- `453` articles returned.
- `238` stories touched.
- `240` developments saved.
- `94` new parent arcs.
- `95` arc attachments.
- `51` story-match accepts.
- `63` story-match rejects.
- `39` real LLM calls.
- Estimated cost: `EUR 1.17`.

The run itself persisted cleanly:

- `453` article rows.
- `453` distinct article IDs.
- `238` `story_daily` rows.
- `240` `story_developments` rows for `2026-05-22`.

The new-parent ratio was `94/240` (`39.2%`), close to recent good runs:

- `38.0%` on `2026-05-21`.
- `39.9%` on `2026-05-20`.

This suggests the headline new-arc count was not the main failure.

### Contaminated Story

Story `4945` was created on `2026-05-21`:

- `canonical_label`: `Uncategorized`
- `theme`: `Other`
- `source_count`: `10`
- `article_count`: `187`
- `importance_avg`: `1.0`

Most of those rows were not validly classified:

- `180/453` article rows for `2026-05-21` lacked valid `article_classifications`.
- The missing rows were concentrated in story `4945`.
- The story contained unrelated articles from multiple sources and topics.

On `2026-05-22`, the polluted story continued with one NRC NATO article:

- Title: `Europese NAVO-landen vallen nog steeds van de ene Trump-verbazing in de andere`
- Runtime fallback attached it to `Uncategorized`.
- A stale `article_classifications` row existed for the same `article_id`, but the
  content hash differed because the description changed slightly.

Important audit nuance: runtime cache lookup checks `content_hash`, but later SQL audit
joins that only use `article_id` can make stale classifications look valid. Future
inspection queries should compare article content hash against `article_classifications.content_hash`.

## Diagnosis

The likely failure path is in `src/classifier.py`:

1. `classify_articles()` sends a batch of missing article IDs to the model.
2. The model response may omit some requested IDs.
3. The code saves the classifications it received.
4. During enrichment, any article still missing from `classification` falls back to:
   - `theme="Other"`
   - `story_label="Uncategorized"`
   - `importance=1`
5. The tracker then treats those fallback labels as real story labels.

This makes classifier omission a silent data-quality failure instead of an explicit
retry, error, or quarantined row.

## Related Findings From The Same Audit

These are not the root issue, but they were observed during the same deep dive:

- Digest rendering duplicates canonical stories across theme sections because `src/digest.py`
  groups by article theme first and canonical label second.
- Run `23` duplicated these headings in `output/digest_20260522_2244.md`:
  `AOW Talks`, `Colombia drug smuggling arrest`, `Dutch women's football`, `Exam quiz`,
  `Iran-Hormuz crisis`, `Israel-Gaza war`, and `Ter Apel asylum overflow`.
- Arc assignment accepts `adjacent_topic` and `broader_context` as attachment relationships.
  In run `23`, `32/95` new-child attachments used those loose relationships.
- Some loose attachments looked too broad for event memory, including:
  `Child labor case -> Child abuse charges`, `Prince Andrew probe -> Police probe assault`,
  `Music complexity -> Music interview`, and `Heat wave and hot weather -> Weather forecast`.
- `LLM cache hits: 438` mostly reflected article-classification cache hits, not exact
  `llm_response_cache` reuse.
- The OpenAI SDK retried a `502`, but the run report showed `Retries: 0`.

Those should be handled separately after classifier completeness is fixed.

## Fix Candidates

1. Treat omitted classifier IDs as a hard validation failure.
   - If the response does not classify every requested article ID, raise a schema/data
     failure and stop the run.
   - Strongest protection for memory, but can make transient model omissions fail runs.

2. Retry omitted IDs in smaller batches.
   - First response can classify most articles.
   - Missing IDs are retried once or twice in small batches.
   - If any still fail, stop the run or quarantine them.

3. Quarantine unclassified articles instead of tracking them.
   - Do not attach omitted articles to `Uncategorized`.
   - Record count and maybe write an audit artifact/table row.
   - Preserves run output for classified articles, but the run is incomplete.

Recommended first implementation:

- Retry omitted IDs once in smaller batches.
- If IDs are still missing, fail visibly before tracking.
- Do not use `Uncategorized` as a silent fallback for model omissions.

## Repair Candidates

Repair must preserve compatibility with existing `data/stories.db` and avoid destructive
migration steps.

Options to consider:

1. Quarantine story `4945`.
   - Rename it to something like `Classifier omission quarantine`.
   - Prevent future matching/arc assignment from using it.

2. Delete or detach only generated memory rows for story `4945`.
   - More invasive; should not be done silently.
   - Needs careful treatment of `articles`, `story_daily`, `story_observations`,
     `story_developments`, and `article_story_links`.

3. Leave historical rows but block future matching to `Uncategorized`.
   - Least destructive.
   - Requires tracker logic to exclude generic fallback labels from recent story/arc candidates.

## Done Criteria

- Classifier omissions are detected by tests with a fake client.
- The pipeline does not silently track articles with missing classifier output as
  `Uncategorized`.
- Stale `article_classifications` rows with mismatched content hash do not appear valid
  in audit helpers or tests.
- A focused DB audit after the fix shows no current articles attached to the polluted
  `Uncategorized` story `4945`.
- The run report or a related audit path exposes classifier omission counts, retries,
  or failures clearly enough for review.

