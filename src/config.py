CLASSIFIER_MODEL = "gpt-5.4-mini"
CLAIMS_MODEL     = "gpt-5.4-nano"
TRACKER_MODEL    = "gpt-5.5"
CROSSDAY_MATCH_MODEL = "gpt-5.4-mini"
STORY_MATCH_VERIFIER_MODEL = "gpt-5.4-nano"
ARC_ASSIGNMENT_MODEL = "gpt-5.4-mini"
BRIEFING_MODEL   = "gpt-5.5"

DEFAULT_LOOKBACK_DAYS = 14

CLASSIFIER_RETRY_BATCH_SIZE = 25
CLASSIFIER_BLOCKED_STORY_LABELS = (
    "uncategorized",
)

STORY_MEMORY_QUARANTINE_LABEL = "Classifier omission quarantine"
STORY_MEMORY_QUARANTINE_SOURCE_LABELS = (
    "uncategorized",
)
STORY_MEMORY_BLOCKED_LABELS = (
    *STORY_MEMORY_QUARANTINE_SOURCE_LABELS,
    STORY_MEMORY_QUARANTINE_LABEL,
)

STORY_VERIFY_ACCEPT_RELATIONSHIPS = (
    "same_event",
    "same_story_arc",
    "direct_follow_up",
)
STORY_VERIFY_CONTEXT_RELATIONSHIPS = (
    "adjacent_topic",
    "broader_context",
)
STORY_VERIFY_REJECT_RELATIONSHIPS = (
    "unrelated",
    "uncertain",
)

ARC_ASSIGNMENT_ACCEPT_RELATIONSHIPS = (
    "same_arc",
    "parent_context",
)
ARC_ASSIGNMENT_CONTEXT_RELATIONSHIPS = (
    "adjacent_topic",
    "broader_context",
)
ARC_ASSIGNMENT_REJECT_RELATIONSHIPS = (
    "unrelated",
    "uncertain",
)

# Standard uncached API token prices from OpenAI's API pricing page, in USD
# per 1M tokens. These estimates do not model cached-input discounts, Batch,
# Flex, Priority, regional processing, or long-context uplifts. Update
# deliberately when model pricing changes.
MODEL_PRICING_USD_PER_1M_TOKENS = {
    "gpt-5.5": {"input": 5.00, "output": 30.00},
    "gpt-5.4": {"input": 2.50, "output": 15.00},
    "gpt-5.4-mini": {"input": 0.75, "output": 4.50},
    "gpt-5.4-nano": {"input": 0.20, "output": 1.25},
}
USD_TO_EUR_RATE = 0.8525
