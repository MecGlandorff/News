import re
from datetime import date

from src.article_dates import editorial_date
from src.tracker.matching.constants import GENERIC_EVENT_TOKENS, LABEL_STOPWORDS


def label_tokens(label):
    tokens = re.findall(r"[a-z0-9]+", str(label or "").casefold())
    return {token for token in tokens if len(token) > 1}


def truncate_text(value, limit):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip() + "..."


def clean_string(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def clean_list(value):
    if not isinstance(value, list):
        return []
    cleaned = []
    for item in value:
        text = clean_string(item)
        if text:
            cleaned.append(text)
    return cleaned


def article_date(value):
    text = clean_string(value)
    if not text:
        return ""
    parsed = editorial_date(text)
    if parsed is not None:
        return parsed.isoformat()
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except (TypeError, ValueError):
        return text


def days_since(value, today, default_days):
    try:
        return (date.fromisoformat(str(today)) - date.fromisoformat(str(value))).days
    except (TypeError, ValueError):
        return default_days + 1


def distinctive_label_tokens(label):
    return label_tokens(label) - LABEL_STOPWORDS - GENERIC_EVENT_TOKENS


def is_generic_event_label(label):
    return bool(label_tokens(label) & GENERIC_EVENT_TOKENS)


def labels_can_refer_to_same_story(left, right):
    """Reject obvious false merges for generic incident/category labels.

    LLM label matching is useful for paraphrases, but broad labels such as
    "accident" or "shooting" are unsafe without a shared distinctive token.
    A false negative creates a duplicate story; a false positive corrupts
    story memory across days.
    """
    if str(left or "").strip().casefold() == str(right or "").strip().casefold():
        return True
    if not (is_generic_event_label(left) and is_generic_event_label(right)):
        return True
    return bool(distinctive_label_tokens(left) & distinctive_label_tokens(right))


def exact_label_reuse_allowed(label: str) -> bool:
    """Whether an identical canonical label alone may reuse a story row.

    Generic incident labels ("Stabbing attack") recur across unrelated
    real-world events, so exact-label equality is only trusted when the
    label carries at least one distinctive token.
    """
    if not is_generic_event_label(label):
        return True
    return bool(distinctive_label_tokens(label))


def compatible_label_clusters(labels):
    clusters = []
    for label in labels:
        placed = False
        for cluster in clusters:
            if all(labels_can_refer_to_same_story(label, existing) for existing in cluster):
                cluster.append(label)
                placed = True
                break
        if not placed:
            clusters.append([label])
    return clusters


def canonical_for_cluster(canonical, cluster, split_group):
    if not split_group:
        return canonical
    if canonical in cluster:
        return canonical
    if all(labels_can_refer_to_same_story(canonical, label) for label in cluster):
        return canonical
    return cluster[0]
