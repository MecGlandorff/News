# Bounded story search — 2026-11-01

Status: **recorder implemented; one bounded controller-only acquisition sideprobe
recorded; application planner and paired comparison untested**.
The [November 1 results](live-feasibility/RESULTS-2026-11-01.md) distinguish these
recording mechanics from search quality and the stopped application trial.
The user requests targeted web search per story, including counterevidence and
missed developments. This means source retrieval/fetch, not tool-catalog discovery.
Broad discovery of new stories is outside the first experiment. No live news,
application-model run or production mutation is authorized
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
For live fixed-evidence architecture runs and enrichment-off, require and verify
effective `web_search = "disabled"` for every stage, including child agents;
cached search is also external evidence. A prompt to use only provided sources
is not enforcement. Before enrichment-on qualifies as controlled, verify complete
recording and enforceable tool caps in the actual backend. The offline envelope
and its budget checks do not control Codex's internal tool execution.
The docs describe `web_search` items and JSONL turn usage; they do not promise that
the stream alone preserves every fetched page body. See [OpenAI non-interactive output](https://learn.chatgpt.com/docs/non-interactive-mode#make-output-machine-readable).
Account/runtime availability, `exec` integration, enforceable per-tool/per-model
caps, cancellation telemetry and complete immutable capture remain unverified.
No live smoke test was performed during this capability inspection; docs/help are
not validation of a hosted-search backend. Resolve these before using that path.

## Controller-owned recording implementation

`search_recorder.py` is a small, offline two-phase receipt writer for an explicit
controller. It does not launch a model or search/fetch tool. The controlled path
uses a source-only application-model call with hosted search disabled to propose
targeted queries and reasons. A frozen controller policy selects fetch URLs from
ordered results; it cannot select only favorable findings. The first trial can
use the runtime-provided web tool, one query or one URL per operation. This does
not establish a standalone CLI search backend.

The controller initializes a new receipt directory from a frozen JSON plan with
exact keys `collection_id`, `story_id`, `cutoff`, `scope`, `provider`, `mode`,
`transport_id`, `max_searches`, `max_fetches`. The cutoff describes the visible
seed; it cannot backdate newly captured evidence. Requests are `{query,reason}`
for search or `{url,reason}` for fetch. The controller follows this sequence:

```sh
python3 research/search_recorder.py init --directory NEW --plan plan.json
python3 research/search_recorder.py begin --directory NEW --kind search --request request.json
# Invoke exactly one explicit tool operation; preserve its COMPLETE returned JSON.
python3 research/search_recorder.py complete --directory NEW --event-id ID --result tool-return.json --status ok
python3 research/search_recorder.py package --directory NEW
```

Fetch completion may add `--source source.json`, containing `fields` (including
`url` and `text`), `completeness` (`full`, `excerpt`, `truncated`, or `unknown`),
`redirects` (URL array or null), and `published_at_utc` (UTC or null). Text must
occur unchanged within a returned payload string. This proves an exact returned
span, not semantic truth, publisher identity or that a tool supplied a whole page.
Only successful fetches admit observations. The runtime tool's text representation
must be labeled excerpt/unknown when completeness cannot be established. All
metadata remains visible alongside the preserved raw result; original result array
order and JSON string contents survive canonical JSON serialization. Original HTTP
bytes, hidden provider requests, redirects not exposed by the tool, hidden retries
and provider costs/tokens remain unknown.

`begin` writes a started receipt before dispatch, reserves one capped operation,
and refuses new operations while a receipt is unfinished. Reopening counts prior
starts; it cannot reset the budget. A refusal is a separate runner outcome, never
a fictional tool call. A process crash leaves a pending reservation with unknown
dispatch/usage, which the package exposes. `complete` writes the full raw return
before validating source metadata; failed/blocked/empty attempts count. Use
`--status failed --error error.json` for an exception without a returned payload.
The recorder does not automatically retry, dispatch from model JSON, enforce tool
timeouts or control provider-internal work. The trusted controller must call
`begin` before every actual operation and preserve each complete return.

Files are exclusive-create, flushed and read-only after writing; hashes detect
changed raw snapshots before subsequent operations. This is append-only API
behavior, not protection against a filesystem owner rewriting the entire ledger.
Invalid source/capture contracts stop further reservations. Available-at and
observed-at use completion time, so today's results cannot enter an older prefix.
Elapsed time covers the reservation-to-completion wall interval, including controller
bookkeeping. Unknown provider cost/model usage is null. Pending reservations must
remain visible in overall run accounting, separately from completed replay events.

Offline verification:

```sh
python3 -m unittest discover -s research/tests -p test_search_recorder.py -v
```

The tests cover restart-safe caps, pending and failed attempts, immutable capture,
text validation, CLI operation and replay chronology/isolation. They do not prove
the runtime transport exposes every provider-internal operation or news quality.
Additional read-only inspection of `codex-cli 0.164.0` generated app-server schemas:
the web-search item exposes query/action and optional `results` documented for
standalone search; its open-page action contains a URL, not a page body. This is
not the exec JSONL schema and does not establish complete hosted capture. Official
[web-search settings](https://learn.chatgpt.com/docs/config-file/config-basic#web-search-mode)
confirm `web_search = "disabled"` removes the hosted tool. The
[configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
documents custom-provider request/stream retry settings. The
[custom-provider contract](https://learn.chatgpt.com/docs/config-file/config-advanced#custom-model-providers)
forbids redefining the built-in `openai` provider; these settings are not a verified
built-in retry override. Zero controller retries does not imply zero hidden
CLI/provider retries.
