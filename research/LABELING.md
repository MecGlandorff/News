# Frozen source-only development labels

All **37 prefix adjudications** are frozen in `casebook/labels/adjudicated/`,
with per-prefix source-packet hashes, input-label hashes, UTC save times and an
append-only audit. They are revisable development interpretations of supplied
sources, not factual truth, a fresh holdout, measured model quality or evidence
of reliability. **C08 gold-v1 is temporally ineligible** because of cross-case
future-source exposure; the fresh D/E-based replacement
[`adjudicated-c08-v2/manifest.json`](casebook/labels/adjudicated-c08-v2/manifest.json)
supersedes those three prefixes in the integrated research branch. See
[LABELING-C08.md](LABELING-C08.md) for its separate sequential procedure. Completion of these
37 records does not make all 37 future-source-blind or replay-ready.

The canonical inventory/index version is
`8a15c20ece6f91898f05a814df53c85ac3e2b0851fdd24cfa2cb97ba8854e3f9`.
The packet SHA-256 in label audits instead hashes the exact pretty-printed
prefix-file bytes. These are different hash domains and must not be substituted.
Source text stays in ignored `.news/`; tracked labels contain paraphrases and
Unicode codepoint `[start,end)` offsets into preserved raw fields, including HTML.

## Method and preservation

The independent adjudicator used `gpt-6.1-sol` with high reasoning. At each
traversal entry it read only the current packet and completed A/B/C labels,
verified the original label/packet hashes against an existing audit entry,
adjudicated from visible source evidence, and saved/hash-audited its decision
before opening the next case-local prefix. New observations were displayed in
full; previously read observations remained available in the cumulative packet.
No candidate/application outputs, old candidate artifacts, web sources or
application model calls were used. Selection notes, complete manifests,
CASEBOOK mechanism descriptions and labeler summaries were first read only
after all 37 gold-v1 saves. General event familiarity is not provably absent.

`labels/a` and `labels/b` preserve all 37 original JSON files and complete audits
byte-for-byte; `labels/c04` preserves the four independent C replacement files
and their audit. Originals remain unadjudicated records. B's original exposure
exception is also retained unchanged. Their labels are not votes: adjudication
uses evidence and records grouping, novelty, materiality, relation and question
choices in each gold record's `decisions` array. Original disagreements remain
inspectable rather than being erased by a consensus count.

Gold records use the protocol Section 4 fields, plus adjudicator identity,
packet/input hashes, clocks, visible observation IDs, decisions and scope.
Contributions accumulate within each case so a later record does not forget
prior evidence. Historical statements remain attributed history, not necessarily
current truth; `view_status` and uncertainty qualify revised or corrected reports.
Only the current record's `delta_expectations` describe its fresh delta.
Cumulative presence does not require reprinting every historical claim each day.
Required, allowed, prohibited and uncertain are distinct. Uncertain relations do
not establish a positive link; allowed details are not required recall units.
`no_delta_reason` explicitly requires a quiet result where supplied. No required
new delta also permits silence when the only possible refinement is allowed.
These compact source-supported units are not exhaustive atomic sentence labels
or final evaluation weights; a later scoring freeze must make unit matching,
current-view requirements and denominators explicit without inspecting outputs.

## Exposure restrictions

- **B C04-p02:** B saw O015 from p03 before its successful p02 save. It is excluded
  from strict temporal adjudication, preserved unchanged, and replaced for that
  decision by A plus independently fresh C and current source evidence. A
  reconstructed attempted draft cannot establish temporal cleanliness. C's four
  records can inform C04, without a majority-vote truth rule.
- **C08 p01–p03:** A, B and this adjudicator saw C01 through October 10 before
  C08 begins on October 5–7. C01 and C08 concern the same Flydubai matter. All
  three C08 gold-v1 records and both original votes are therefore exposed
  development records, not temporally clean references. Fresh C08-only D/E labels
  and an independent C08-only adjudicator supply the separately frozen v2 mapping.
  No old C08 record is rewritten. Original per-record
  tentative eligibility strings are overridden by `adjudicated/eligibility.json`.
- **Other exposure:** the separate technical review found no other established
  same-matter overlap in the retained 49 observations, and no cross-case exact
  observation/version/hash/URL intersections. This finite audit cannot establish
  absence of latent dependence. C03's October 12 Iran/IRGC and Fairford bombing
  background preceded earlier C04 sources describing Iran-backed Houthis. Its
  effect is unknown; no operational or occurrence link is established, so neither
  a forced story merge nor confirmed contamination follows.
- **Within-case packaging:** A reported one save-then-open sequence in a single
  tool invocation at C01-p01/p02, with the earlier save completed before the later
  read. Its account supports the chronological ordering but is retained as a
  procedural caveat. No additional adjudicator case-local read-before-save
  violation was observed. This is distinct from the confirmed C08 cross-case
  exposure and the later rejected locator-amendment draft below.

