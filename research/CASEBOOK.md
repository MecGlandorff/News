# Frozen development casebook v0.1

This is a finite source packet for independent labeling before candidate runs.
It is not a news pipeline, semantic gold, or a holdout. Selection used source
fields only, without consulting old reports, briefs, memory, generated labels,
evaluation outputs, or candidate outputs. No application model calls or external
fetches were made to assemble it. Research was performed by `gpt-6.1-sol` agents
with high reasoning; research-agent token/cost telemetry is unknown, not zero.
All archived material is **development / prior exposure
unknown**. A new labeler does not change that classification.

Known: the frozen selection contains **12 cases, 49 source observations, 46 source
field versions, 44 URLs, and 37 cumulative prefixes**. Eight cases use authentic
archive capture timestamps from six polls on October 5–7 and 10–12, 2026. Four
cases use historical publication-order simulation. Two cases contain sources
from one simultaneous capture and consequently have one prefix each. Sources
selected for this version are pinned by exact relative filename, zero-based row
index, archive file SHA-256, canonical raw-row SHA-256, and canonical sanitized
source-field SHA-256.

The canonical packet-index digest is
`8a15c20ece6f91898f05a814df53c85ac3e2b0851fdd24cfa2cb97ba8854e3f9`.
The byte SHA-256 of `casebook/freeze.json` is
`1a3ae8e3ed850da88dee4d21eaf840caf038b3427feebdaa074e907108145cb4`.
The source/case digests and counts are in that freeze file. Packet hashes use
UTF-8 canonical JSON (`ensure_ascii=False`, sorted keys, compact separators),
not the pretty-printed packet bytes. The index hashes each canonical prefix;
its canonical hash is the packet digest. Traversal is filenames only and is not
part of that semantic packet digest.

## Rehydrate locally

From the repository root, with the source archives available:

```sh
python3 research/prepare_casebook.py \
  --legacy-root /Users/mrgreen/Desktop/AI/News/data/daily \
  --capture-root /Users/mrgreen/Desktop/AI/News-worktrees/from-scratch/.news/dogfood/captures \
  --output .news/research/casebook-v1-rehydrated
python3 -m unittest discover -s research/tests -v
```

The Python standard library is sufficient (Python 3.9+). The command does not
read reports, run application code, call a model, fetch URLs, or expand its source
selection. It reads only pinned source JSON files. It checks every article's
schema in each accessed snapshot, verifies file/row/source hashes and timing,
and exports only the source-field whitelist. Known legacy generated fields
`theme`, `story_label`, `importance`, and optional `occurrence_id` are omitted,
as is the old `id`. Unexpected article schemas fail closed. The exporter does
not interpret source prose as instructions.

All input and frozen packet validation completes before writing. Existing
identical output files are left untouched, including their modification times;
an existing conflicting file aborts before any output write. There is no force
overwrite switch. Use a new output directory for an independent reproduction.
Unrelated existing files are never deleted. Runtime source text belongs under
ignored `.news/`, never in a commit. The original labeling directory
`.news/research/casebook-v1/` is frozen; do not mutate it while labeling.

## Blinded labeling boundary

Give labelers only `traversal.txt` and the referenced prefix files, plus the
separate labeling protocol. Read a case's prefixes in order, save an immutable
answer to the earlier prefix, and only then open the next. Each prefix contains
only sources available under its declared clock. Do not give labelers the
selection-notes file or later answers, candidate outputs, or other labels.
The neutral case manifest contains no mechanism hints but is unnecessary for
labeling. The full traversal contains 37 filenames.

Each prefix has `case_id`, `prefix_id`, `chronology_mode`, `checkpoint_at`,
`source_version_ids`, and cumulative `observations`. Each observation contains
only original whitelisted fields plus provenance, publication/capture clocks,
snapshot day, and character counts. Repeated observations retain their own
`O...` identities; identical sanitized source fields share an `S...` identity.
A URL with changed fields has a distinct source version. These are field-version
identities, not a claim that a publisher changed the underlying article.

Evidence spans refer to `observation_id`, `fields.<field>`, and half-open
`[start,end)` Unicode codepoint offsets in the exact decoded string. HTML and
escaped line-break strings are preserved. Labels can cite these offsets without
committing copyrighted source passages. Character counts describe availability,
not semantic sufficiency. Thirty-three selected observations have nonempty
`text`; the other sixteen have source `description` fields of varying length.
An RSS text field is not evidence that a full article was captured.

