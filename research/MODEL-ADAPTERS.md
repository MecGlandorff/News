# Codex D/E transport and candidates v1

This is a small live-capable backend with offline executable tests. No live call
is authorized by this file. Freeze a separately reviewed finite run plan first.
I, R and B remain contracts only; this is not a five-arm comparison or semantic
quality evidence. The application model request is fixed to `gpt-6-astra` with
`medium` reasoning; research and review agents remain Astra/xhigh.
The [November 1 results](live-feasibility/RESULTS-2026-11-01.md) record the failed
source-free preflight, offline correction and separately recorded acquisition.
No D/E application result has been measured.

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

Natural-source candidate purpose requires `isolation.status="verified"` and external reviewed
preventive-isolation evidence. This string is an attestation, not a proof created
by the backend. Limited isolation permits a source-free probe or the explicitly
reviewed invented diagnostic described below. Allowed stages
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
Even a complete reported total covers observed turn telemetry only, not proven
total backend spend. A scheduled call is one CLI invocation; the underlying
provider-request count and server usage after cancellation are not fully observable.

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
The installed0.164.0 parser rejects retry overrides for reserved built-in provider
ID `openai`; documented retry fields apply to custom providers. The invalid flags
were detected with read-only `features list`, without launching a model, and
removed. No custom provider or alternate authentication route is introduced.
unbounded_connection_retries is disabled and the runner kills the process on the
first emitted error/turn.failed event. Built-in HTTP/SSE/auth/socket retries before
an observable event remain unverified and may occur; their attempt count is
unknown. The runner never retries a process. See the exact feature list in
`codex_backend.py`. A frozen live plan must disclose this limit.
The JSONL allowlist rejects unknown events and every tool item immediately, but
post-dispatch event rejection is detection, not preventive tool isolation. Do not
promote a successful no-tool probe into proof that unseen tools were unavailable.

The first recorded source-free invocation was stopped after0.834 seconds when
codex-cli0.164.0 emitted an `item.completed` error saying its disabled Code Mode
host was unavailable. No completed turn/usage was observed. Its exact three raw
JSONL events and binary hash are preserved under `protocol-fixtures/`; the original
run remains failed with unknown usage and cannot resume. `turn.started` after the
diagnostic was observed; whether a final no-tool response could complete is unknown.

By default this event still aborts, now as `disabled_code_mode_startup` rather than
an unspecified tool event. A future independently reviewed source-free backend plan
may explicitly add `startup_diagnostic_policy:
"codex-0.164.0-disabled-host-preflight-v1"`. This optional policy requires the exact
recorded macOS arm64 CLI binary SHA-256, `purpose="transport_probe"`, the exact
event/item/message shape and position immediately after the first `thread.started`.
It permits only that one capability diagnostic to be recorded and continued.
`diagnostics.json` preserves its classification and continuation decision. Every
changed, repeated, late or different error item, top-level error, tool event and
unknown event still aborts. Source-bearing synthetic/candidate purposes reject the
policy. No feature, host or tool is enabled by it. The fake executable tests use an
explicit test-only binary-pin substitution; they establish parser/accounting
behavior, not successful live transport. This option grants no retry or new trial;
the failed unknown-usage run remains stopped under every policy.

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

## Pinned diagnostic driver

An explicitly reviewed `synthetic_diagnostic` purpose additionally permits only
D/E_extract/E/delta with limited isolation. This is a narrow invented-input
diagnostic, not a declaration that preventive isolation is verified. Use the
driver's exact source hash and review pin; neither natural articles nor search
stages are admitted through this purpose. `candidate` retains its verified gate.

`trial_driver.py --capsule capsule.json --root /absolute/repository --output NEW`
supports source-free preflight and synthetic D/E phases. It verifies every pin
before dispatch, uses separate frozen D and E backend schedules, and preserves
the declared interleaving. A known-usage arm failure leaves its remaining slots
pending without consuming or transferring them; the other arm may continue.
Unknown usage, forbidden events, overshoot or global exhaustion stops all calls.
Canonical model output is preserved; publication only attaches the separately
generated validated deltas. No assignment/quote/offset repair is performed.
The driver validates structure/provenance, not semantic correctness; it does not
claim a live semantic judge or a quality score.

The capsule has exactly these keys (all non-null unless shown):

```json
{
  "schema_version": 1,
  "phase": "preflight",
  "files": [{"path": "relative/to/root", "sha256": "..."}],
  "phase_plan": "relative/phase-plan.json",
  "source": null,
  "schemas": {"reconstruction": "...", "extraction": "...", "delta": "..."},
  "executable": {"path": "/absolute/codex", "sha256": "...", "version": "codex-cli 0.164.0"},
  "review_record": "relative/independent-review.json",
  "prior_runs": []
}
```

`files` must pin the four Python files in `trial_driver.CODE`, all three prompt
files, phase/backend plans, input files and the review record. Paths resolve within
the supplied root. `schemas` is the canonical SHA-256 mapping from
`trial_driver.schemas()`. The executable bytes are pinned separately; its stated
version is frozen by review, not measured by a model call. For synthetic phase,
`source` is the pinned `synthetic_stress` manifest and `prior_runs` contains
`{"path":"/absolute/preflight/report.json","sha256":"..."}`. The driver verifies
that report and its call-record hashes, reconstructs usage from terminal records,
and rejects unaccounted/started-only attempts. This is a trusted controller and
same-user filesystem pins, not a malicious-code sandbox.

For the earlier root-owned preflight wrapper, use `trial_driver.py
--bridge-preflight /absolute/phase-summary.json --output
/same/directory/preflight-driver-bridge-v1.json`. This writes a new accounting
bridge, verifies summary usage against the recorded terminal, preserves its
original trial clock, and hashes all original raw call files plus the wrapper
capsule, start and summary records. It never rewrites them. Unknown usage remains
an explicit global stop; a failed preflight cannot authorize a synthetic phase.

Preflight phase plans contain `schema_version,phase,backend_plans:{preflight:path},
inputs:[initial_path,diagnostic_path]`. Only the first probe is dispatched. The
reserved diagnostic is retained as unused and is never automatically spent; a
later diagnostic requires a separately reviewed execution path and remaining
allocation. Synthetic phase plans contain `schema_version,phase,
backend_plans:{D:path,E:path},order:[{arm,call_id,stage,prefix_id,source_version_id}]`.
Each arm's filtered order must exactly equal its backend schedule. Extraction
source_version_id is explicit; other stages use null. D has at most4 slots and E
at most7. A successful pinned preflight must precede synthetic execution.

All phases retain the first preflight UTC clock origin and add measured call time
and usage; the global ceilings are18 CLI invocations,480000 input/72000 output
token stop thresholds,1800 model-active seconds,2700 elapsed seconds and2 failures.
The driver reserves at most2 preflight+4D+7E slots; the5 later search slots are
unimplemented here and cannot be silently spent. Phase/backend limits still apply,
and the strictest remaining shared time is passed to the child timeout. Unused
slots remain unused. These totals are reported turn usage, not financial caps or
proven provider request totals. A synthetic output marked successful here only
passed mechanical checks; semantic source review remains separate.
