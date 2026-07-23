# Phase 3 Matching Reconstruction

**Created:** 2026-07-23T21:10:37+00:00
**Range:** 2026-07-21 through 2026-07-22
**Snapshots:** 158 articles across 2 days
**Source archive:** `source-archive.db`
**Review dataset:** `matching_reconstruction_review_2026-07-21_22.jsonl`
**Active database replaced:** no

## Effort Comparison

| Effort | Reviewed | Scored | Insufficient evidence | Corrupting accepts | Clear-positive recall | Matching cost |
|---|---:|---:|---:|---:|---:|---:|
| none | 16 | 15 | 1 | 1 | 60.0% | EUR 0.1793 |
| low | 16 | 15 | 1 | 0 | 80.0% | EUR 0.1920 |

## Cost Detail

| Effort | Purpose | Calls | Prompt tokens | Completion tokens | Latency | Cost |
|---|---|---:|---:|---:|---:|---:|
| none | match-arc-evidence | 1 | 9780 | 1578 | 9.0s | EUR 0.0123 |
| none | match-crossday-evidence | 4 | 66801 | 4699 | 31.2s | EUR 0.0607 |
| none | match-sameday-evidence | 8 | 105450 | 10112 | 65.3s | EUR 0.1062 |
| low | match-arc-evidence | 2 | 10967 | 1956 | 12.7s | EUR 0.0145 |
| low | match-crossday-evidence | 4 | 64733 | 6087 | 46.6s | EUR 0.0647 |
| low | match-sameday-evidence | 8 | 105450 | 11812 | 74.4s | EUR 0.1127 |

## Integrity

| Effort | SQLite quick check | Foreign-key violations | Non-ok runs | LLM errors | Schema failures | Retries |
|---|---|---:|---:|---:|---:|---:|
| none | ok | 0 | 0 | 0 | 0 | 0 |
| low | ok | 0 | 0 | 0 | 0 | 0 |

## Selection

**Status:** selected
**Selected effort:** low

low passes, improves clear-positive recall, and adds no more than EUR 0.05.

## Reviewed Failures

- `story-world-matchplay-distinct-developments` (none, story, corrupting_accept, route `mini`)
- `arc-tour-stage-under-tour-2026` (none, arc, missed_positive, route `mini`)
- `arc-world-matchplay-tournament` (none, arc, missed_positive, route `not_retrieved`)
- `story-india-youth-protests` (low, story, missed_positive, route `fail_closed`)

## Insufficient Evidence

These cases remain fail-closed and are excluded from quality scoring:
- `same-day-ai-agent-incident` (same_day): The saved Trouw occurrence has a question-style headline but no description or body text, so the shared incident cannot be established from retained source evidence.

The reconstruction databases remain local. Replacing `data/stories.db` requires a separate explicit decision.
This result validates the matching precondition only; the fresh Phase 3 daily claim/source review series still has to run.
