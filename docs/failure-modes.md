# Failure Modes

This document lists known failure modes in the pipeline, their detection methods, current mitigations, and planned improvements.

For the end-to-end flow where these failures can enter, read [how-it-works.md](how-it-works.md).

---

## 1. Source publishes a correction after ingestion

**Description:** A source updates or retracts a claim after the article has been classified and cached. A later ingestion may capture changed content, but the system does not understand that the change is a correction.

**Detection:** Manual review; no automated correction tracking.

**Mitigation:** Classification and claim extraction caches use content hashes. Changed captured content creates another append-only occurrence; classification and claim extraction are rerun for the new input.

**Current status:** Partially mitigated. Captured versions are retained, but no field identifies a correction, retraction, or superseding claim.

**Future improvement:** Add a `retracted_at` field to `claims` and retain claim history across article corrections.

---

## 2. Multiple publications syndicate the same wire copy

**Description:** Reuters, AP, or AFP wire stories are republished verbatim by many outlets. The deduplication step uses normalized URL, not content hash, so syndicated copies appear as separate articles from different sources.

**Detection:** Same headline appearing across 5+ sources with high cosine similarity.

**Mitigation:** Deduplication operates at the URL level, which catches exact duplicates. The consolidation LLM prompt merges story labels that refer to the same event, reducing double-counting in story grouping.

**Current status:** Partially mitigated. Source count can be inflated by syndication.

**Future improvement:** Add content-hash deduplication across articles. Mark primary vs syndicated copies. Weight source count by unique editorial voice, not publication count.

---

## 3. Headline exaggerates or misrepresents the article body

**Description:** The classifier and claim extractor see the title and description, which may contain clickbait framing not reflected in the full article.

**Detection:** Comparison of RSS description sentiment vs full-text sentiment (requires full-text fetching).

**Mitigation:** The classifier still uses title and description, but evidence runs extract claims from fetched body text when available and preserve the RSS fallback.

**Current status:** Partially mitigated for claim extraction, not for classification.

**Future improvement:** With `--fetch-article-text`, compare the extracted claims from the headline vs. the body. Flag divergence.

---

## 4. RSS summary differs from the full article

**Description:** RSS feeds often contain a teaser (50–150 words) that omits key context, qualifications, or corrections present in the full article.

**Detection:** Structural: if `text` field is empty, the article was not fully fetched.

**Mitigation:** `--show-evidence` fetches the full article page for claim extraction, and `--fetch-article-text` can fetch body text even when evidence extraction is disabled. Body text fetching is still gated because of cost and rate-limiting risk.

**Current status:** Mitigated for evidence runs when body extraction succeeds. Claims fall back to RSS title/description when article text is empty or unavailable.

**Future improvement:** Measure how much full-text evidence improves claim quality against the added fetch latency, token use, and failure rate.

---

## 5. LLM merges unrelated stories

**Description:** The consolidation or matching LLM merges two distinct stories that share keywords, actors, geography, or broad context (e.g. "Iran nuclear deal" and "Iran ceasefire talks" treated as one story).

**Detection:** Manual review of canonical labels. Eval: story clustering pairwise F1 against a golden set. Inspect `story_match_decisions` for rejected/accepted candidate matches when a candidate crossed the verifier gate.

**Mitigation:** `CONSOLIDATE_PROMPT` is explicit about only merging "clearly the same event." `MATCH_PROMPT` says broad topic similarity is not enough. The tracker also applies a deterministic guard for generic incident/category labels: labels such as accidents, crashes, shootings, and lawsuits may not merge unless they share a distinctive token beyond the generic category. Candidate cross-day matches are checked by default using full article text and `gpt-5.4-nano`; weak, uncertain, adjacent-topic, or malformed verifier decisions default to a new story. Use `--no-verify-story-matches` only for comparison runs.

**Current status:** Partially mitigated by prompt design, deterministic false-merge guards, and default-on story-match verification. Exact verifier model responses can be cached for identical prompts, but there is no semantic decision cache.

**Future improvement:** Add a story clustering eval dataset and a `story_match_cases.jsonl` fixture set. Track false-merge and false-split rates over time before making the verifier more permissive.

**Motivating example:** Run #2 on 2026-05-07 attached Al Jazeera's `Palestinians expose torture and sexual violence in Israeli detention` to `Gaza flotilla raid`. The correct behavior is to reject that as an adjacent topic and keep it as a separate story.

---

## 6. LLM treats allegation as confirmed fact

**Description:** The briefing LLM may present an unverified claim as a confirmed fact, especially when sources agree on the claim without independently verifying it.

**Detection:** Claim type tagging (`allegation` vs `fact`). Source agreement check.

**Mitigation:** `CLAIMS_PROMPT` distinguishes `allegation` from `fact` in `claim_type`. `BRIEFING_PROMPT` requires neutral prose and tells the model to surface allegations, uncertainty, and divergent claims instead of smoothing them away.

**Current status:** Partially mitigated by claim typing. Not yet surfaced in briefings.

**Future improvement:** Surface `allegation`-typed claims differently in the briefing output. Add a warning when briefing confidence exceeds what claims support.

---

## 7. Source has political, commercial, or institutional bias

**Description:** A source systematically frames stories in a particular direction. If that source dominates coverage of a story, the briefing will reflect its framing.

**Detection:** Track source distribution per story. Flag stories dominated by a single source or source type.

**Mitigation:** `BRIEFING_PROMPT` asks the model to surface disagreement, allegations, uncertainty, and divergent numbers/status claims. The `sources` table stores reliability and bias notes per feed; new article rows record `source_id` when a seeded source matches.

