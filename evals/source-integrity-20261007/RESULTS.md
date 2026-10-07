# Source integrity: bounded promotion evidence

The candidate recovers RSS descriptions, makes headline provenance explicit and
checks story coherence automatically before storing a decision. It is suitable
for continued bounded dogfooding, subject to the separate final review. It is
not a claim of generally correct story evolution or successful automatic repair.

Application: `d3b63e2`; control: `a5fef508c26e301a59c039e200e4f10b7adf9e1f`.
The experiment branch descends from the automatic-integrity policy commit
`d1cc16ad1d2d126ef973bb15fc8609e60e10e1d8`. The policy forbids manual source,
assignment, journal or briefing patches. Neither arm edits production state.
The application has 2,109 physical Python lines in eight modules, an increase
of 154 over the daily-wrapper baseline. There are 309 passing offline tests;
Ruff lint and format checks pass. Application model calls are GPT-6 Astra / medium.

## Protocol and independent review

`plan.json`, `code-freeze.json`, `inputs/`, and `fresh-sources/` were frozen before
the main campaign. A fresh source-only agent selected 14 archive versions and
authored relationship, event and reader expectations without seeing generated
outputs. Root read all normalized sources and expectations, then independently
verified all 14 archive rows and 48 exact evidence spans before model execution.
The selected source pack is purposefully chosen, not random or human gold.

The Astra/max reviewer did not implement the changes. Its preflight corrected a
protocol weakness: fresh cases must actually supply all designated prior/current
cards, and candidate author input must equal baseline input. Failed coverage
stops before a call. The fixed-context cases use ten retrieval hits; they do not
prove default retrieval recall. The original ship/cat replay uses the unchanged
default three hits and asserts the full author payload equals the original.

Common prehistory is produced by the real pipeline and copied without changing
accepted rows. No handcrafted story assignments enter either arm. Each worker
verifies frozen code, prompts and source hashes. No model tools, web browsing,
project instructions or production writes are enabled by the news runner.

The original plan allowed at most 24 news CLI calls. It ended at 19 because failed
preparation made C01 unavailable and the rejected ship batch prevented its cat
follow-up. Those outcomes are final in `metrics.json`. An independently reviewed,
separately frozen follow-up spent the remaining five calls under its own ledger.
There were no automatic retries, altered prompts, amended source labels or
hand-repaired decisions. The separate experiment is explicitly output-informed.

## Results and counterevidence

| Test | Observed result | Interpretation |
| --- | --- | --- |
| Nine original RSS files | 135/135 Guardian descriptions recovered; metadata and 154 NOS/BBC polled versions unchanged | Deterministic parsing gain, no model-quality claim |
| Daily version selection | 97/81/83 candidate versions versus 97/80/82 original | Two real wording/typo revisions become visible after body recovery |
| Exact original ship/cat decision | Reviewer rejects unsupported grouping | Detection of the actual preserved failure, without editing it |
| Later cat update against contaminated story | Reviewer rejects inherited ship event despite the new title | Renaming cannot bypass full-history review; this does not repair old state |
| Existing valid control decision | Reviewer accepts | One positive control, not a false-rejection rate |
| Fresh original eight-article ship/cat replay | Baseline accepts a correct separation. Candidate proposes correct ship/cat grouping, but rejects the whole batch for uncertain Yemen event reuse | Candidate full output is unavailable; no successful complete regression claim |
| Cat follow-up | Baseline keeps the cat story separate; candidate is unprocessed after rejection | Baseline author saw the cat prior, not the ship priors; journal separation is not another supplied-context discrimination result |
| Fresh C02/C03 | Both arms: 4 positive and 9 negative story pairs agree; 4 explicit negative event pairs agree | No observed pair regression in available cases; no overall accuracy percentage |
| Old four headline gaps | Candidate cites Jupp appointment, Pentagon stopping tools, murder admission and Boots identity/£7bn price/Canadian buyer | Restores headline-dependent core information in all four cases. Baseline already reported a sale announcement; the Boots gain is its supported details, not a newly discovered sale |
| Fresh three headline briefs | Candidate retains bus-cap amount/scope/timing, water-test charges, attributed OpenAI claim | Richer evidence, with the substantive identity overreach below |

The candidate water-test summary calls Matthew Wright the former Southern Water
boss. The title only says a former boss is among four defendants; the description
names Wright and three others. The supplied evidence does not establish that
apposition. It remains an accepted, unsupported identification, even though the
grouping reviewer returned supported. No output or entity-specific rule fixes it.
Claim grounding needs a future general mechanism and independent source cases.