Twelve case bundles are **not twelve independent trajectories**. C01/C08 share
a matter; C02, C06 and C12 contain multiple matters. A cross-case relation and
plausible-dependence cluster map remains necessary before mixed-stream scoring,
trajectory minimums or bootstrap uncertainty. Disjoint URLs do not establish
independence. Case-grouped inputs also leak relevance and cannot measure unaided
story discovery or retrieval. These labels do not replace the later mixed-stream,
full-slice, genuinely unexposed or prospective gates in the protocol.

## Semantic scope and gaps

The gold preserves source attribution and uncertainty, separates occurrences
from broader matters, allows unassigned evidence, and recognizes zero new
contributions on repeated captures. A new publisher or rewritten account alone
is not news. Newly captured old details can add evidence while retaining their
older occurrence/publication context. Source-version changes can reflect
acquisition/extraction differences; they do not automatically mean correction.

C04 initially leaves airport-attack identity uncertain, then uses newly visible
Saturday timing prospectively. Toll increases do not automatically become
corrections. C09 keeps unnamed-ship/patient linkage uncertain, limits negative
tests to people still aboard, and treats the later positive as a qualification
without inventing infection time, onward transmission or a thirteenth patient.
C10 supports explicit reporting corrections, including the original publisher's
later acknowledgment. C11's authority reduction is initially numberless; later
90-to-82 explanation does not imply the previously visible BBC 82 was corrected
or establish authentic 82-to-90-to-82 history. Legal labels distinguish confirmed
charges, allegations, arrest avoidance and forecasts from conviction or transfer.

C09 has a publication gap greater than 14 days, but the earlier ship is unnamed.
The supplied evidence does not establish a **required same-matter connection**
across that gap. Neither that sampling intention nor a long gap alone satisfies
a long-gap handling denominator. C09–C12 remain publication-order simulations,
with authentic historical availability unknown. Actual captures cover only six
polls on October 5–7 and 10–12; missing polls/days are not evidence of quiet news.
No continuous 30/60/90-day trajectory or sufficient independent sample is shown.

The source packet has multi-matter material, thin headlines/photo credits,
repeated promotion, qualified same-occurrence additions, disputes, corrections
and source-supported questions. It does not establish automatic interpretation
repair: no contaminated application state or recovery output exists. Derived-state
fixtures must be frozen separately. No quality floor or comparison gate has been
measured or passed, and this labeling exercise authorizes no model experiment.

## Locator amendments and validation

Original gold-v1 JSON/audit bytes remain immutable. Post-freeze source review
found several compound claims with in-bounds but incomplete inherited evidence
locators. `adjudicated/span-amendments.json`, active version
`source-span-locators-v2`, adds 17 locator amendments across 14 prefixes. It changes
no semantic claim, status or delta requirement, and uses only observations already
inside each affected packet. It was prepared after all later sources were seen;
it is not a fresh temporally blind adjudication and does not restore C08 eligibility.
A later scorer must explicitly freeze the amendment version and any supersession
manifest rather than silently changing the raw reference.

The first locator draft accidentally targeted an O016 answered-question span at
C04 p02/p03 copies of that question too. The validator rejected the unavailable
observation before use. The rejected draft bytes and audit history are retained;
v2 restricts that locator to p04. No original label, gold-v1 record or candidate
score was changed. The active amendment passes the same packet/span checks.

Run from the repository root, substituting a local rehydrated packet directory:

```sh
python3 research/casebook/labels/validate.py \
  --packet-root /Users/mrgreen/Desktop/AI/News-worktrees/news2/research-sources/.news/research/casebook-v1 \
  --original-label-root /Users/mrgreen/Desktop/AI/News-worktrees/news2/research-sources/.news/research
```

The optional original root verifies byte-for-byte preservation against the local
labeler outputs. The validator is read-only. It checks complete coverage/order,
raw packet/label/audit hashes, increasing gold save times, required fields,
Unicode span bounds and visible observation membership, relation/delta references,
status enums, and amendment base/history hashes and targets. The executed check
passed with zero gold errors, 37 gold records and 37/37/4 preserved originals.
It reports A C01-p03's original `partially_answered` question status as outside
the protocol enum; the original stays intact and gold uses supported separate
answered/open states. This validator checks the preserved v1 set and locator amendments; the separately
validated fresh C08 override is documented in LABELING-C08.md. A passing validator
does not prove semantic truth,
independence, temporal blindness, output quality or automatic recovery.

Application model calls: **0**. Research-agent inference occurred; token/cost
telemetry is **unknown**, not zero. No pipeline, CI, push, merge or PR was run
for this labeling work.
