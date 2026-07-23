from __future__ import annotations

from collections.abc import Iterable

from src.tracker.matching.profiles import (
    MatchProfile,
    normalize_text,
    semantic_tokens,
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
        exact_phrase = normalized in left_text and normalized in right_text
        tokens = semantic_tokens(anchor)
        token_overlap = (
            bool(tokens)
            and tokens <= left.semantic
            and tokens <= right.semantic
        )
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
        tokens = semantic_tokens(anchor) & left.semantic & right.semantic
        if len(tokens) >= 2:
            return True
        shared_tokens.update(tokens)
    return len(shared_tokens) >= 2


def retrieval_signal_anchors(
    shared_headline_tokens: Iterable[str],
) -> list[str]:
    """Return locally grounded headline anchors only when at least two agree."""
    anchors = sorted(
        {
            normalize_text(token)
            for token in shared_headline_tokens
            if normalize_text(token)
        }
    )
    return anchors if len(anchors) >= 2 else []
