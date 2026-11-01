# Source-free transport preflight v2

This is a definition freeze for a bounded backend check, within the user's
accepted small trial. It authorizes no source-bearing application call by itself.
A separate immutable execution capsule must pin the reviewed runner, executable,
version, effective configuration and review record before root dispatches it.
Null capsule values in the manifest are blocking unknowns.

Use the exact input and response schema in
`inputs/preflight-initial-v1.json`, with `preflight-backend-plan-v2.json`.
The requested result is one schema-valid acknowledgement, exit zero, exactly one
completed turn with known nonnegative integer input/output token counts, and no
tool or unfamiliar events. Preserve request, argv, stdout/stderr, output, usage,
timing and every failure. Success proves transport behavior on this request;
it does not prove preventive evidence isolation or semantic quality.

There is one initial invocation and one **conditional** diagnostic slot. The
second slot uses its separately frozen input only after a known-usage failure
that needs no code/configuration change. It is unused after success. No automatic controller/process
retry exists. Provider-internal HTTP/SSE/auth retries are unknown and may occur;
the 18-call ceiling counts Codex invocations, not hidden upstream requests. Unknown usage, forbidden tool activity, timeout without usage,
changed artifacts or a token/time stop prevents further application calls.
Changing the runner requires a versioned plan and remaining-budget check;
the reserved slot is not permission for an unrecorded retry or repair loop.

The stage has at most two application invocations, 120 seconds per invocation,
240 model-active seconds and 600 elapsed seconds. Its token stop thresholds are
48,000 input / 8,000 output; each slot reserves 24,000 / 4,000. Those tokens are
not hard backend caps. One-call overshoot and cancellation with unknown usage
remain possible and must be reported. This stage counts against the complete
trial's 18 invocations, 480,000 input / 72,000 output stop thresholds, 1,800
model-active seconds and 2,700 elapsed live seconds, including failure/recovery.
All live clocks start at the first preflight dispatch and cannot be reset by
creating another run directory. Root must carry actual preflight accounting
into every later stage.

Application calls use `gpt-6-astra` with medium reasoning. Research, preparation,
independent review, corrections and result review use Astra/xhigh within six
aggregate active agent-hours and one elapsed working day. Their tokens and cost
are unknown; no global financial cap is claimed. One independent review and one
correction/recheck cycle are allowed within that finite work budget.

Version 2 preserves v1 and corrects an offline-discovered capability assumption:
the installed CLI rejects built-in provider retry overrides. No live call occurred
between these definitions. The rejected assumption is retained in v1; neither
version claims a global financial cap or a hard hidden-request count.
