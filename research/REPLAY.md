# Offline replay contract v1

`replay.py` is a standard-library, model-free execution and accounting harness.
It accepts frozen JSON responses or trusted offline Python stubs. It runs no
application model, baseline code, web search, shell command or tool dispatcher.
This is a representation/mechanics test, not five implemented architectures or
evidence of semantic detection, factual correctness or reader usefulness.

Run the executable probes with:

```sh
python3 -m unittest discover -s research/tests -p test_replay.py -v
```

The CLI consumes a JSON array of response envelopes in invocation order:

```sh
python3 research/replay.py --manifest manifest.json --plan plan.json \
  --responses responses.json --output .news/replay/run-001
```

Use a new output directory for every attempt, including unsuccessful runs. The
CLI supports the direct recorded-response path; extraction/index artifacts,
initial state and the optional comparison callback use the Python API:

```python
run(manifest, plan, candidate, output_dir, initial_state=None,
    artifacts=None, delta_compare=None, recorded_responses=None)
```

Set `candidate=None` with `recorded_responses` to freeze the entire response
recording. Otherwise `candidate(context)` returns this JSON envelope:

```json
{"status":"ok","output":{},"usage":{"input_tokens":2,"output_tokens":3},"error":null}
```

`status` is `ok` or `failed`. Usage must be supplied even for failure; either
token count may be null. Synthetic numbers in tests are declared stub telemetry,
not measured model usage. A callable implementation's declared identity is
recorded, but the harness cannot attest its code or sandbox a malicious callable.

## Frozen inputs and output representation

The manifest contains `schema_version:1`, `fixture_id`, `chronology_mode`,
`observations`, `boundaries`, `coverage`, and optional `search_events`.
Each observation has `observation_id`, `source_version_id`, `source_sha256`,
`fields`, `observed_at`, `published_at_utc`, and `available_at`. The SHA-256 covers
canonical JSON of the allowlisted source fields, using sorted keys, UTF-8 and
compact separators. Repeated observations retain separate identities; a version
ID cannot silently refer to changed fields. Source metadata contains no curated
case, story, expectation or defect labels. Whitelisting metadata cannot detect
semantic hints embedded in source text.

Boundaries are `{prefix_id,day,at}` in strict chronological order. All timestamps
use UTC (`Z` or `+00:00`); `day` is the UTC date, not a reader-local briefing day.
The visible source set is cumulative at `available_at <= at`, including empty
and repeated sources. Actual-observed availability must equal capture time;
editorial reconstruction uses publication time. Existing casebook mode aliases
are retained; synthetic stress is separate. Future coverage gaps are withheld,
and a visible gap is clipped to the current day. Quiet boundaries are explicit;
missing dates do not become evidence of quiet news.

Every output contains these fields (empty arrays and nulls are explicit):

| Field | Contract |
| --- | --- |
| `schema_version` | Integer 1 |
| `contributions` | `id,kind,claim,attribution,source_spans,occurrence_id,story_id,uncertainty` |
| `relations` | `from,to,type,status,source_spans`; status `accepted` or `possible` |
| `source_accounting` | Exactly one row per visible observation: `observation_id,status,contribution_ids,reason` |
| `deltas` | `kind,contribution_ids`; context and interpretation repair are not news kinds |
| `questions` | `id,status,claim,source_spans,closure_reason`; open/answered/closed |
| `analysis` | Only `text,evidence_contribution_ids`; no factual mutation fields |
| `repair` | `reason,supersedes`, separate from source correction and news deltas |

Contribution kinds are `new_occurrence`, `same_occurrence_material_fact`,
`source_correction`, `question_opened`, `question_answered`, `question_closed`,
`conflict`, and `context_only`. Exact spans contain `observation_id`,
`source_version_id`, `field`, `start`, `end`, and `quote`; offsets are Unicode
codepoints `[start,end)` in unchanged title/description/text, including raw HTML.
Attribution is a string; uncertainty is a string array. Occurrence/story IDs may
be null. A nonnull story ID expresses accepted assignment; uncertain relations
belong in `possible` links. Corrections can use typed evidence-bearing relations.

