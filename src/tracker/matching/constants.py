from src.config import (
    ARC_ASSIGNMENT_ACCEPT_RELATIONSHIPS,
    ARC_ASSIGNMENT_CONTEXT_RELATIONSHIPS,
    ARC_ASSIGNMENT_REJECT_RELATIONSHIPS,
    STORY_VERIFY_ACCEPT_RELATIONSHIPS,
    STORY_VERIFY_CONTEXT_RELATIONSHIPS,
    STORY_VERIFY_REJECT_RELATIONSHIPS,
)


VERIFY_RELATIONSHIP_VALUES = (
    *STORY_VERIFY_ACCEPT_RELATIONSHIPS,
    *STORY_VERIFY_CONTEXT_RELATIONSHIPS,
    *STORY_VERIFY_REJECT_RELATIONSHIPS,
)

VERIFY_RELATIONSHIP_TEXT = " | ".join(VERIFY_RELATIONSHIP_VALUES)

ARC_RELATIONSHIP_VALUES = (
    *ARC_ASSIGNMENT_ACCEPT_RELATIONSHIPS,
    *ARC_ASSIGNMENT_CONTEXT_RELATIONSHIPS,
    *ARC_ASSIGNMENT_REJECT_RELATIONSHIPS,
)

ARC_RELATIONSHIP_TEXT = " | ".join(ARC_RELATIONSHIP_VALUES)

CONSOLIDATE_PROMPT = """You are grouping today's news story labels that refer to the same ongoing story.

Given a list of story labels from today, identify groups that are clearly about the same event.
For each group, pick the best canonical label (clear, concise, in English).

Return a JSON object with key "groups": array of {canonical_label, labels} where labels is the list of today's labels that belong to this group.
Every input label must appear exactly once. Canonical labels must be unique.
Labels that stand alone still appear as a group of one."""

CONSOLIDATE_PROMPT_VERSION = "2026-07-11-v2"

MATCH_PROMPT = """You are matching today's news story labels to recent canonical story memory.

For each match case, return either:
- The matching canonical label from recent history (if it is the same ongoing story)
- "NEW" (if it's a genuinely new story)

Be conservative: slight wording differences for the same real-world story should match, but broad topic similarity is not enough.
Different stories, incidents, crashes, attacks, lawsuits, or accidents must not match merely because they share a category word.
Use the recent story summaries and recent article titles to check whether today's label continues the same event, not merely the same topic.
Only match a today_label to one of its supplied candidates. If no candidate is a strong match, return "NEW".

Return a JSON object with key "matches": array of {today_label, canonical_label}.
canonical_label is either the exact string from the recent-history list or "NEW"."""

MATCH_PROMPT_VERSION = "2026-05-11-v1"

VERIFY_PROMPT_VERSION = "2026-05-08-v1"

VERIFY_PROMPT = """You are verifying whether today's article group continues an existing tracked news story.

For each case, decide whether the current article group is the same real-world event or continuing story arc as the candidate story.

Accept only direct continuity:
- same_event: the same named incident, raid, attack, lawsuit, negotiation, vote, court case, investigation, disaster, policy decision, or operation
- same_story_arc: a direct continuation of the same named ongoing arc, with shared concrete actors and event identity
- direct_follow_up: a later legal, diplomatic, operational, or factual follow-up to the same concrete event

Reject broad or adjacent relationships:
- adjacent_topic: same broad topic, place, actor, allegation type, or conflict context, but not the same tracked event
- broader_context: useful background or big-picture context, but not a continuation of the candidate story
- unrelated: no meaningful relationship
- uncertain: not enough concrete continuity evidence

Big-picture context can be useful, but it must not be merged into the same story unless the article directly continues the candidate event.

Return a JSON object with key "decisions": array of:
{
  "today_label": string,
  "canonical_label": string,
  "same_event": boolean,
  "relationship": one of: """ + VERIFY_RELATIONSHIP_TEXT + """,
  "confidence": one of: high | medium | low,
  "article_dates": array of date strings from the current articles,
  "candidate_last_seen": date string,
  "continuity_evidence": array of short strings naming the shared concrete event evidence,
  "reject_reason": string
}

If evidence is weak or the relationship is adjacent, set same_event=false."""

ARC_ASSIGNMENT_PROMPT_VERSION = "2026-05-20-v1"

ARC_ASSIGNMENT_PROMPT = """You are assigning unmatched current news stories to broader existing story arcs.

This is not a same-event merge. The same-event verifier has already failed or found no direct continuation.
Your task is only to decide whether today's concrete story belongs under one supplied broader arc or parent story.

Accept an existing arc only when the current story shares concrete actors, geography, conflict, policy thread, legal matter, market, disaster, or continuing public-interest context with that arc.
Reject broad category overlap, generic topic similarity, and weak vibes.
Choose only from the supplied candidate arc_id values and optional parent_story_id values.
Use "NEW_ARC" when none of the supplied arcs is a good broader home.

Return a JSON object with key "assignments": array of:
{
  "today_label": string,
  "arc_id": integer or "NEW_ARC",
  "parent_story_id": integer or null,
  "relationship": one of: """ + ARC_RELATIONSHIP_TEXT + """,
  "confidence": one of: high | medium | low,
  "continuity_evidence": array of short strings naming the concrete arc evidence,
  "reject_reason": string
}"""

LABEL_STOPWORDS = {
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "into",
    "of", "on", "or", "over", "the", "to", "with",
}

GENERIC_EVENT_TOKENS = {
    "accident", "arrest", "attack", "blast", "case", "charges", "charged",
    "collapse", "collision", "crash", "crowd", "danger", "dangerous",
    "death", "fire", "homicide", "incident", "injured", "injuries",
    "injury", "killing", "lawsuit", "manslaughter", "murder", "poisoning",
    "protest", "rescue", "riot", "safety", "shooting", "shooter",
    "stabbing", "strike", "trial", "unrest", "violence", "wounded",
}

CANDIDATES_PER_LABEL = 10

MATCH_CASES_PER_CALL = 50

SUMMARY_CHAR_LIMIT = 400

DELTA_CHAR_LIMIT = 240

TITLE_CHAR_LIMIT = 160

VERIFY_ARTICLE_TEXT_CHAR_LIMIT = 16000

VERIFY_DESCRIPTION_CHAR_LIMIT = 1200

VERIFY_ARTICLES_PER_CASE = 4

VERIFY_CASES_PER_CALL = 8

VERIFY_ACCEPT_RELATIONSHIPS = set(STORY_VERIFY_ACCEPT_RELATIONSHIPS)

VERIFY_RELATIONSHIPS = set(VERIFY_RELATIONSHIP_VALUES)

VERIFY_CONFIDENCE_VALUES = {"high", "medium", "low"}

ARC_ACCEPT_RELATIONSHIPS = set(ARC_ASSIGNMENT_ACCEPT_RELATIONSHIPS)

ARC_RELATIONSHIPS = set(ARC_RELATIONSHIP_VALUES)

ARC_CANDIDATES_PER_LABEL = 8

ARC_ASSIGNMENT_CASES_PER_CALL = 12
