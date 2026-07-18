# Phase 3 Closure Plan

**Status:** Ready for evidence collection

**Scope:** Close Phase 3 with current, reviewed production evidence before starting Phase 4.

Phase 3 implementation is complete. The remaining question is empirical: does the
current evidence path produce grounded claims and cautious source comparisons on real
news at an acceptable cost?

This plan turns that question into one bounded closure gate. It does not change model
choices, prompts, confidence rules, source-agreement semantics, or ordinary-run behavior.

## What Counts As Phase 3 Closure

Phase 3 closes after all of the following are true:

1. The current code has produced 5-10 successful daily runs, with 7 as the target.
2. At least 3 of those runs used evidence mode and exposed claim-verifier metrics.
3. A reviewer labeled 5-10 real claim cases, including paraphrases decided by the
   derivability verifier.
4. The RSS-versus-full-text eval records coverage, evidence validity, duplicates,
   verifier work, latency, tokens, and estimated cost.
5. The shipped similar-claim and number/date/status/attribution comparison results are
   reviewed on real cases without inferring independent corroboration.
6. Representative story matches, arc decisions, and daily deltas from the run series are
   inspected for obvious memory corruption.
7. The outcome and any accepted limitations are recorded in a checked-in closure report.

The review is the gate, not a promise that every result will pass. A grounding failure
keeps Phase 3 open until it is fixed or explicitly accepted through the repository's
decision protocol.

## Not Required For Phase 3

These remain useful later work, but do not block this closure gate:

- inferring independent corroboration or wire-copy relationships
- making claim extraction part of ordinary runs
- formal citation-support and temporal-diff benchmark suites
- semantic story-match caching
- dashboards, hosted services, or other Phase 4 product expansion

## Step 0: Prepare The Local Runtime

Use the repository's Python 3.12 target rather than an older global environment:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

Verify the exact environment that will run the pipeline:

```bash
python --version
python -m ruff check .
python -m mypy src
python -m pytest -q
```

Do not start the live series unless all three repository checks pass.

## Step 1: Protect And Rehearse The Database Upgrade

The existing database predates occurrence-backed replay and arc-decision audit rows. The
schema is idempotent and supports legacy data, but the first live run should not be the
first time the local database is exercised against it.

Create a consistent backup:

```bash
mkdir -p data/backups
sqlite3 data/stories.db ".backup 'data/backups/stories-pre-phase3-closure-20260718.db'"
sqlite3 data/backups/stories-pre-phase3-closure-20260718.db "PRAGMA quick_check;"
```

Rehearse initialization on a disposable copy:

```bash
cp data/backups/stories-pre-phase3-closure-20260718.db /tmp/news-phase3-migration-check.db
python -c 'from pathlib import Path; from src.tracker.store import get_db; connection = get_db(Path("/tmp/news-phase3-migration-check.db")); print(connection.execute("PRAGMA quick_check").fetchone()[0]); connection.close()'
sqlite3 /tmp/news-phase3-migration-check.db "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ('article_occurrences', 'story_arc_decisions') ORDER BY name;"
```

The rehearsal passes when the integrity check prints `ok` and both new table names are
present. The source database remains unchanged by this check.

## Step 2: Collect A Short Daily Run Series

The story lookback is 14 days, while the last local run predates this closure series by
several weeks. Treat the first run as a new baseline; the later runs provide the useful
continuity evidence.

Use one successful run per Europe/Brussels editorial day:

- minimum: 5 runs, including at least 4 after the baseline
- target: 7 runs
- maximum before reassessing the sample: 10 runs
- evidence mode: first, middle, and final run at minimum
- run size: keep the same `--max-per-source` value throughout the series

Recommended controlled evidence run:

```bash
python -m src.run --max-per-source 5 --show-evidence --pipeline-report
```

Recommended memory-only run between evidence days:

```bash
python -m src.run --max-per-source 5 --pipeline-report
```

Use the stored database; `--db-off` cannot build the multi-day memory being reviewed. A
same-day retry may repair a failed run, but it does not count as another day. Record any
flag or scope change because it affects comparability.

For every run, retain:

- run ID, editorial date, Git SHA, CLI flags, and final status
- the complete pipeline report
- notable claim-verifier accepts and rejects
- accepted and rejected story-match decisions
- arc attachments or rejections worth reviewing
- briefing cards with useful or suspicious deltas

## Step 3: Build The Real Claim Review

Keep raw fetched article bodies local unless redistribution is clearly permitted. Local
review datasets belong under `evals/local/`, which is ignored by Git. Checked-in reports
may include source URLs, short evidence spans, aggregate metrics, and reviewer findings.

Create 5-10 cases from the evidence runs. The set should include, where available:

- an expected claim visible in RSS fields
- an expected claim visible only in full text
- a near-verbatim deterministic acceptance
- paraphrases accepted by the verifier
- paraphrases rejected by the verifier
- a zero-claim or RSS-fallback result
- multi-source similar claims
- precise number, date, status, or attribution differences

Run the current production prompt and validation path:

```bash
python -m evals.run_claim_quality_eval \
  --dataset evals/local/phase3_claim_review.jsonl \
  --output evals/reports/phase3_claim_review.json
```

Reviewers should label verifier decisions, not just aggregate claim coverage. The key
question is whether a saved claim is actually derivable from its evidence span.

## Step 4: Review Memory And Source Comparison

Use the same run series for a bounded manual review:

- inspect continuing-story matches and rejections from days 2 onward
- inspect `delta_summary` for new information versus repeated context
- inspect accepted and rejected `story_arc_decisions`
- inspect similar-claim support groups for false equivalence
- inspect every emitted source-divergence note for a genuinely comparable claim pair
- verify that no output describes repetition as independent corroboration

This is a Phase 3 smoke review, not the broader citation or temporal benchmark planned
for Phase 4.

## Step 5: Record The Decision

Add a Markdown report under `evals/reports/` containing:

- dates and Git SHA for the run series
- dataset size, sources, model names, and prompt versions
- RSS and full-text claim-quality metrics
- verifier accept/reject review results
- agreement/divergence findings
- representative story-memory findings
- total and per-stage latency, tokens, and estimated EUR cost
- failures, limitations, and the final Phase 3 decision

There are three valid outcomes:

1. **Pass:** mark Phase 3 done in the README and improvement checklist, and add a project-log entry.
2. **Fix needed:** keep Phase 3 open, make the narrowest grounded fix, and rerun affected cases.
3. **Inconclusive:** extend the series up to 10 runs or add targeted reviewed cases without broadening production behavior.

Phase 4 begins only after this decision is recorded.
