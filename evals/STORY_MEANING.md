# Story meaning prompt experiment

This branch tests one short instruction for an observed semantic error: an
accepted timeline called a newly diagnosed crew member a correction to an
earlier negative-tested cohort, then omitted a later source clarification that
the person had left the vessel earlier. The relevant current text and earlier
source captures were available. Exact quotations and structural validation did
not make that inferred comparison correct.

Base: `78bd7678b4f4a3be079597b5c5fd062537965088` (the schema-only variant). The only changed
application file is `news/tasks/trajectory.md`. Its added paragraph is:

> Before labeling a correction or disagreement, compare the subject, cohort, occurrence, claim and time referred to; different scopes or later states are not inherently conflicting. Prior generated summaries, labels and change judgments are interpretations: verify them against the supplied immutable source text. If current evidence clarifies a scope difference or undermines a prior interpretation, explain that distinction with exact evidence in the new observation; do not repeat the prior interpretation as a source-established fact.

The old prompt already requires an explicit source revision for a correction.
Repeating that requirement alone would be redundant. This addition makes claim
comparability and rechecking earlier generated interpretations explicit; neither
was an operational instruction in that form. It is a plausible, unproved
prompting hypothesis, not a deterministic semantic check. No examples, case
names, blacklist, new judgment type, verifier pass or framework are added.
Schema, runtime, retrieval, model (`gpt-6-astra`), medium reasoning and transport
remain byte-identical to the base. The prompt continues treating source fields
as untrusted data.

## Motivating evidence and limits

The original `long-stories-01` accepted May 22 output says the diagnosis revises
the May 21 Rotterdam-arrival account. Its May 25 input contains the earlier
Tenerife-disembarkation clarification, both source captures, and the prior
generated correction; the published timeline still omits the distinction.
The source-only rubric had already required keeping these cohorts separate.

The exact motivating artifacts are under sibling worktree
`story-evolution/.news/`; their SHA-256 values are frozen below. They are not
new evaluation labels. The independent May 26 failure review concerns a separate
rejected malformed answer, which this prompt change does not claim to fix.

| Artifact relative to that `.news/` root | SHA-256 |
|---|---|
| `experiments/long-stories-01/state/runs/7f8efdfe011b4a7e860b36b1085b3c7a/input.json` | `571ae4a3bc29778b085668a7c47342f8f28bddb8d3b1dd5cec6c2dcc4db7d3d9` |
| `experiments/long-stories-01/state/runs/7f8efdfe011b4a7e860b36b1085b3c7a/result.json` | `ab131e95acb413bf32a191aa62d98816f2b9da76dcfb2d26f22350d218e6f9ac` |
| `experiments/long-stories-01/state/runs/7f8efdfe011b4a7e860b36b1085b3c7a/briefing.md` | `610c0f07ed81094f47e36dedc77c105db611648bcf77832053ac365a1d4faf49` |
| `experiments/long-stories-01/state/runs/59ac4440800b4f0aa9fe0e933b0ad5c8/input.json` | `35c2f29bac738ebc3356686277c312a5a8c4f9fe194acacff15184430ada0645` |
| `experiments/long-stories-01/state/runs/59ac4440800b4f0aa9fe0e933b0ad5c8/result.json` | `57ee3f04ad766c852a54dd11977e53b62cfa5507a2a891497bf4bd15b0e48fed` |
| `experiments/long-stories-01/timelines/s-daf2bc20b21f1c833128.md` | `6ee29b57809b494d297ceb3341026f42db90406d5daeb4eea828de80b0000952` |
| `experiments/long-stories-review.json` | `406057c445e3eac9e36b729792d4c929e6c7f93400288f02eaa1e219a61c950d` |
| `experiments/long-stories-01-failure-review.json` | `d64d80004e7ed57cd50bd4e64280957ce6ea81e39c54bd070280fc40b6e0e75a` |

The author selected the trajectory corpus, authored its frozen questions,
reviewed baseline outputs and the first story run, and has seen the motivating
failure. This is a known-case development experiment, not an untouched holdout.
No schema-only fresh-replay outputs or meaning-variant outputs were viewed while
specifying this change. A separate evaluator must review it before live calls.

A prompt cannot erase immutable historical observations, reassign old captures,
or repair stored event identities. A later observation can explain a
source-supported distinction. Fresh replays also cannot demonstrate recovery
from a particular prior generated mistake if they avoid that mistake entirely;
record that recovery behavior was not exercised rather than counting it as a
separate success. One current article is still assigned once, so the existing
representation can limit how multiple developments in one source are expressed.
No claim is made that this paragraph resolves those design limits.

## Frozen evaluation plan

Compare this prompt variant with a fresh schema-only replay, never by resuming
or repairing the first partial run. Use the exact frozen snapshots, their
external order and ordinary within-batch validation order. Do not send rubrics,
review notes or expected answers to the model. Preserve original labels and
all earlier runs. The fixture root is the sibling `story-evolution/.news/`.

| Corpus | Path from fixture root | Maximum calls | Records | Frozen questions |
|---|---|---:|---:|---:|
| main | `long-horizon` | 20 | 34 | 15 |
| synthetic | `correction-fixtures` | 3 | 6 | 6 |
| sparse | `long-horizon/sparse-music-on` | 3 | 3 | 1 |

