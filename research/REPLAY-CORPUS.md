# Offline replay corpus audit — 2026-11-01

This slice supplies frozen synthetic contract controls and a reproducible,
ungrouped **partial captured-source diagnostic**. It establishes no architecture
winner, semantic detection, automatic recovery, retrieval quality, real-world
importance, human usefulness, or authentic 30/60/90-day reliability. No application
model call, live search, new archive selection, production action or source-label
amendment was made. Research author: `gpt-6-astra` / xhigh; token/cost telemetry
is unknown. Initial preparation and validation took approximately eight active
minutes, within the two-hour corpus allocation; later review work is separate.

## Frozen synthetic controls

[`definition-freeze-v1.json`](replay-fixtures/definition-freeze-v1.json) pins exact
file bytes before any candidate script or output was inspected. Its invented
sources have nine observations, eight source-field versions and seven boundaries
at 0/1/2/3/30/60/90 elapsed days. They mix insufficient text, two independent
contributions in one source, unrelated similar names, a repeated observation,
a same-occurrence update, an uncertain supplier link, a later correction and a
late established relationship. Missing fixture dates are coverage gaps, not
quiet-news evidence. These are deliberately synthetic clocks and expectations.

Candidate inputs are the `synthetic-*.json` files at the fixture directory root.
The `scorer/` directory contains author expectations, reference mappings,
contaminated states and hashes. **Never give that directory, its filenames or its
metadata to a candidate.** The runner may give a selected plain prior state to I
under its normal interface; it must not attach defect IDs or expected repairs.
No candidate gets the locator manifest or original case/source IDs.

The active recovery manifest is
[`scorer/recovery-manifest-v2.json`](replay-fixtures/scorer/recovery-manifest-v2.json).
Its P04 source prefix contains seven visible observations. A valid contaminated
state seeds an unsupported museum/bridge relationship, an omitted transit
contribution, a stale count and questions closed without evidence. A separate
processed-empty accounting state must be rejected structurally. A clean historical
view and a repair-only response are distinct; the latter has empty news deltas.
Runner-generated version/supersession metadata must link any actual replacement.
An authored clean response is one permitted reconstruction, not an exact-string
semantic oracle. Scripted repairs demonstrate persistence/interface mechanics
only; automatic semantic detection remains unmeasured.

Frozen v1 state files remain as failures: their repeat observation was marked
processed without a matching contribution citation. V2 adds that exact repeat
span; original source definitions and expectations are unchanged. The v2 manifest
records the correction. This was found by contract inspection/validation, without
candidate output inspection.

[`synthetic-search-clock-v1.json`](replay-fixtures/synthetic-search-clock-v1.json)
is a separately frozen append, with private expectations in `scorer/`. An empty
January search establishes no negative fact; an old January publication fetched
in April enters only in April. A negative probe exposes the fetch event early
while keeping its source in the future and must fail before candidate execution.
The baseline excludes these events/sources. Event accounting is synthetic, with
unknown timing/cost retained as null. No actual search, semantic search-quality
label or new benchmark is implied.

## Existing captured diagnostic

[`scorer/observed-capture-locators-v1.json`](replay-fixtures/scorer/observed-capture-locators-v1.json)
selects **only the 33 existing captured observations, 30 field versions and six
polls** from frozen C01–C08. It excludes the 16 publication-order-simulation
observations in C09–C12. It pins the effective reference, active locator
amendment, eligibility/history artifacts, exact packet bytes, original observation
and version, capture time, archive filename, row index, file hash and row hash.
The effective selection remains 34 v1 plus three C08-v2 development labels;
pinning it neither makes all records globally time-blind nor supplies newly
adjudicated cross-case or mixed-stream expectations.

The bounded standard-library exporter checks those pins and source-field hashes,
then assigns neutral chronological observation IDs and source-hash-derived version
IDs. It emits only source fields, clocks, source IDs/hashes, neutral boundaries
and coverage. Equal-time sources enter together; deterministic hash order within
a poll conveys no earlier/later availability. Grouping, label paths, old IDs and
scorer metadata do not enter the candidate manifest. Real text is written only
under the checkout's ignored `.news/` directory. With an existing frozen packet
copy, run from the repository root:

```sh
python3 research/replay-fixtures/materialize_observed.py \
  --packets .news/research/casebook-v1
```

The packet argument can name another local frozen copy. The helper neither globs
archives nor expands selection; differing existing outputs are refused. The
tracked locator manifest alone is not directly executable candidate input.
Materialization succeeded locally and the result passed the replay schema.

## Dependency and exposure map: bounded, incomplete

