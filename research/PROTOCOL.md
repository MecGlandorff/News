# News2.0 pre-candidate research protocol v0.2

Status: **PROPOSED; no measured quality claim or authorization for application calls.**
Revision: **2026-11-01**. This direction revision supersedes v0.1's two-candidate
restriction, future research-agent model requirement and three-arm calibration
proposal. The [direction record](DIRECTION.md) captures the accepted product
decisions and finite next offline step. Frozen source inventories, labels, exposure
records and historical review/model attribution remain unchanged. The inherited
screening floors below remain proposals, not validated reliability thresholds.
Bootstrap `2033740` is in local ancestry; that does not establish integration of
PR #58 into `News2.0`. Verify this dependency and the exact target before merging.
This revision makes zero application model calls and changes no operational
system or schedule.

## 1. Question and scope

Can a small system provide useful daily developments in the most important new
and ongoing stories while preserving evidence, uncertainty and continuity?
Develop these distinct architecture variants in parallel under one contract;
their selection is a research plan, not an architecture verdict:

| Arm | Required behavior |
| --- | --- |
| D: direct | Reconstruct the current story view directly from the visible sources. |
| E: extract | Extract source-local contributions, then reconstruct from those contributions and their evidence. |
| I: incremental | Use the same source-local extraction as E; update prior interpretations and automatically detect/repair affected state. |
| R: retrieve | Use the same source-local extraction as E; retrieve bounded evidence from a source-only index and reconstruct the affected views. |
| B: baseline | Frozen old rebuild at `bc7b0fb93d3ca34fdb9400d91deb4a627cf96fe9`. |

E is the comparison hub: D/E tests extraction, E/I tests dependence on prior
interpretations, and E/R tests retrieval limits. Do not combine I and R in this
batch. Each arm must prevent, detect and repair interpretation errors; rebuilding
from evidence is itself a possible repair mechanism. No multi-agent application
architecture or extra analysis/judge call is required by the contract.
D/E/R reconstruction cannot consume prior story interpretations. A common declared
delta-comparison interface may read the previous published view after reconstruction;
keep that access separate so the contrast with I's state dependence is meaningful.
R indexes the same complete visible corpus, using a frozen source-only query/index
design; it cannot query previous story summaries or curated case IDs. Cached
extraction and indexes must preserve each prefix boundary: no future documents,
later versions, or future-derived index statistics may influence earlier views.
Retrieval omission does not expire a story. Missing mixed-stream/full-slice corpus
coverage blocks a live retrieval comparison, not offline interface development.

The accepted per-story web-search direction, including counterevidence and missed
developments, is a separate bounded source-enrichment experiment in
[SEARCH.md](SEARCH.md). Compare the same candidate without/with recorded evidence;
do not give one architecture extra information or treat current web results as
historically available. This offline batch records fixtures only; live search needs
its own complete frozen manifest and budget, separate from the five-arm screen.

