# Tiny live feasibility source plan v2

This version preserves every v1 artifact and source-grounded expectation. It
removes a future-metadata leak and gives D and E separate finite backend
schedules. Use `run-plan-v2.json`, `synthetic-phase-plan-v2.json` and the v2 source
projection. Use the unchanged source-free preflight v2 through its new phase
plan. Execution capsules still require root's code/executable/prompt/schema pins,
prior-ledger pins and independent review before dispatch.

The old candidate-visible coverage text disclosed the complete trial's four
observations, three versions and two cutoffs at P01. The v2 projection changes
only `fixture_id` and `coverage.scope`: the new scope describes invented partial
coverage without future counts. `scorer/projection-amendment-v2.json` records the
exact before/after values and maps the unchanged v1 expectations to the v2
projection. All source fields, hashes, clocks, order, boundaries, evidence spans
and required/allowed/prohibited expectations remain byte-identical in content.
No application output informed this correction. Counts remain in scorer/run-plan
metadata, which never enters application prompts.

The independent review permits an explicit `synthetic_diagnostic` purpose under
limited isolation for invented sources only. Frozen CLI configuration disables
hosted search/tool surfaces, and observed forbidden/unknown events fail closed;
preventive tool/context isolation remains unverified. This exception cannot
unlock captured-source or search candidate calls. Those retain their separate
verified-isolation and source-only expectation gates. Synthetic success would
establish only the observed invented-input behavior.

D has exactly four backend slots and E exactly seven, with one failure allowed
per arm. The frozen phase order remains D P01 + delta; E's three P01 extractions,
E P01 + delta; E P02 + delta; D P02 + delta. Each backend keeps its own immutable
schedule and cursor. An ordinary known-usage failure stops that arm and records
its remaining slots as pending; the unaffected arm may continue at its positions.
No schedule popping, slot transfer, retry or manual output patch is allowed.
A shared failure, unknown usage, forbidden tool activity, exhausted global budget
or second globally counted application failure stops all remaining dispatch.

The overall allocations remain at most two preflight invocations, four D, seven E
and five later search invocations: **18 Codex subprocess invocations**, one trial,
zero controller/process retries. Provider-internal HTTP/SSE/auth retries, hidden
request counts and cancelled server usage are unknown. Input/output thresholds
remain 480,000 / 72,000; reservations are 24,000 / 4,000 per dispatched slot.
They are post-call stop thresholds, not provider-enforced token or spend bounds.
Preserve actual overshoot and all partial known usage; unknown usage is not zero.

Every phase carries the same immutable global ledger and first-preflight clock.
Pin prior reports and every referenced started/terminal record before continuation.
A missing terminal, incomplete ledger, changed pin or unknown usage blocks it.
Recorded active duration includes failure/cancellation/cleanup; elapsed duration
includes search recording and review. Creating a new phase or directory does not
reset either. Per-dispatch timeout is the minimum of the slot's deadline, the
remaining stage limits and the remaining shared 1,800 model-active / 2,700 elapsed
seconds. Every slot is at most 120 seconds; all maximum call deadlines still sum
to 1,650 seconds. D's ceiling is 360 active seconds / 96,000 input / 16,000 output;
E's is 630 / 168,000 / 28,000, including all three source-local extractions.

The unchanged prospective thin-source search seed and its expectations remain
frozen. The source-only author has seen no candidate outputs, prior pipeline
briefings or natural case labels. Search tool/recording limits, conditional versus
expanded denominators, six aggregate active research-agent hours, one working day
and the original evidence limits remain as specified in the machine v2 plan.
This is backend/D/E/search feasibility, not a completed five-arm comparison,
holdout, natural-news quality, importance/usefulness or long-run reliability test.