The Yemen rejection is an output-aware diagnostic, not new blind gold. The
proposal certainly reuses a specific operation-announcement event while the old
Guardian input contains only a broad coalition/Houthi headline and a photo
credit. The reviewer judged that connection uncertain. Independent inspection
found this defensible rather than a demonstrated false rejection. Regardless,
all eight inputs remain unaccepted: whole-batch rejection has a real availability
cost. The corrected RSS descriptions were tested separately; no claim is made
that the full live campaign reprocessed all three days through the corrected parser.

## Separate 19-day follow-up

The main C01 preparation failed the existing reference validator and remains a
failure. `followup/plan.json` then froze a conditional five-call experiment before
any current C01 output existed: copy the exact first accepted prior row; run the
identical second prior snapshot through the unchanged candidate; only on success,
copy that accepted common history to both current arms. The candidate preparation
passed without manual edits. This does not causally prove that the new code fixed
the stochastic baseline preparation error.

Both current arms received identical two-current/four-prior payloads and followed
the Musk/OpenAI case from April 29 to May 18, with April 27 origin and a competing
Tumbler Ridge matter present. Both preserve the timeliness ground, advisory jury
and judge's adoption of its view. Each has five correct positive and four correct
negative story pairs plus one same-event pair. No scored merge or missed link
appeared in this conditional case. Ambiguous prior event granularity remains
unscored. The result supports one long-gap example, not months-long operational
capacity, a fresh independent replication, or superiority to baseline here.

## Cost, failures and limits

| Scope | CLI calls | Input tokens | Output tokens | Summed CLI seconds |
| --- | ---: | ---: | ---: | ---: |
| Main baseline current cases | 5 | 79,259 | 4,291 | 112.506 |
| Main candidate current cases, including rejected ship batch | 8 | 111,177 | 5,530 | 163.290 |
| Main common preparation, including one failure | 3 | 32,565 | 1,716 | 50.198 |
| Exact-decision review controls | 3 | 40,504 | 1,062 | 37.088 |
| Separate follow-up, including preparation and both arms | 5 | 68,873 | 2,178 | 66.305 |
| Total | 24 | 332,378 | 14,777 | 429.387 |

All calls report usage; none have unknown launch status. Input includes cached
input (20,608 total); output includes reported reasoning output. Coding and
review-agent account usage is separate. CLI calls are not backend reconnects.
These are different completed workloads with cache differences; summed times are
neither campaign elapsed time nor a controlled speed comparison.

The guard performs at most one additional call per batch, sharing the original
deadline. Daily defaults allow 12 batches/24 calls, 360 seconds per proposal/review
pair. Known and unknown usage are counted per call. Failed or uncertain reviews
stop the FIFO. Full prior-history review can exceed its context cap even for one
article; there is no silent truncation or human override. A same-model reviewer
is separate execution, not statistically independent proof of correctness.

The check covers proposed/touched stories, not every old stored story. It detects
and contains inherited contamination when reused; it cannot split or repair the
old accepted journal. Original sources, decisions and failed attempts remain.
All 844 frozen production files have unchanged SHA-256 values after both phases.

## Evidence

The experiment worktree retains `.news/source-integrity/` with every actual
request, output, failure, usage receipt and immutable source pack. The published
experiment package includes an audit archive and file hashes; raw datasets and
research runners do not enter `from-scratch/main`. Research scripts retain local
paths and authenticated CLI prerequisites; this is preserved evidence, not a
separate installed application. See `metrics.json`, `followup/metrics.json`,
`rss/frozen-replay.json`, and the independent reviews for detailed provenance.

The original parser audit reads its control code from the then-current primary
checkout. That checkout has since been promoted. A future parser comparison must
use `news/feeds.py` from control commit `a5fef50`, not the now-promoted primary
file. The original harness, its exact hashes and its recorded outputs are retained;
running it against changed control code would not reproduce the frozen comparison.

The installed no-mistakes v1.46.0 always selects the origin default branch via
`ls-remote --symref ... HEAD`; that is legacy `main`, not `from-scratch/main`.
Its pipeline was not started against that incorrect base. Delivery instead uses
the independent code/evidence review, offline checks, explicit branch push and
GitHub CI on the exact promoted head. No old branch is merged or rewritten.