One fresh state per corpus, one replay per arm, 360-second deadline per call:
the meaning arm has a total ceiling of 26 calls, with no automatic retries.
Stop each corpus at its first failure and retain partial outputs; the other
independent corpora may still run within their own ceilings. Do not increase a
ceiling or tune between corpora. Any further repeat or prompt revision requires
a separately named, declared protocol. These are model-call deadlines, not a
claim of a strict combined wall-clock cutoff.

Before execution, the evaluator must approve the prompt and protocol, and
`evals.evolution.preflight` must verify each original manifest/rubric/review.
Record the actual source hashes and runner revision in every run. Root may
cherry-pick the shared harness/protocol into this worktree; require the same
runner behavior and settings in both arms and recheck all application hashes.
If other measured behavior differs, disclose the difference and do not call the
result a prompt-only comparison. Do not select this variant before reviewing
the schema-only fresh replay.

Use `--engine stories`, each corpus's `--max-calls` and `--timeout 360`.
Prepared and rubric paths come from that corpus; sparse uses the shared
`long-horizon/label-cross-review.json`, while synthetic uses its own review.
Reserve fresh output names `.news/experiments/main-story-meaning-01`,
`synthetic-story-meaning-01` and `sparse-story-meaning-01`.

All 15 main, six synthetic and one applicable sparse question retain their
frozen wording, references and 0/1/2 interpretation. Missing accepted inputs
remain explicitly unscored, with rejected/unprocessed accounting; do not turn
them into semantic zeros or drop them. The motivated comparison is the existing
Hondius cohort question, especially an unsupported correction and any later
clarification. Its expected answer is unchanged. Also inspect every accepted
reader artifact for new unsupported claims or false links, beyond that target.

Review actual daily briefings and as-known/final story pages. Use inputs,
retrieval, assignments and immutable quotes for diagnosis, not hidden-history
presentation credit. Separate story membership, event identity, claim scope,
source correction, unresolved disagreement, chronology, attribution and false
closure. Retain synthetic conflicting reports, the explicit publisher
correction and continuing disagreement; verify sparse origin continuity.
Report calls, failures, duration, input/output tokens, unknown usage and full
request size. Use the same accepted prefix for limited runtime comparisons.

Prefer the variant only if independent review finds the motivated error reduced
without new material source/identity errors in the same observed coverage, and
the planned replays complete. If coverage differs or evidence is mixed, report
that instead of selecting a winner. These few known, purposive fixtures cannot
establish overall story quality or a reliable population error rate. No sum of
question grades becomes an overall quality percentage or a promotion claim.

| Frozen evaluation file | SHA-256 |
|---|---|
| `long-horizon/prepared/manifest.json` | `53f30de106080b4bef05e017bcfe9a5fb045bdbff9159b1333a4c3a7fe7ddefa` |
| `long-horizon/rubric.json` | `6887b4da6ef570b7801d00549d36bb96b5912f5f94c6648ccf9d8801299c7ac4` |
| `long-horizon/label-cross-review.json` | `6bc98a32ad28664fc07ed5d221636a02452e248051fb444c03ca4f754f94de56` |
| `correction-fixtures/prepared/manifest.json` | `db664b33369b9743cfb95825ae9a96a8815b4e589551c77bc4288ac00e76868a` |
| `correction-fixtures/rubric.json` | `8ce3ea59f87927a5b3a7197a65005ebeb09f7db080a38b86dca17f50287f046f` |
| `correction-fixtures/label-cross-review.json` | `e64b817eb64971784422ba02191f3a469dc607b245932ef553e679849cdb367d` |
| `long-horizon/sparse-music-on/prepared/manifest.json` | `dec3ea28632d78f2d7da8e4b214c2079f56bb1d1feebbc19a6cdda71ceee3f1e` |
| `long-horizon/sparse-music-on/rubric.json` | `1cb8bd34582c75756e10d05217afb78d8ab1bdc575f449aecdf03521332cfb21` |

## Offline checks and freeze

All three existing fixture preflights pass (20/34/15, 3/6/6 and 3/3/1 for
snapshots/records/questions). The existing focused offline suite passes:
`python -m pytest -q tests/test_story_schema.py tests/test_story_trajectory.py tests/test_evolution.py`
— 55 tests. No new test mirrors the prompt, and none establishes its semantic
benefit. No model calls were made during preparation.

- Old task SHA-256: `cbce086f17541f203d949dd61690e2e88adc53ad6a3b3c04f4eacb81df166b71`.
- New task SHA-256: `0e46584b4a810fa78c22a02a24b173d6a9ad8d3edb24194c199e2bd7f778e672`.
- Unchanged schema SHA-256: `be35a90bc90064a7ece86f8c1efd24f909b51d8c76ab3e0898da5d2281a4a872`.
- Unchanged runtime SHA-256: `67f8d4cda8d31d8fd2ab6a91c8bdadfd0de1b19306963c29651390881ffdf403`.

Local `.news/meaning-protocol.json` records per-file fixture hashes, the exact
added paragraph and this predeclared plan. `.news/meaning-byte-identity.json`
compares every tracked base file and every application byte. Only the task
paragraph and this document are committed for this experiment. The independent
review is a separate artifact; do not amend the frozen task after outputs.
