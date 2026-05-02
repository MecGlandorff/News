# Failure Modes

This document lists known failure modes in the pipeline, their detection methods, current mitigations, and planned improvements.

---

## 1. Source publishes a correction after ingestion

**Description:** A source updates or retracts a claim after the article has been classified and cached. The system stores the original version and will not re-fetch unless the content hash changes.

**Detection:** Manual review; no automated correction tracking.

**Mitigation:** Classification and claim extraction caches use content hashes. If the article input changes, classification is re-run and stale cached claims are invalidated before claim extraction is retried.

**Current status:** Partially mitigated. The system invalidates stale cached claims, but does not retain explicit correction/retraction history.

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

**Mitigation:** None currently. The classifier uses both title and description.

**Current status:** Unmitigated.

**Future improvement:** With `--fetch-article-text`, compare the extracted claims from the headline vs. the body. Flag divergence.

---

## 4. RSS summary differs from the full article

**Description:** RSS feeds often contain a teaser (50–150 words) that omits key context, qualifications, or corrections present in the full article.

**Detection:** Structural: if `text` field is empty, the article was not fully fetched.

**Mitigation:** `--fetch-article-text` flag fetches the full article page. Off by default due to cost and rate-limiting risk. The fetched body text is not yet used by claim extraction.

**Current status:** Partially mitigated for article capture. Not yet mitigated for claims; evidence spans currently reflect RSS title/description.

**Future improvement:** Use fetched full text selectively for lead-story claim extraction before considering full-text fetching by default.

---

## 5. LLM merges unrelated stories

**Description:** The consolidation or matching LLM merges two distinct stories that share keywords (e.g. "Iran nuclear deal" and "Iran ceasefire talks" treated as one story).

**Detection:** Manual review of canonical labels. Eval: story clustering pairwise F1 against a golden set.

**Mitigation:** `CONSOLIDATE_PROMPT` is explicit about only merging "clearly the same event." `MATCH_PROMPT` says "Different stories (even similar topics) should not match."

**Current status:** Partially mitigated by prompt design. No automated eval.

**Future improvement:** Add a story clustering eval dataset. Track false-merge rate over time.

---

## 6. LLM treats allegation as confirmed fact

**Description:** The briefing LLM may present an unverified claim as a confirmed fact, especially when sources agree on the claim without independently verifying it.

**Detection:** Claim type tagging (`allegation` vs `fact`). Source agreement check.

**Mitigation:** `CLAIMS_PROMPT` distinguishes `allegation` from `fact` in claim_type. Briefing prompt instructs neutral tone.

**Current status:** Partially mitigated by claim typing. Not yet surfaced in briefings.

**Future improvement:** Surface `allegation`-typed claims differently in the briefing output. Add a warning when briefing confidence exceeds what claims support.

---

## 7. Source has political, commercial, or institutional bias

**Description:** A source systematically frames stories in a particular direction. If that source dominates coverage of a story, the briefing will reflect its framing.

**Detection:** Track source distribution per story. Flag stories dominated by a single source or source type.

**Mitigation:** Briefing prompt asks to "synthesize across all sources provided, surfacing different angles where they exist."

**Current status:** Partially mitigated by prompt design. No automated bias flagging.

**Future improvement:** Add source reliability and bias metadata (`sources` table, Phase 3). Surface source-distribution warnings in briefings.

---

## 8. Article timestamp differs from actual event date

**Description:** An article published today may report an event from yesterday, last week, or months ago. The system treats the publication date as the event date.

**Detection:** Cross-check `published_at` against event references in article text.

**Mitigation:** None currently. The briefing prompt is instructed to use reported timestamps to clarify chronology.

**Current status:** Unmitigated structurally.

**Future improvement:** Extract event dates from article text as a separate field. Distinguish "reported at" from "occurred at."

---

## 9. Paywalled article provides incomplete content

**Description:** Some RSS feeds return a full description; others return a paywall stub. The classifier and claim extractor see incomplete content.

**Detection:** Description length < 100 characters, or contains "subscribe" / "login" in the stub.

**Mitigation:** None currently. Short descriptions produce fewer extracted claims.

**Current status:** Unmitigated.

**Future improvement:** Detect paywall stubs and mark articles accordingly. Skip claim extraction for stubs. Weight paywalled sources lower in source agreement.

---

## 10. Numeric claims conflict across sources

**Description:** Source A reports "20 casualties"; source B reports "34 casualties." The briefing may synthesize a single number or pick one arbitrarily.

**Detection:** Claims with `claim_type = "number"` on the same entity across sources within a story.

**Mitigation:** None currently. Claim extraction captures numbers as typed claims. Contradiction detection is planned (Phase 4).

**Current status:** Claims are extracted and typed but not compared.

**Future improvement:** Compare numeric claims across sources. Surface as `contradiction` with `contradiction_type = "number"`.

---

## 11. Model invents causal relationships

**Description:** The briefing LLM may connect two developments with causal language ("which led to", "as a result") that is not present in the source articles.

**Detection:** Compare causal phrases in briefing against causal language in source descriptions. No automated check currently.

**Mitigation:** Briefing prompt: "Base current developments on today's article titles and descriptions." Claim extraction separates source-supported claims from prose synthesis.

**Current status:** Partially mitigated by prompt design. No automated detection.

**Future improvement:** Citation coverage check: for each causal claim in the briefing, verify it appears in at least one source span.

---

## 12. Model overstates certainty

**Description:** LLM uses confident language ("X has occurred") when sources use hedged language ("officials said X may occur").

**Detection:** Compare hedge words in sources vs. hedge words in briefing.

**Mitigation:** `BRIEFING_PROMPT` instructs "factual, neutral" tone and to use delta_summary for uncertainty. Claim types (`prediction`, `allegation`) capture hedging in structured form.

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

**Mitigation:** `BRIEFING_PROMPT`: "If previous_context is supplied, use it only for background and continuity. Today's articles are the authority for what is new today."

**Current status:** Partially mitigated by prompt design. The delta_summary is a separate field specifically for what is materially new.

**Future improvement:** Add a temporal grounding check: flag when briefing text uses language from previous_context without a temporal qualifier.

---

## 15. Duplicate detection collapses distinct but similar stories

**Description:** The story consolidation step may merge two related but distinct events (e.g. two different diplomatic meetings on the same topic) into a single canonical story.

**Detection:** Eval: compare auto-merged stories against a golden set of known-distinct stories.

**Mitigation:** `CONSOLIDATE_PROMPT` is explicit: "Labels that stand alone still appear as a group of one." The system errs on the side of splitting within a day.

**Current status:** Partially mitigated. The 14-day lookback for cross-day matching may over-merge long-running topics.

**Future improvement:** Add a story splitting mechanism for cases where a canonical story diverges into distinct threads. Reduce lookback for stories that have been quiet for >7 days.
