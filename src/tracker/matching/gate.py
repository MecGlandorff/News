from __future__ import annotations

from collections.abc import Iterable

from src.tracker.matching.profiles import (
    MatchProfile,
    content_tokens,
    normalize_text,
)


ACCEPTED_STORY_RELATIONSHIPS = {"same_event", "direct_continuation"}
CONFIDENT_DECISIONS = {"high", "medium"}


def grounded_shared_anchors(
    anchors: Iterable[object],
    left: MatchProfile,
    right: MatchProfile,
) -> list[str]:
    """Return model-supplied anchors that are present in both evidence profiles."""
    left_text = normalize_text(left.evidence_text())
    right_text = normalize_text(right.evidence_text())
    grounded = []
    for raw_anchor in anchors:
        anchor = " ".join(str(raw_anchor or "").split())
        normalized = normalize_text(anchor)
        if not normalized:
            continue
        tokens = content_tokens(anchor)
        exact_phrase = normalized in left_text and normalized in right_text
        token_overlap = bool(tokens) and tokens <= left.tokens and tokens <= right.tokens
        if exact_phrase or token_overlap:
            grounded.append(anchor)
    return grounded


def has_sufficient_shared_anchors(
    anchors: Iterable[str],
    left: MatchProfile,
    right: MatchProfile,
) -> bool:
    """Require one grounded phrase or at least two grounded distinctive tokens."""
    grounded = grounded_shared_anchors(anchors, left, right)
    shared_tokens: set[str] = set()
    for anchor in grounded:
        tokens = content_tokens(anchor) & left.distinctive & right.distinctive
        if len(tokens) >= 2:
            return True
        shared_tokens.update(tokens)
    return len(shared_tokens) >= 2

