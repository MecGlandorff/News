# Independent integrated technical review

Initial reviewed commit: `19f554b3fb4b61826b1dd07939e864582b198bae`, initially clean.
Fix re-reviewed: `636f9ca6b3d85b8d93aa27d7d8a945d74ba7dd65` in the clean
`news2/reference-validation` worktree. **All four findings below are resolved
by that patch; no remaining technical blocker was found for this research scope.**
Reviewer: independent `gpt-6.1-sol`, high reasoning. This review changes no
source packet, original label, adjudication, amendment or exposure record.

The intended development reference can be assembled and its present data passed
independent integrity checks: 34 selected gold-v1 records with the active
`source-span-locators-v2` amendments, plus the three fresh C08-v2 records. The
repository's executable validator at the initial commit did not validate that
effective set. The following small validator/selection changes were requested
and subsequently verified in the fix review recorded below.

1. **Effective selection is not checked.** `labels/validate.py:96` hardcodes the
   archived A/B/C/v1 sets; its `gold_prefixes: 37` includes exposed C08-v1.
   It never reads `adjudicated/eligibility.json`, the C08-v2 manifest or D/E.
   In a temporary copy, deleting `adjudicated-c08-v2`, `d-c08` and `e-c08`
   entirely still produced exit 0. Clearing the eligibility exclusions also
   produced exit 0. Documentation candidly limits this command to v1, but there
   is no single executable check of the intended 37 records. Add one modest
   effective-prefix manifest selecting exactly 34 v1 bases plus 3 C08-v2 bases,
   pin the active amendment and eligibility artifacts, and validate the selected
   files and input hashes. Exposed C08-v1 and the rejected amendment must be
   ineligible selections. Preserve all archived bytes.
2. **Malformed spans and nested schema omissions can pass.** At
   `labels/validate.py:35`, the walker recognizes a span only when all four
   required keys already exist. Replacing an ordinary contribution's spans
   with `[{"observation_id":"O999","field":"text","start":0}]` passes
   `check_record`, because `end` is missing. Deleting the required contribution
   `claim` also passes: lines 53–57 check only kind and nonempty spans. Both
   changes passed the full CLI in temporary audited fixtures. Require the
   documented fields/types for contribution, relation, delta, question and span
   records before checking their values; malformed source references must fail.
3. **Embedded provenance is incompletely checked.** Lines 115–122 verify the
   raw gold and source-packet hashes, but not the gold's `label_inputs` against
   actual A/B/C inputs and its audit, nor its checkpoint against the packet.
   Changing `adjudicated/C07-p01.json` to contain an all-zero A-input hash or a
   2099 checkpoint still passes when its new raw hash is correctly audited.
   Check inventory version, checkpoint and embedded input hashes against their
   authoritative inputs; extend the same check to D/E and C08-v2.
4. **Span validation depends on interpreter optimization.** The `assert`
   statements at lines 39–42 disappear under `python3 -O`. An audited
   out-of-bounds span is rejected normally and accepted under `-O`. Replace
   validation assertions with explicit conditional errors.

The matching audit updates in the negative fixtures isolate schema/provenance
validation from ordinary byte-tampering checks. They do not alter real audits
or imply an attacker can modify frozen artifacts without detection. Original
files were copied to temporary directories; all mutations occurred there.

Checks actually executed at the reviewed commit:

- All 11 offline source-export tests passed.
- The documented v1 validator passed with zero errors, 37 v1 records, 17 active
  locator amendments across 14 prefixes, and byte-identical 37/37/4 A/B/C
  originals and audits. It retained the disclosed original A C01-p03 enum issue.
- A separate standard-library check assembled exactly the intended 37-prefix
  reference and verified packet membership, source/inventory identities, all
  gold/input/audit/manifest hashes, active amendment bases, eligibility audit,
  checkpoint values, contribution/delta/relation references and all 456
  effective source-span entries. No current-data integrity failure was found.
- D/E files, audits and summaries were byte-identical to their original local
  outputs. The C08 manifest/audit matched all three fresh golds and their D/E
  inputs; all 36 C08 decision JSON Pointers resolved. D/E audits and C08 freeze
  order were chronological. These artifacts report procedure; they cannot
  independently prove what a model had previously seen.
- Negative fixtures correctly rejected corrupted packet bytes, a complete span
  naming an unavailable observation, an unresolved delta contribution, and
  substitution of the rejected locator-amendment draft. The acceptance gaps
  above are separate from these functioning guards.

Source-entailment samples compared complete claims with their actual cited slices
at C01-p01, C04-p02, C09-p01, C11-p02 and C08-p01. The active locator additions
support the sampled compound clauses. C04 preserves unresolved attack identity;
C11-p02 does not invent the later numerical explanation; C08 remains limited
to its headline and repeated promotion. No semantic blocker was found in these
samples. This reviewer had already read later source material during the earlier
cross-case audit: this is an exposed review, not new blind gold or a comprehensive
semantic certification.

The updated protocol correctly requires cross-case future-exposure accounting
and a reviewed dependency-cluster map. C01/C08 overlap, uncertain C03/C04
background dependence, curated grouping, simulated historical clocks, incomplete
coverage and missing mixed-stream/full-slice/holdout/prospective evidence remain
explicit. Twelve bundles are not twelve independent trajectories. No statistical
or quality gate is established by this artifact review.

No application/model experiment, CI, push, merge or production action ran.
Research-agent token usage/cost is unknown. Bootstrap dependency and current
remote PR state were not independently queried.

## Fix verification

At `636f9ca6b3d85b8d93aa27d7d8a945d74ba7dd65`, the patch changes only the
validator, a plain effective-reference manifest, synthetic executable tests and
the labeling document's command/status description. Immutable labels, audits,
amendments, source manifests and packets are unchanged. The standard-library
script and explicit JSON selection are appropriate for this phase; no storage
framework, model stage or application implementation was introduced.

Independent execution of all 23 offline tests passed, including the 12 new
validator tests. Running the validator against the original frozen packet path
and original A/B/C outputs passed: archived 37 v1 records preserved; effective
selection exactly 34 v1 plus 3 fresh C08-v2; 17 active locator amendments;
zero errors. Archived and effective counts now appear separately in its output.

Twelve additional reviewer-controlled negative probes used temporary copies of
the actual reference archive. All rejected: missing complete C08-v2/D/E
directories, a missing E original, removed eligibility exclusions, malformed
future span missing `end`, missing contribution claim, incorrect embedded input
hash, incorrect checkpoint, complete future span, out-of-bounds span under
`python -O`, exposed C08-v1 selected with its correct raw hash, rejected amendment
selected with its correct raw hash, and a future-prefix D/E decision reference.
Schema/provenance probes refreshed the gold/audit/selection hashes needed to
reach the underlying checks; the future decision probe refreshed all affected
v2 pins. These are executable rejection checks, not prompt-string assertions.

The effective selector checks exposure exclusions and supersession, pins the
active amendment/history, validates D/E and fresh C08 provenance, and checks
same-prefix decision-pointer resolution. Nested record fields and exact span
shape/types/bounds are checked directly; interpreter optimization no longer
removes them. Embedded v1 input hashes, audit metadata and checkpoints are
cross-checked against their inputs. This resolves the original four findings.

This approval concerns reproducible source/reference integrity and the modest
implementation. It does not establish semantic truth, independence, global
temporal blindness, candidate quality, recovery or production readiness. The
earlier exposed semantic-sample limitations and all later research gates remain.
