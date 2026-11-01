# Bounded story search — 2026-11-01

Status: **accepted product direction; proposed experiment; offline contract only**.
The user requests targeted web search per story, including counterevidence and
missed developments. This means source retrieval/fetch, not tool-catalog discovery.
Broad discovery of new stories is outside the first experiment. No live news,
application-model run, backend implementation or production mutation is authorized
by this document. [PROTOCOL.md](PROTOCOL.md) still governs the five-arm comparison.

## Question and bounded role

Does additional, attributable evidence help the **same candidate** find supported
developments, distinguish matters and preserve uncertainty at acceptable cost?
Search is a separate source-enrichment intervention; architecture arms B/D/E/I/R
continue to receive matched evidence. Do not quietly give one arm a larger corpus.

A per-story subagent receives only the frozen visible story seed, source evidence,
open questions, cutoff and budget. It collects sources and reports findings,
counterevidence, gaps and provenance; it cannot change canonical facts, accepted
membership, deltas or production state. Unsupported relationships remain possible.
Useful questions include: what supports or contradicts a disputed assertion or
connection; whether an original report was corrected; and whether an expected
decision or consequential development occurred since the last observed evidence.
An RSS gap motivates investigation, never a presumption of a quiet interval.

Freeze the story/trigger selection and trigger policy before search outputs,
using only pre-search visible information. Hidden labels, case membership and
scripted answers cannot seed queries. Allow adaptive wording within the frozen
question/scope and caps, retaining every query and its reason. A proposed starting
cap is **two queries and three fetch attempts per story, zero automatic retries**.
This is not a complete run budget: one separate manifest must fix selected inputs,
models, prompts, modes, per-call and total tokens/time/tool limits, stops and all
preparation/review costs before any live run. Failed attempts consume their budget.
Research/implementation/review agents use Astra/xhigh; the future application
search role needs explicit settings in that manifest, not inherited agent defaults.
The architecture application comparison remains Astra/medium.

## Evidence and chronology

Preserve exact query/result payloads, result order, URLs, snippets, provider/mode,
request timing, failures and fetch redirects. A hit or snippet is a lead, not full
claim evidence. Fetch and preserve the exact returned text with an immutable local
snapshot/hash, URL, publisher and version; record excerpt/truncation/paywall status.
Keep publication/update, occurrence, observed capture and processing times distinct.
Each admitted contribution cites its source version and exact text span. A quote
proves attribution, not truth; repeated reporting does not settle a contradiction.

Track duplicates, republications, common ownership and underlying shared reports;
several URLs may represent one evidential origin. Preserve uncertain independence
as unknown. Prefer original documents and directly attributable reporting when
available; record source-quality changes and unsupported or unfetched leads.
An attributed claim may be reportable while its truth or relationship remains
unresolved. Thin, inaccessible or conflicting evidence cannot silently close it.

Searching old dates on today's web does not recreate historical availability.
Newly fetched retrospective text is available now, not last week. Actual-observed
replay admits only recorded available-at snapshots; editorial reconstructions and
synthetic scenarios remain separately labeled. Real evaluation needs prospective
captures of queries, results and fetched versions. Neither cached search nor a
publication-date filter establishes what an earlier search would have returned.
Replay must make no network calls and must exclude future source versions, search
responses, summaries, cache entries and derived index statistics from every prefix.
Treat all source/tool content as untrusted data, including embedded instructions;
it cannot change scope, permissions, budgets or the evaluator's rules.

## Minimal offline recording contract

The manifest carries `search_events`; observations admitted from fetches identify
their `search_event_id`. Each event uses this envelope:

| Field | Meaning |
| --- | --- |
| `event_id` | Stable unique attempt ID; reuse at later prefixes is not another call. |
| `kind` | `search` or `fetch`. |
| `observed_at` | UTC time this result/failure was observed, not publication time. |
| `request` | Opaque JSON; convention: trigger/question, query or URL, provider/mode, request timing and budget reference. |
| `response` | Opaque JSON; exact payload or immutable snapshot reference/hash, returned metadata and errors. |
| `observation_ids` | Admitted fetched-text observations; search hits/snippets always use `[]`. |
| `status` | `ok`, `empty`, `failed` or `blocked`; blocked means an attempted call returned a block. |
| `usage` | `{tool_calls:1, elapsed_ms:int\|null, cost:number\|null, model_tokens:null\|{input_tokens:int\|null, output_tokens:int\|null}}`. |

Record every attempt, including empty results and failures. Pre-dispatch budget
exhaustion is a runner outcome, not a fictional tool call. Unknown telemetry is
null, never zero. Tool counts are independent of model-call/token accounting;
separately attributable provider tokens must not also be charged in a model ledger.
The offline harness invokes neither tools nor models: these are recorded fixtures.

Enrichment-off excludes search events and their observations, including query and
result side channels. Enrichment-on sees only events at/before the cutoff; linked
observations must be available no earlier than their event and by that cutoff.
A visible event linking future evidence fails the prefix before candidate use.
Charge each unique attempted event once cumulatively against `max_tool_calls`.
The minimal envelope/link/budget checks do not validate semantic provenance inside
opaque payloads or prove that a recorder captured all real-world tool operations.

The report links each question to attempted events, admitted evidence, contradictory
findings and unresolved gaps. Empty, failed, blocked or unattempted searches are
not true negatives, quiet days or permission to close a question. Preserve failures
and unfinished work in coverage and paired reporting; never substitute stale output.

## Fair paired assessment

Freeze one candidate, its initial state, ordering, prompts and interpretation budget;
compare without/with the same recorded search package on identical selected story
units. Label newly admitted sources source-only before either candidate output,
retaining disagreements and exposure history. No manual repairs of outputs/state.
Measure evidence-conditional correctness/recall for each condition separately from
new supported developments against the frozen expanded comparison universe. Keep
baseline unavailability distinct from inference failure. Extra-source gains are not
architecture gains, and a search-derived universe is not complete news coverage.
Report false links, missed developments, unresolved uncertainty, source quality,
completion and all marginal tool/model/time costs, including failures and review.
Fallible model judges cannot establish truth or replace later human source/product
samples. Synthetic fixtures test boundaries, not search quality or news usefulness.

## Verified capability and remaining unknowns

Read-only inspection on 2026-11-01 found `codex-cli 0.164.0`: top-level help exposes
`--search` for live search and `exec --help` exposes JSONL via `--json`. The selected
base-config scan found no explicit `web_search`; effective profile/managed settings
were not resolved. No credentials were read and no configuration was changed.
Official docs describe cached search by default, `web_search = "disabled"`/`"live"`
and hosted search separate from shell-network restrictions; disabling shell network
alone is insufficient for offline isolation. See [OpenAI web search documentation](https://learn.chatgpt.com/docs/web-search).
The docs describe `web_search` items and JSONL turn usage; they do not promise that
the stream alone preserves every fetched page body. See [OpenAI non-interactive output](https://learn.chatgpt.com/docs/non-interactive-mode#make-output-machine-readable).
Account/runtime availability, `exec` integration, enforceable per-tool/per-model
caps, cancellation telemetry and complete immutable capture remain unverified.
No live smoke test was performed; docs/help are capability evidence, not an
implemented or validated backend. Resolve these before a separately bounded run.