**Current status:** Partially mitigated by prompt design and seeded source metadata. No automated bias flagging or source-distribution warnings yet.

**Future improvement:** Use the seeded reliability and bias metadata to surface source-distribution warnings in briefings, and to weight source agreement.

---

## 8. Article timestamp differs from actual event date

**Description:** An article published today may report an event from yesterday, last week, or months ago. The system treats the publication date as the event date.

**Detection:** Cross-check `published_at` against event references in article text.

**Mitigation:** None currently. The briefing prompt is instructed to use reported timestamps to clarify chronology.

**Current status:** Unmitigated structurally.

**Future improvement:** Extract event dates from article text as a separate field. Distinguish "reported at" from "occurred at."

---

## 9. Paywalled article provides incomplete content

**Description:** Some RSS feeds return a full description; others return a paywall stub. The classifier still sees the RSS title and description. Evidence runs fetch article bodies for claim extraction, but paywalls and extraction failures can still leave the claim extractor with incomplete content.

**Detection:** Description length < 100 characters, or contains "subscribe" / "login" in the stub.

**Mitigation:** `--show-evidence` now fetches full article text for claims and falls back to title plus RSS description when body text is unavailable. Short or blocked article bodies still produce fewer extracted claims.

**Current status:** Partially mitigated for evidence runs; still not modeled as a source-quality signal.

**Future improvement:** Detect paywall stubs and mark articles accordingly. Skip claim extraction for stubs. Weight paywalled sources lower in source agreement.

---

## 10. Comparable claims diverge across sources

**Description:** Sources may report different numbers, dates, statuses, or attributions for an otherwise comparable development. The briefing may otherwise collapse those differences into one account.

**Detection:** Deterministic comparison of current, non-background claims across distinct source identities. Matching remains deliberately narrow.

**Mitigation:** Evidence-mode source agreement records narrow divergence notes for comparable numbers, dates, statuses, and attributions. Any such note forces `source_agreement = mixed` and `dispute_flag = possible conflict`. The briefing layer still does not accept `confirmed conflict`.

**Current status:** A conservative first pass is implemented in evidence mode. It has not yet been reviewed against enough real cases to justify broader matching.

**Future improvement:** Review real divergence cases, measure false matches, and tighten patterns before considering any broader comparison. Keep surfaced differences as source-divergence notes, not confirmed contradiction prose.

---

## 11. Model invents causal relationships

**Description:** The briefing LLM may connect two developments with causal language ("which led to", "as a result") that is not present in the source articles.

**Detection:** Compare causal phrases in briefing against causal language in source descriptions. No automated check currently.

**Mitigation:** `BRIEFING_PROMPT` tells the model to base current developments on today's article titles, descriptions, reported timestamps, and supplied structured claims. Claim extraction separates source-supported claims from prose synthesis.

**Current status:** Partially mitigated by prompt design. No automated detection.

**Future improvement:** Citation coverage check: for each causal claim in the briefing, verify it appears in at least one source span.

---

## 12. Model overstates certainty

**Description:** LLM uses confident language ("X has occurred") when sources use hedged language ("officials said X may occur").

**Detection:** Compare hedge words in sources vs. hedge words in briefing.

**Mitigation:** `BRIEFING_PROMPT` requires neutral prose, bounded confidence labels, and explicit surfacing of allegations, uncertainty, and divergent claims. Claim types (`prediction`, `allegation`) capture hedging in structured form.

**Current status:** Partially mitigated by prompt design.

**Future improvement:** Add a post-generation certainty check. Flag briefing sections where confidence exceeds claim support.

---

## 13. Model misses important minority-source reporting

**Description:** One credible source reports a significant development, but the briefing model focuses on the consensus across many sources and underweights the outlier.

**Detection:** Check whether low-source-count stories with high importance appear in the briefing.

**Mitigation:** Importance score is factored into story selection. Single-source stories can appear in the briefing if importance is high enough.

**Current status:** Partially mitigated by scoring. Minority reporting within a story is harder to surface.

**Future improvement:** For each story, surface the highest-credibility outlier claim explicitly as a "Notable minority report."

---

## 14. Old background information is mistaken for new development

**Description:** The LLM may present historical context from `previous_context` as if it is new reporting.

**Detection:** Compare delta_summary against previous_context to check for repetition.

**Mitigation:** The briefing prompt treats previous context and up to seven days of older claims as historical context only. Source-agreement conclusions use current-day claims, and rendered evidence labels older claims as historical.

**Current status:** Partially mitigated by prompt design, explicit evidence roles, and a separate `delta_summary`. Generated prose still lacks a general temporal-entailment checker.

**Future improvement:** Add a temporal grounding check: flag when briefing text uses language from previous_context without a temporal qualifier.

---

## 15. Duplicate detection collapses distinct but similar stories

**Description:** The story consolidation step may merge two related but distinct events (e.g. two different diplomatic meetings on the same topic) into a single canonical story.

**Detection:** Eval: compare auto-merged stories against a golden set of known-distinct stories.

**Mitigation:** `CONSOLIDATE_PROMPT` is explicit: "Labels that stand alone still appear as a group of one." The system errs on the side of splitting within a day.

**Current status:** Partially mitigated. The 14-day lookback for cross-day matching may over-merge long-running topics.

**Future improvement:** Add a story splitting mechanism for cases where a canonical story diverges into distinct threads. Reduce lookback for stories that have been quiet for >7 days.