Accounting is `processed` (one or more cited contributions), `unassigned` (zero
contributions and a reason), or `pending` (possibly partial contributions and a
reason). Cross-checking every citation against every accounting row exposes
mechanical omissions; it cannot identify a meaningful source fact never extracted.
Successful prefix execution can retain explicit pending work. `completed` means
every scheduled prefix returned a structurally accepted output, not full semantic
coverage. Rendered briefings, semantic correction/supersession validity, importance
and whether a new question is material remain unevaluated.

## Arm boundaries and budgets

A plan contains `schema_version:1`, `arm`, `implementation_id`, `enrichment`,
`delta_comparison`, `budget`, `per_call_tokens`, and `recovery_prefixes`.
The budget has integer ceilings for `calls`, `tokens`, `seconds`, `tool_calls`,
and `recovery_calls`. Zero is allowed; `per_call_tokens` must be positive.
No automatic retry is permitted outside the explicit recovery-prefix list, and
v1 permits at most one reserved recovery attempt per prefix.

D/E/R receive no previous interpretation. I alone receives `prior_state` with
its version, time, output and origin. E/I require an extraction artifact; R also
requires an index artifact. These are contracts for future implementations:
the harness does not extract, retrieve, enforce a retrieval algorithm, or verify
that an opaque artifact's contents were generated source-only.
Artifacts are keyed by prefix and kind; each has `kind,version,cutoff,source_only,
source_versions,recipe_sha256,payload`. Declared source versions/hashes must equal
the complete visible corpus, the cutoff cannot be in the future, and the recipe
is pinned. Represented future versions and index provenance fail before dispatch;
undeclared information inside opaque payloads still requires independent audit.
B additionally requires `adapter:{baseline_revision,adapter_sha256}`, pinned to
`bc7b0fb93d3ca34fdb9400d91deb4a627cf96fe9`; no baseline executes here.

Only a declared `delta_compare` callback sees `previous_published` after current
reconstruction. It returns the same envelope with output `{deltas:[...]}` and
cannot replace facts or relationships. Every invocation counts, including failed
calls, comparison and reserved recovery. Analysis is schema-separated, but text
can still imply unsupported claims; schema checks do not prove it is truthful.

Call ceilings and token reservations are checked before invocation. Returned
overshoots are recorded and stop the arm. Partial known token counts are retained;
unknown usage makes `total_tokens:null` and stops further calls. Wall-clock and
token enforcement are cooperative for local stubs: an in-flight Python callable
cannot be preempted, and declared reservations do not bound a real backend.
Live adapters need enforceable output/time controls and separately authorized
budgets. Research-agent work, shared extraction cost and provider telemetry are
not inferred from stub call counts; real comparative cost accounting is future work.

## Persistence, search and recovery evidence

`inputs.json` freezes the manifest, plan, seed, artifacts and optional recording.
Each call writes a started record before dispatch and a separate terminal record.
Views and failed outputs are append-only; versions include their prefix and
previous publication. Interrupts retain a report and unknown usage before being
re-raised. A hard process kill can leave only a started record: treat the run as
incomplete, never as zero-cost success. Non-JSON Python returns retain a diagnostic
and valid usage where available; their arbitrary object graphs are not preserved.
There is no resume operation or automatic rewriting of an existing run directory.

A failed current prefix clears `active`; old successes remain in history, not
silently published as current. The runner records replacement ancestry separately
from candidate-authored repair text. Contamination tests show that reconstruction
can replace seeded state and I can receive/replace it without scorer-only defect
IDs. Scripted replacement is not semantic discovery or proof of automatic repair.

Recorded search is a separate same-arm enrichment switch. Off hides both search
events and linked fetched observations. On admits timestamped events and sources
only at their cutoffs; a visible event pointing to a future source fails. Only
successful fetches mint claim-bearing observations; search hits alone cannot.
Each unique attempted event counts once across cumulative prefixes, including
empty/failed/blocked results. Opaque requests/responses are never executed. Nullable
provider telemetry stays null and is stored separately from callable token costs.
The detailed experimental contract is in [SEARCH.md](SEARCH.md).

The executable probes cover future evidence, version tampering, hidden incomplete
accounting, malformed and interrupted output, exhausted/unknown budgets, recorded
search boundaries, isolated arm state, and mechanical replacement. They do not
establish news quality, full-day retrieval, natural 30–90-day continuity, human
usefulness, or any architecture winner. Those require later frozen evidence,
candidate implementations, source-grounded review and separately bounded runs.