All arms receive identical immutable source versions, visible prefixes and order.
Match actual text, truncation and cutoffs, including baseline adapter inputs.
Before live fixed-evidence calls, verify hosted web search is effectively disabled
for every stage/child agent; shell-network restrictions or prompt instructions
alone do not enforce the evidence boundary. See [SEARCH.md](SEARCH.md).
Use `gpt-6-astra`, medium reasoning, for every architecture application call,
including shared extraction, optional analysis and internal validation stages
(including the frozen baseline's). External semantic judges are evaluation agents:
use `gpt-6-astra` / xhigh and account for them separately. Freeze prompts, decoding
settings and any seeds the API supports for both roles.
Match available evidence and per-arm resource ceilings; count every stage's cost.
Different call counts are an architectural cost, not a reason to hide extraction.
Report each arm's standalone cost, charging extraction to every arm that needs it,
and the actual experiment cost if an identical frozen extraction is shared.
Count all stages, including optional analysis, judges, failed calls and repair;
research-agent review remains separately attributed and accounted.
If B cannot consume the selected evidence without changes, freeze and disclose a
minimal input adapter separately; unsupported capabilities count as failures.
Do not quietly improve B, import its code into candidates or treat B as truth.
All future research, implementation, labeling, evaluation and review agents use
`gpt-6-astra` with xhigh reasoning. Preserve historical Sol attribution.
Research-agent work is separate from application model choice and calls.

## 2. Reader and representation contract

At each observation boundary a reader can identify the matter, what was previously
supported, today's material additions, exact supporting evidence and uncertainty.
A daily delta distinguishes a new occurrence from a material new fact about the
same occurrence. A new publication, rewritten summary or processing repair alone
does not constitute fresh news. Quiet days may correctly have no delta.
Prioritize meaningful developments in important new and ongoing stories. Extended
analysis appears under a separate heading and is read-only with respect to factual
state, accepted relationships and delta membership; analysis alone creates no news.
Assess importance/relevance as a reader preference within the frozen observed
source window. Source counts or model rankings do not establish objective world
importance; disclose missing coverage. Evaluate both canonical facts/deltas and
the rendered briefing, including whether analysis implies unsupported facts.
Assess the first 30–90 days once suitable observed coverage exists. This is no
fixed expiry for stories, evidence, unresolved questions or late relationships.

Before model experiments, demonstrate expressibility with hand-authored fixtures:

- A source version has **0..many contributions**; thin text may remain unassigned.
  Context, an unresolved relation or a question need not invent an occurrence.
- Occurrences and ongoing stories have separate identities. Shared entities or a
  topic alone do not justify merging matters; one source can concern several.
  Merge when evidence supports it; display uncertain links as possible
  relationships, keeping them distinct from accepted story membership.
- Contributions retain attribution, source version and exact evidence spans.
  Publication, occurrence, observed capture and processing times remain distinct.
- Material new facts can update an existing occurrence without fabricating another.
  Source corrections supersede claims with provenance; interpretation repairs
  revise system judgments and do not masquerade as source corrections or news.
- Questions can open, remain unresolved, be answered, or close with a stated reason.
  Silence and elapsed time do not establish resolution. Conflicts remain attributed
  until evidence resolves them; majority source count is not a truth rule.
- Long gaps preserve identities and unresolved questions without implying continuous
  coverage. Late evidence can reconnect a matter without rewriting earlier views.
- Immutable sources and historical views survive revisions. Automatic recovery from
  a contaminated assignment produces an auditable replacement and affected deltas.

Failing expressibility stops the model comparison. This contract specifies outcomes,
not a database schema, event taxonomy, pipeline or required number of model stages.

## 3. Casebook, chronology and exposure

Build roughly 12–16 public-source development cases with inventory and manifests.
Record source URL/title, publisher, publication/updated times if known, capture
evidence, local version/hash, excerpt/full-text status, gaps, rights/publication
scope, exposure history and trajectory membership. Absence of text is not absence
of a real-world development. Preserve competing and unassigned source material.
The casebook is a development resource and cannot authorize quality promotion.
The 12 grouped packets are source-labeling aids, not inputs for unassisted story
discovery or retrieval: case IDs, membership and rationales pre-cluster relevance.
The 49 selected observations are curated, incomplete-day diagnostics, not evidence
of full-archive retrieval or coverage. A candidate harness must hide those grouping
cues and use mixed chronological streams with predeclared background sources.
Before broad quality claims, freeze and replay full archive slices, retaining all
sources and failures, separately by chronology mode. This full-slice gate is unmet;
selected-case calibration establishes feasibility only.
Source-version differences may reflect acquisition or extraction changes, not a
publisher correction. Require claim-level evidence before assigning semantic change.

Keep these chronology modes separate in every result and denominator:

| Mode | What the order establishes |
| --- | --- |
| Actual observed | Verifiable capture timestamps establish when this system had each version. |
| Editorial reconstruction | Declared historical ordering; available-at time is not established. |
| Synthetic stress | Deliberate gap, reorder, contradiction or contamination manipulation. |

Packet aliases `captured_observation` and `publication_order_simulation` mean actual
observed and editorial reconstruction respectively; preserve the mode in exports.
Existing archives have already been exposed and are development material, never
holdout. Their 34 daily files do not prove 34 actual available-at days because of
backfill; the frozen development subset uses the original six capture dates.
At the original inventory audit, October 23 polls 7/8 were excluded and reserved
for a future exposure/provenance audit, not holdout. All later polls also remain
outside the frozen casebook unless explicitly selected in a new version. A larger
archive count alone establishes neither coverage nor evaluation sufficiency.
Inventory must substantiate chronology claims.
Do not relabel publication dates as capture dates.
Do not pool modes to claim online performance or 30/60/90-day reliability. Historical
long-gap cases establish only behavior under their documented evidence and gaps.

Include thin/empty text, no-delta prefixes, same-occurrence additions, multi-matter
documents, unrelated similar entities, corrections, question closure, unresolved
conflicts, long gaps, delayed evidence and contamination/recovery. Record missing
categories openly; do not silently narrow the intended contract to available cases.

## 4. Prefix-only source labels

Label before generating candidate outputs. Two independent source-only labelers
receive sequential prefixes: save and freeze each prefix before exposing the next.
Future-source blindness and candidate-output blindness are separate requirements;
record violations of either, including prior familiarity. Do not open the complete
casebook in advance. A separate adjudicator reconciles each prefix before seeing
later sources, without candidate outputs or arm identities. Retain
both original labels, adjudication rationale and unresolved ambiguity. Later
prefixes may add expectations but may not leak facts into an earlier label.
Use provisional source-based occurrence/story references, never candidate IDs.
Future visibility includes related cases, not merely later prefixes within a bundle.
Before scheduling labels, freeze an exposure graph and audit related-case clusters.
Within each appropriate clock stratum, label in global chronological order; curated
diagnostics may instead use fresh isolated case contexts, with cross-case links
adjudicated separately before mixed-stream scoring. Retained labels exposed to
related future evidence are ineligible; replacement requires fresh labelers and
separate adjudication. The current reference does not establish global clock blindness.

Keep shared provenance, chronology, exposure, source sufficiency and source lists
in the versioned inventory/prefix manifest rather than copying them into every label.
Each prefix label contains these fields (empty arrays/null are explicit):

```text
case_id, prefix_id, labeler_id, label_version, inventory_version,
contributions[] {
  id, kind, claim, source_spans, attribution, occurrence_ref|null,
  story_ref|null, materiality, uncertainty
},
relations[] {from, to, type, status, reason, source_spans},
delta_expectations[] {contribution_ids, status, reason},
questions[] {id, status, claim, source_spans, closure_reason|null},
no_delta_reason|null, missing_evidence_reason|null, ambiguity_notes[],
adjudication_status
```

`kind`: new_occurrence, same_occurrence_material_fact, source_correction,
question_opened, question_answered, question_closed, conflict, context_only.
Relation/delta `status`: required, allowed, prohibited, uncertain. Relations identify
same/different occurrence or story, or a correction/conflict link. Source spans
use `{observation_id,field:'text'|'title'|'description',start,end}`, with Unicode
codepoint offsets `[start,end)` in preserved raw fields (including raw HTML).
Questions use open/answered/closed; labeler records start as `unadjudicated`.
Inventory sufficiency is sufficient/partial/insufficient/missing. Exposure records
who saw which sources/labels/outputs and when; unknown exposure stays unknown.
Required units enter recall denominators; allowed alternatives receive no penalty;
uncertain units are excluded from correctness rates and counted separately.
Source-only labels cannot certify interpretation repair without a prior system state.
After source labels freeze, separately freeze recovery fixtures with fixture_id,
prefix_id, seeded_state, seeded_defects, expected_repairs and source-label references.
Fixtures derive repairs from the source contract; they add no source truth.

Development labels can change only through versioned amendments with reason,
author, prior value and affected units. Freeze amendments before output inspection
where possible. Any later amendment invalidates affected output scoring; retain old
scores, mark them invalid and rescore every affected arm under a new version.
An output-inspired amendment remains disclosed development evidence, not holdout.

## 5. Freeze and replay

Freeze a run manifest containing source hashes, label/adjudication versions, this
protocol, chronology/exposure, complete prefix order, arm code/prompt versions,
baseline/adapter commit, model/settings, output schema, budget and scoring rules.
Assign run IDs and retain raw requests/responses, errors and score amendments.
Any change creates a new version/run; do not overwrite a failed comparison.
No future source or derived state crosses the prefix boundary. Randomize arm
execution order and blind output scoring to arm identity where feasible.

Replay whole trajectories, including no-delta boundaries and pending work. Score
both the current supported view and the delta from the previous prefix. Score
daily views separately: freeze UTC calendar-day boundaries and end-of-day cutoffs;
aggregate ordered within-day contributions once, retaining corrections/conflicts.
Source-change checkpoints (the initial packet has 37) are not 37 daily observations.
Add explicit daily cutoffs and quiet-day labels before measuring daily usefulness;
missing quiet days are unmeasured, and uncaptured days are coverage gaps, not quiet.
Compare clean reconstruction against declared contaminated history: planted wrong
membership, stale correction and omitted contribution. Use the same visible source
prefix, log the contamination, and require automatic repair without manual IDs or
patched outputs. Verify all affected views, links, deltas and source accounting,
not merely removal of the planted item. Reference is fresh prefix reconstruction.
Freeze detection/repair policy before the run; the tested policy receives no seeded
defect IDs, locations or expected repairs. Those belong only to the fixture/scorer.
Affected contaminated views stay visibly pending until repaired before the next
affected daily view activates and within 24 hours of declared replay time; record
repair latency in replay and processing wall time. Passing a cutoff unrepaired fails.

## 6. Units and reporting

The primary independent unit is a source-supported trajectory, not all possible
article pairs. Report raw numerators/denominators plus micro pooled unit rates and
macro means across eligible trajectories, with each trajectory's result visible.
Twelve case bundles are not twelve independent trajectories (nor eleven after
subtracting one overlap): a bundle may contain multiple matters, and one matter
may span bundles. A reviewed semantic/statistical dependency-cluster map is required
before minimum-trajectory gates or clustered intervals; use its independent units,
not packet counts. Unknown background dependence stays explicit. Current research has
no claimed complete cluster map; the corresponding gates remain unestablished.
Do not inflate sample size by counting repeated prefixes or n-squared negative
pairs as independent observations. Cluster uncertainty by trajectory; report a
paired trajectory bootstrap 95% interval only with at least 10 eligible trajectories
(10,000 resamples, fixed recorded seed). Below that, report range and **insufficient
evidence for uncertainty estimation**. Intervals are descriptive development data.

| Metric | Unit and denominator |
| --- | --- |
| Supported precision | Supported emitted atomic factual claims / all emitted factual claims. |
| Delta novelty precision | Supported material new delta items / all emitted delta items; rewording and repair-only news fail. |
| Development recall | Required material developments emitted / required material developments in sufficient visible text. |
| Connection recall | Correct required occurrence/story links / adjudicated required links. |
| False merges | Incorrect accepted links / all accepted links; also violated predeclared distinct relations / eligible distinct relations, plus contaminated stories and trajectories. |
| Usable coverage | Nonempty useful, supported daily results / eligible actionable day windows; silent/rejected/pending outputs fail. |
| No-delta accuracy | Correct quiet daily results / adjudicated no-delta day windows; abstention on actionable days is separate. |
| Special handling | Correct correction, interpretation-repair, question, conflict and long-gap units / required units of each kind. |
| Recovery success | Fully repaired planted defects with provenance and no collateral loss / planted defects; report by trajectory. |

Labels enumerate eligible relations before outputs; also count every emitted false
merge, including relations outside that list. Report ambiguous units, insufficient
text, uncaptured sources, extraction omission, retrieval miss, link error, briefing
omission and unscorable output separately. Never credit an unsupported invention
because labels are incomplete. Abstention, failure and pending are not true negatives.
Every emitted false merge enters accepted-link error and affected-story/trajectory
counts and the gate, even outside predeclared relations. A useful daily result must
identify the matter, previous support, material addition, evidence and uncertainty;
independent output reviewers record which required reader element is missing.
Model-authored labels and semantic reviews are fallible, potentially correlated
interpretations. Keep deterministic integrity checks separate from source-grounded
semantic judgments and human source/product review. Review emitted claims and
sample un-emitted sources for missed developments; retain disagreement and
unscorable results, and report how disputed interpretations could change a
comparison. Another model or model
majority does not replace human review or establish truth. Optional later human
sampling does not gate ordinary offline harness, fixture or audit work.
Calibrate semantic judges with independently checked wrong-entity, number,
attribution, future-evidence, uncertainty, novelty, omission and causal-inference
probes plus valid paraphrases. Check sensitivity to arm labels, order and verbosity
under the scoring procedure. LLM-authored probes alone are not independently
verified truth; disclose how expected judgments were checked. Audit unanimous
passes too: disagreement rate alone cannot reveal shared mistakes. Human samples
can assess source-only importance/sufficiency before output exposure, then blinded
output usefulness across arms and omissions; their size remains to be frozen.
Report end-to-end prefixes completed, failed/rejected/pending counts, oldest pending
age in observed time and processing time, schema failures and recovery attempts.
Record per call/stage/arm and aggregate: input/output/cached/reasoning tokens where
available, model-active time, wall time, call count, retries, errors, timeouts and
monetary cost if known. Unavailable fields are `unknown`, never zero. Separately
report research-agent model/settings, active preparation/review time and available
usage; unavailable agent token/cost telemetry prevents a claim of total token/cost
measurement even when application accounting is complete.
Special categories are source corrections, seeded interpretation repairs, question
opening/answering/closure separately, conflict preservation and long-gap continuity.

## 7. PROPOSED screening floors — not empirical reliability claims

These finite development thresholds are policy proposals, frozen before scoring.
Every applicable absolute floor and paired condition must pass; better than B alone
is insufficient. The cost-calibration slice below cannot satisfy these denominators.

| Metric | Minimum eligible denominator | Absolute floor/ceiling |
| --- | --- | --- |
| Supported precision | 60 emitted claims across ≥10 trajectories | ≥95% micro and ≥90% macro; zero invented high-impact facts. |
| Delta novelty precision | 30 emitted delta items across ≥10 trajectories | ≥90% micro and ≥85% macro. |
| Development / connection recall | 30 required units each across ≥10 trajectories | ≥85% micro and ≥80% macro each. |
| False merges | 30 accepted links and 30 predeclared distinct relations, each across ≥10 trajectories | Each error rate ≤5% micro and ≤10% macro; zero cross-matter merger persisting to final prefix. |
| Usable coverage | 20 actionable day windows across ≥10 trajectories | ≥85% micro and ≥80% macro. |
| No-delta accuracy | 10 quiet day windows across ≥5 trajectories | ≥90% micro and ≥80% macro. |
| Each special-handling category | 5 required units across ≥3 trajectories per category | ≥80% micro and macro; no unsupported question closure. |
| Recovery | 6 planted defects across ≥3 trajectories | 100% repaired before next affected daily view activates, within one daily cutoff; zero collateral required-unit loss. |
| Completion | All scheduled prefixes, ≥10 trajectories | ≥95% completed; zero hidden/discarded failures or silently stale active views. |

Empty denominators are undefined. Below a minimum is **insufficient evidence**,
never a pass, and must not be fixed by discarding a difficult category. Reject-all
fails recall and coverage and lacks precision evidence; report refusal rate explicitly.
High-impact means identity, death/injury, legal status or similarly consequential
claims identified in labels; adjudicate ambiguity before candidate scoring.

For each candidate versus B, require paired macro supported precision and novelty
no worse than B by >2 percentage points, recall/coverage no worse by >5 points,
and false merges no worse by >2 points. Also require ≥5-point improvement in at
least one of development recall, connection recall, usable coverage or false-merge
reduction, without a new critical failure. Use identical eligible paired trajectories;
freeze label-eligible sets before outputs and require ≥10 paired trajectories. Failed,
abstaining and unscorable outcomes stay in the set and recall/coverage denominators;
never select favorable complete pairs or impute perfect precision to empty outputs.
Undefined precision/link rates cannot pass a paired gate. If B's rate is undefined,
superiority on that metric is unestablished, even if a candidate passes absolute floors.
Report paired differences and clustered intervals, including intervals spanning zero;
do not call an uncertain improvement established superiority. Compare D/E, E/I and
E/R on the same metrics and standalone cost; select no winner from this plan alone.
If no candidate meets every applicable gate, promote none. Ties or
uncertain tradeoffs favor no promotion, not selective metric weighting after results.

## 8. Offline prerequisites, bounded calibration and later gates

The next batch is the finite offline harness, fixture and audit work in
[DIRECTION.md](DIRECTION.md), with zero application model calls. The v0.1 budget
for D/E/B is superseded; do not silently multiply it for the expanded roster.
After offline prerequisites and candidate adapters exist, freeze one small
feasibility screen for D/E/I/R/B before proposing larger parallel comparisons.
Its actual selected inputs, prompts, versions and numeric budget must be known
before any application calls. An unfilled plan is not a runnable experiment.

Proposed ceiling for that first screen: two mixed development streams with two
cutoffs each, all five arms once, yielding 20 scheduled views. Select and freeze
the streams/cutoffs after the corpus audit. This tests feasibility, not complete-day
usefulness, long-run quality or the Section 7 denominator gates. The ceilings below
include failed attempts and any explicitly reserved recovery; they are not grants
to consume unused calls or substitutes for an actual stage-by-stage schedule.

| Budget | Calls | Input / output tokens | Model-active time |
| --- | --- | --- | --- |
| Each application arm | ≤18, including ≤2 reserved recovery calls | ≤360,000 / 36,000 | ≤45 minutes |
| All five arms, standalone attributed ceiling | ≤90 | ≤1,800,000 / 180,000 | ≤225 minutes |
| External evaluation judges, including calibration/probes and recovery review | ≤40 | ≤800,000 / 80,000 | ≤120 minutes |
| Combined actual calls, including external judges | ≤130 | ≤2,600,000 / 260,000 | ≤345 minutes |

The proposed judge allocation is 15 calibration/perturbation calls (eight failure
types, one valid-paraphrase control and three paired arm-label/order/verbosity
checks), 20 view assessments and five recovery assessments. Exact probe inputs,
independently checked expectations, scoring procedure and scheduled recovery
fixtures still require a freeze. If their actual task cannot fit, report the
limitation rather than granting extra calls or weakening calibration silently.

Cancel each call at 120 seconds; actual remaining stage and total limits still
apply. Charge shared extraction to each relevant arm for standalone feasibility
and count its actual execution once in the combined actual ledger. Default to no
automatic retries; a failed call uses budget, and at most the predeclared reserved
recovery calls may follow. A design that cannot fit must report that result; do not
silently drop stages, evidence or arms. Numeric wall-time and research-agent work
caps, exact judge tasks and enforceable per-call token limits must be filled in
the reviewed manifest before this proposal is runnable.

The live manifest must enumerate scheduled calls and per-stage/per-arm/total
ceilings for input/output tokens, model-active time, wall time and failures,
including preparation, optional analysis, judging, review and repair. Declare
per-call output/time bounds, any permitted recovery calls within those ceilings,
the number of trials, and a finite research-agent time budget. Default to one
trial and zero retries; any additional attempt must already be in the manifest.
Show both standalone per-arm costs and the actual cost of shared extraction.
Freeze execution order, stops, accounting and paired reporting before outputs;
independent review checks the plan's completeness without making the judge truth.

Check remaining tokens/time before each call. Token thresholds are hard ceilings
only when input counting and backend per-call output bounds are enforceable; otherwise
report one-call overshoot risk, actual overshoot and backend usage after cancellation.
Unknown app usage stops further calls for that arm. Research-agent token/cost usage
may be unavailable: mark unknown and enforce time limits; claim no total financial cap.
No automatic retries. A failed call consumes budget and its prefix remains failed
unless a predeclared reserved recovery call is used, with the original failure kept.
Budget exhaustion is an observed arm feasibility failure; unfinished scheduled
prefixes remain failed/pending in completion, coverage and paired reports.
A critical unsupported fact stops that arm as a scored semantic failure; retain
remaining scheduled prefixes as failed/pending and continue unaffected matched arms.
Source/label leakage, changed frozen inputs, broken provenance/accounting, unbounded
execution, manual output patching or contaminated clean inputs invalidate affected
shared results. Preserve artifacts and define a new bounded plan before continuing
affected work. Semantic errors in an output do not invalidate the experiment.
Do not silently narrow source coverage, reorder failures away or reuse stale
outputs to complete a run.

Calibration reports feasibility, cost and failure modes only. Larger replays,
variability repeats and recovery experiments need a new predeclared bounded plan
with exact selected trajectories, calls/tokens/time and stopping rules; no implied
authorization follows from this protocol. Independent review must assess labels,
correctness, usefulness, simplicity, failures and accounting before any advance.
Development success permits a proposal for a genuinely unexposed holdout and a
prospective capture gate, whose samples, durations, floors and budgets remain to
be defined and independently reviewed. Neither exists here. Quality promotion,
production use and long-run claims remain blocked pending those gates and evidence.