This map carries forward source-only labeling and technical-review findings from
[LABELING.md](LABELING.md), [LABELING-C08.md](LABELING-C08.md) and
[FINAL_REVIEW.md](FINAL_REVIEW.md). No new source semantic labeling was performed.
Packet/provenance metadata were checked; neither filenames nor disjoint URLs are
evidence of semantic independence.

| Units | Known evidence / unresolved dependence | Consequence |
| --- | --- | --- |
| C01 ↔ C08 | Established same-matter overlap. A/B and original adjudicator saw later C01 before earlier C08. | Preserve exposed C08-v1; effective reference uses separately frozen C08-v2. Treat both bundles as dependent. |
| C03 → C04 | Later C03 background was seen before earlier C04; thematic/background influence is plausible, actual effect unknown. No operational/occurrence connection established. | Neither force a merge nor certify independence or temporal cleanliness. |
| B C04-p02 | Read-before-successful-save exposure to C04-p03. | Exclude that strict temporal vote; preserve original and fresh C-based replacement provenance. |
| C02, C06, C12 | Existing adjudication describes multiple matters within bundles. | Bundle count cannot be used as independent trajectory count or exhaustive multi-matter coverage. |
| C05, C07, C09, C10, C11 and remaining pairs | Earlier finite audit established no additional same-matter overlap or exact cross-case source intersections; latent dependence remains unknown. | Do not treat these as certified independent units. A reviewed source-grounded graph remains missing. |
| All retained sources/labels | Development/prior exposure unknown; grouped labels leak selected relevance; source-only and candidate-output blindness differ. | Neutral export removes grouping fields, not selection bias or historic exposure. No fresh holdout claim. |

The capture stratum covers October 5–7 and 10–12, 2026; October 8–9 is a gap and
every represented day omits unselected sources. Publication simulations remain a
separate stratum with authentic availability unknown. C09's publication gap over
14 days does **not** establish a required same-matter connection. The current
map is not a complete semantic dependency graph, and no independent-trajectory
denominator or uncertainty interval is derived from it.

## Missing evidence and bounded next collection

| Missing claim/category | Evidence needed before making it |
| --- | --- |
| Complete daily development/omission and retrieval quality | Freeze full source slices with all background, failures, pending work and feed coverage; label omissions as well as emitted results in global prefix order. The present 33-source mixture cannot substitute. |
| Authentic 30/60/90-day continuity | Collect timestamped, versioned prospective observations across those periods, including genuinely supported late links and explicit missing polls. Synthetic gaps and historical publication clocks remain separate denominators. |
| Robust multi-matter extraction | Independently source-label diverse complete mixed documents and unrelated-matter roundups; quantify lost contributions. Existing multi-matter bundles and one invented digest establish expressibility only. |
| Natural correction versus interpretation error | Add source-grounded corrections with verified observed ordering; distinguish delayed acquisition/extraction changes from publisher corrections. Existing C10/C11 simulations and the invented correction do not establish live chronology. |
| Dependency/temporal exposure and fresh holdout | Complete a bounded source-grounded relationship/exposure audit, retain unknown edges, then freeze genuinely unexposed sources and global label order before outputs. New agents or unassessed captures are not automatically holdout. |
| Automatic semantic repair and human usefulness | Freeze detectors/arms without defect metadata, test recovery on matched inputs with supported omissions, retain judge disagreements and sample human source/product judgments. Authored controls and judge agreement alone cannot establish either. |

The parent-supplied November 1 count audit was not independently recounted here:
41 legacy snapshots / 18,912 observations / 15,123 URLs; 33 recent polls on
October 5–November 1, with 30 complete and three failed, 2,889 observations,
1,709 URLs and 16 capture dates, including gaps October 8–9 and 13–22. This
larger directory is **outside** the unchanged frozen selection. Counts establish
neither complete-day coverage nor an authentic 30-day test; no new capture text
was read for this slice.

## Verification and limits

Offline checks accepted all three synthetic manifests, the clean/contaminated/
repair-only v2 structures, and the 33-observation materialized diagnostic. They
verified every definition/state/search hash; rejected preserved v1 repeat
accounting and the intentionally invalid v2 accounting; checked late-fetch and
baseline visibility; and rejected future-linked search evidence, changed
reference/packet/source/provenance pins, earlier availability and path escape.
These checks validate actual hashes, data and executable boundaries, not source
string matches. The corpus author inspected validator code after definitions
froze, without reviewing candidate/application outputs. Semantic scores,
automatic detection, live-call cost and human validation remain unmeasured.
