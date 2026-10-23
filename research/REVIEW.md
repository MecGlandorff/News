# Independent review record

The protocol/casebook and source-only development reference are concrete research
artifacts, **not evidence of improved story quality**. The 37 gold-v1 records are
complete and audited, but C08 gold-v1 is excluded for confirmed cross-case future
exposure. The integrated branch selects the fresh D/E-based C08 replacement through
[`adjudicated-c08-v2/manifest.json`](casebook/labels/adjudicated-c08-v2/manifest.json);
[LABELING-C08.md](LABELING-C08.md) documents that separate adjudication.
Raw originals and v1 remain preserved. Labels do not authorize candidate calls,
production use or long-run claims.

This adjudicator's worktree was `news2/casebook-adjudication` at `3facfed`.
Assigned new artifacts are `research/casebook/labels/**`, `research/LABELING.md`
and this file. Existing protocol/exporter/test/source manifests were not edited.
The parent integrates these additions after author revision
`2481a1beff19e1ca7453360f1147805bda784be8`, its later cross-case protocol
clarification, and the separate fresh C08 replacement. The technical review below
identifies its exact reviewed revision; final integrated verification is separate.
Bootstrap PR #58 was declared pending at preparation; the intended PR target is
`News2.0`. No claim is made here that either PR was merged or current remote
state was independently queried.

## Findings and limits

- Source-only adjudication preserves required/allowed/prohibited/uncertain
  distinctions, original disagreements and unsupported identity questions.
  Repeated wording or recapture is not a fresh delta. Explicit corrections,
  revised attribution and changing reports retain provenance and historical scope.
- B C04-p02 is excluded; independent fresh C plus A supplied eligible current
  evidence. C08 v1 is temporally ineligible because C01's later Flydubai material
  had already been seen. Within-case save order and candidate-output blindness
  do not cure cross-case future visibility.
- Twelve selected bundles cannot supply twelve independent trajectory units.
  C01/C08 overlap; several bundles contain multiple matters. An independent
  cross-case audit found no other established same-matter overlap, while possible
  Iran/IRGC background exposure from C03 to C04 remains unknown. A conservative
  trajectory/cluster map and mixed input stream are still required for inference.
- C09's greater-than-14-day gap does not establish a required same-matter link
  from its unnamed early ship to later Hondius. Historical ordering is simulated;
  genuine 30/60/90-day and unattended recovery evidence remain absent.
- Policy thresholds and minimum denominators can screen development work only.
  These selected sources, single labeling exercise and agreement counts cannot
  establish reliability or superiority. Current labels are not exhaustive atomic
  claim annotations or output matching rules. Those rules and resource budgets
  must be frozen before any separately authorized comparison.
- Source-only gold cannot certify system repair without seeded derived state.
  Immutable source versions and revisable interpretations remain the proper
  boundary; no fabricated source chronology or manually patched output is allowed.

No further storage abstraction or model stage is justified by this work. The
small JSON records, audits and read-only validator are sufficient for this phase.
The restrictions above bound what can be inferred; they are not claims that
source preparation or semantic performance has passed a production gate.

## Validation actually executed by this adjudicator

```sh
python3 research/casebook/labels/validate.py \
  --packet-root /Users/mrgreen/Desktop/AI/News-worktrees/news2/research-sources/.news/research/casebook-v1 \
  --original-label-root /Users/mrgreen/Desktop/AI/News-worktrees/news2/research-sources/.news/research
```

Result: exit 0; zero gold errors; complete 37-prefix gold coverage; 37 A, 37 B
and 4 C originals/audits byte-identical to local originals; all raw hashes,
visible source spans, references and active locator amendments valid. One retained
original schema observation: A C01-p03 uses `partially_answered`; gold uses only
protocol question statuses. Gold save times increase in traversal order. This command checks v1 preservation
and locator amendments, not the separately validated D/E-based C08 override.

A first locator-amendment draft failed validation because one question ID also
appeared at earlier prefixes lacking the cited future observation. It was
rejected before use; bytes/history remain preserved. The active v2 amendment is
restricted to the supported prefix and passed. Gold-v1 bytes were never edited.
This is evidence of a guard catching a draft locator error, not proof of general
semantic correctness. No candidate output was generated or scored.

## Separately reported technical verification

Independent `gpt-6.1-sol`/high reviewer `/root/news2_technical_review` reviewed
protocol/exporter/tests at
`2481a1beff19e1ca7453360f1147805bda784be8` and reported **no technical blockers**.
That reviewer, not this adjudicator, executed:

```sh
python3 -m unittest discover -s research/tests -v
```

The reviewer reported all 11 offline tests passed; fresh temporary rehydration
reproduced canonical packet digest
`8a15c20ece6f91898f05a814df53c85ac3e2b0851fdd24cfa2cb97ba8854e3f9`.
It independently checked manifest/freeze/prefix hashes, clocks and membership,
six capture manifests and 18 archived raw-feed hashes, unchanged output mtimes
on identical re-export, and corrupted-freeze rejection before output creation.
It reported a clean tracked worktree. Those checks concern reproducible source
preparation and failure behavior; its initial review excluded the later labels.
The parent may separately verify the final integrated commit.

The same reviewer subsequently inspected retained title/description/text for all
49 observations for cross-case overlap. It confirmed C01/C08 Flydubai identity,
found no other established same-matter overlap or exact cross-case identifier/
version/hash/URL intersections, and retained uncertainty about C03/C04 shared
Iran/IRGC background. A finite audit cannot prove absence of latent dependence.

Application model calls: **0**; research-agent inference usage/token cost is
**unknown**. No application pipeline, CI, live quality experiment, push, merge
or PR was performed. Passing offline checks and independent review do not prove
story quality, recovery or online reliability.

The parent reports the fresh C08 replacement integrated as `a586c7b` from
`1983426`: three sequential C08-only adjudications, six byte-identical D/E inputs,
and an effective-prefix manifest. Its reviewer reported 45 raw-field spans and
36 decision references valid. The pilot item is allowed at p01, with no delta on
p02/p03. This adjudicator read its documentation/manifest only after its own
37 v1 records were frozen and did not re-adjudicate those fresh decisions.
