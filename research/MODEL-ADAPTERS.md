# Codex D/E transport and candidates v1

This is a small live-capable backend with offline executable tests. No live call
is authorized by this file. Freeze a separately reviewed finite run plan first.
I, R and B remain contracts only; this is not a five-arm comparison or semantic
quality evidence. The application model request is fixed to `gpt-6-astra` with
`medium` reasoning; research and review agents remain Astra/xhigh.

`codex_backend.Backend(output_dir, plan, executable="codex")` creates a new
immutable ledger. `invoke(call_id, stage, prompt, schema, validate=None)` consumes
the next exact scheduled slot and returns the existing replay envelope. No shell
interpolation, session resume, automatic process retry or existing output rewrite
occurs. A trusted optional validator can reject the output before the response is
recorded. The backend plan records its own code hash, requested model/settings,
environment-key allowlist and disabled features. Environment values and credentials
are not logged; existing CLI authentication uses the ordinary home/CODEX_HOME.

The plan is a JSON object with these exact keys:

```json
{
  "schema_version": 1,
  "purpose": "transport_probe",
  "isolation": {"status": "limited", "evidence": "Reviewed capability evidence location"},
  "schedule": [{"call_id": "probe01", "stage": "probe", "input_tokens": 24000,
    "output_tokens": 4000, "timeout_seconds": 120}],
  "budget": {"input_tokens": 24000, "output_tokens": 4000,
    "model_active_seconds": 120, "wall_seconds": 180, "max_failures": 1}
}
```

Candidate purpose requires `isolation.status="verified"` and external reviewed
preventive-isolation evidence. This string is an attestation, not a proof created
by the backend. Limited isolation permits only a source-free probe. Allowed stages
are probe, D, E_extract, E, delta, search_plan. Probe calls contain no news corpus,
labels or scorer material. The run controller owns actual corpus freezing,
cross-ledger/shared-stage accounting, stage/arm allocation and semantic stops.
The backend must not be used as an uncounted nested callable in the offline replay
harness: persist extraction calls separately and charge actual/standalone costs.

Before process launch each call stores `request.json`, `prompt.txt`, and
`schema.json`. It preserves `stdout.jsonl`, `stderr.txt`, `last-message.txt`,
`response.json`, `usage.json` and `terminal.json`. A launch failure still consumes a
slot and retains a terminal record. Hard killing the controller can leave a
started-only attempt; that remains incomplete with unknown usage. Known partial
usage is retained, never converted to zero; unknown usage stops subsequent calls.
Failures, token-threshold overshoots and unfamiliar/tool events remain visible.
No monetary cost is inferred. Cached-input telemetry stays in raw completed events;
input_tokens is not reduced by cached tokens for the token budget.

Each child starts in a new empty temporary directory and a separate process group.
The remaining wall/model-active budget limits its timeout (at most120 seconds).
TERM/KILL cleanup adds at most approximately0.6 seconds of local grace; remote
work cancellation and final usage after cancellation are unverified. Four MiB is
the combined stdout/stderr byte threshold. These are process/stream controls, not
provider output-token ceilings. There is no verified per-call output-token bound
or exact pre-call input counting; token budgets are stop thresholds with possible
one-call overshoot. The full request/schema/hidden CLI context can add input tokens.

The argv uses `--ignore-user-config`, `--ephemeral`, `--sandbox read-only`, disabled
hosted web search, explicit disabled shell/app/plugin/browser/multi-agent features,
and no `--ignore-rules` or sandbox/approval bypass. Managed security remains in force.
`request_max_retries=0` and `stream_max_retries=0` are requested for the OpenAI
provider and unbounded_connection_retries is disabled; no claim is made that every
internal authentication/socket recovery path is independently counted. The runner
never retries a process. See the exact feature list in `codex_backend.py`.
The JSONL allowlist rejects unknown events and every tool item immediately, but
post-dispatch event rejection is detection, not preventive tool isolation. Do not
promote a successful no-tool probe into proof that unseen tools were unavailable.

`model_adapters.py` holds strict JSON output schemas and a narrow validator; prompt
versions are text files under `prompts/`. D receives only current visible sources.
E invokes one extraction per immutable source version, without other sources or
interpretations, then reconstructs from that prefix's selected extraction payload
and unchanged raw sources for evidence verification. This E is an intermediate
extraction variant, not a compressed-input cost architecture. Version-local spans
omit observation IDs so repeated observations can reuse extraction. Reconstruction
still accounts for each observation and validates every exact span. No offset,
assignment or output is manually or automatically patched. The extraction recipe
hash pins its schema/prompt; externally provided cache provenance still needs audit.

D/E reject prior interpretations and require empty deltas/null repair at canonical
reconstruction. `compare_delta` alone sees previous_published and returns only
deltas, with separate scheduled usage. `extraction_artifact` selects visible
versions and rejects failed/invalid results; future cached versions are withheld.
The helpers do not invoke other stages automatically. The search planner may
produce a separately validated plan; only the external controller can execute
bounded recorded tools. Hosted web search remains disabled throughout.

Run offline behavior checks with
`python3 -m unittest discover -s research/tests -p test_codex_backend.py -v`.
These launch temporary fake executables, never Codex or a model, and cover request
persistence, exit/launch errors, usage stops, overshoot, tool rejection, timeout
with descendants, schema failure, schedule/isolation gates and source boundaries.

Capability sources: local codex-cli0.164.0 `exec --help` and `features list`,
[official exec documentation](https://learn.chatgpt.com/docs/developer-commands#codex-exec)
and [configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).