## Clocks, provenance and coverage

`captured_observation` uses the capture manifest's UTC `captured_at` as the
observation clock. Publication time remains separate. Sources in one poll enter
the same checkpoint; no arbitrary within-poll sequence is treated as observation
history. Gaps between polls are not quiet-news evidence. A source may have been
available externally well before this archive first observed it.

`publication_order_simulation` orders historical source versions by their parsed
original publication fields, with `observed_at: null`. Snapshot directory dates
are retained separately. Authentic capture times cannot be recovered from those
article files. Publication timestamps may be retained through source updates,
and a later saved source can contain retrospective content. In particular, a
source correcting an earlier claim can have a timestamp preceding a stale
uncorrected source from another publisher. These prefixes **do not establish
authentic as-known chronology**, causal sequence, or valid online latency.
This uncertainty must remain visible in labels and results. Do not retrofit
fictional capture dates or infer occurrence time from publication time.

The frozen inventory verifies 41 legacy snapshots, 18,912 observations, 15,123
URLs and 15,565 sanitized source versions; only 85 rows have nonempty `text`.
Most evidence is RSS description material. April 25–May 28 has 34 consecutive
snapshot dates; there are 53 missing calendar days before July 21. Earlier dates
also have gaps. There is no claim of complete publisher or daily coverage.

The six frozen capture polls contain 569 observations, 503 sanitized source
versions and 489 URLs. Their 18 raw feed archive SHA-256 checksums were verified
at inventory freeze and are listed in `casebook/inventory.json`. Rehydration
verifies the pinned parsed-source file hashes; it does not reparse or recapture
feeds. Some captured texts are only photograph credits or promotional snippets.
Differences between polls may reflect acquisition/extraction changes as well as
source updates. A dedicated source-quality experiment would need to distinguish
them using the preserved raw feeds; candidate architecture comparisons must use
the same frozen fields.

Stale: the earlier six-poll inventory was no longer a complete inventory of the
directory on October 23. Polls 7 and 8 exist but are explicitly excluded. Their
article texts were not inspected for this assembly. They are **unassessed;
reserved for a later exposure audit**, not a fresh holdout. No later glob-based
replay can silently add them: source locators pin only polls 1–6.

## Scope and remaining gaps

Selection probes same-occurrence developments, nearby competing matters,
repeated observations and same-URL field changes, insufficient text, source
correction language, questions and later reports, and a historical trajectory
with a publication gap greater than 14 days. These are sampling intentions;
independent labels must establish which mechanisms the evidence actually
supports. They are not frozen expected conclusions. The unblinded selection notes
record intentions without assigning story memberships or expected deltas.

The case-grouped labeling packets **are not valid candidate inputs for measuring
unassisted story discovery or retrieval**. Their grouping leaks selected
relevance. This is a curated diagnostic casebook, not a complete day or a
representative archive mixture. A later candidate harness must withhold case IDs
and grouping and construct a mixed chronological stream with background sources,
using the same matched source corpus for every candidate. Full-slice evaluation,
including rejected and pending work, is required before broad quality claims.
This labeling export alone is not a replay-ready quality corpus.

Unknown: a clear unrelated-matter roundup is not guaranteed represented. The
selected liveblog excerpt is relatively narrow, and a liveblog title alone does
not prove multi-matter coverage. Thirty-, sixty-, and ninety-day authentic
trajectories, adequate full-text coverage, calibrated model quality, genuine
fresh holdout performance, and automatic recovery are also unestablished.
No synthetic source examples were mixed into this natural packet.

Automatic repair needs separate **derived-state probes**, after independent gold
and adjudication are frozen. The intended probe family can contaminate an
interpretation with an unsupported merge, a lost contribution from a multi-matter
source (once such a source is established), a stale contradicted claim, or an
unresolved item incorrectly marked complete. Preserve the original source
packet, contaminated derived state, expected permitted repairs, audit history,
and fresh-reconstruction reference separately. Such injected errors are synthetic
state corruption, never natural source corrections or additional news. This
casebook contains no repair outputs and does not demonstrate recovery.

Validation establishes reproducible preparation and guardrails, not story
quality: eleven offline tests cover generated-field leakage, schema drift,
file/row/source integrity failures, revision/repeat preservation, empty/duplicate
identities, chronology and future-source boundaries, path containment, and
non-destructive output handling. A separate rehydration reproduced the frozen
packet digest. Source labels and evaluation remain independent work.
