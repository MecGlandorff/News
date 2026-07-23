from __future__ import annotations

import math
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date
from typing import Iterable

from src.tracker.matching.profiles import MatchProfile, normalize_text


DEFAULT_CANDIDATE_LIMIT = 5


def rare_tokens(profiles: Iterable[MatchProfile]) -> frozenset[str]:
    items = list(profiles)
    frequencies = Counter(
        token
        for profile in items
        for token in profile.distinctive
    )
    threshold = max(2, math.ceil(len(items) * 0.10))
    return frozenset(
        token
        for token, frequency in frequencies.items()
        if frequency <= threshold
    )


def _days_apart(left: str, right: str) -> int | None:
    try:
        return abs((date.fromisoformat(left[:10]) - date.fromisoformat(right[:10])).days)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class CandidateSignals:
    score: int
    exact_url: bool
    exact_label: bool
    theme_match: bool
    shared_distinctive_tokens: tuple[str, ...]
    shared_rare_tokens: tuple[str, ...]
    shared_phrases: tuple[str, ...]
    shared_numbers: tuple[str, ...]
    different_years: tuple[str, ...]
    days_apart: int | None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RetrievedCandidate:
    profile: MatchProfile
    signals: CandidateSignals


def candidate_signals(
    current: MatchProfile,
    candidate: MatchProfile,
    *,
    rare: frozenset[str],
) -> CandidateSignals:
    exact_url = bool(current.urls & candidate.urls)
    exact_label = (
        bool(normalize_text(current.label))
        and normalize_text(current.label) == normalize_text(candidate.label)
    )
    shared_distinctive = current.distinctive & candidate.distinctive
    shared_rare = shared_distinctive & rare
    shared_phrases = current.phrases & candidate.phrases
    shared_numbers = current.numbers & candidate.numbers
    different_years = (
        current.years | candidate.years
        if current.years and candidate.years and current.years.isdisjoint(candidate.years)
        else frozenset()
    )
    theme_match = bool(current.theme and current.theme == candidate.theme)
    age = _days_apart(current.date, candidate.date)

    score = 0
    if exact_url:
        score += 1_000
    if exact_label and shared_distinctive:
        score += 30
    score += len(shared_rare) * 14
    score += len(shared_distinctive - shared_rare) * 6
    score += len(shared_phrases) * 16
    score += len(shared_numbers) * 4
    if theme_match:
        score += 2
    if age is not None:
        score += max(0, 6 - min(age, 6))
    if different_years:
        score -= 8

    return CandidateSignals(
        score=score,
        exact_url=exact_url,
        exact_label=exact_label,
        theme_match=theme_match,
        shared_distinctive_tokens=tuple(sorted(shared_distinctive)),
        shared_rare_tokens=tuple(sorted(shared_rare)),
        shared_phrases=tuple(sorted(shared_phrases)),
        shared_numbers=tuple(sorted(shared_numbers)),
        different_years=tuple(sorted(different_years)),
        days_apart=age,
    )


def is_plausible_candidate(signals: CandidateSignals) -> bool:
    if signals.exact_url:
        return True
    if signals.shared_phrases and signals.shared_distinctive_tokens:
        return True
    if (
        len(signals.shared_distinctive_tokens) >= 2
        and signals.shared_rare_tokens
    ):
        return True
    if signals.shared_rare_tokens and (
        signals.shared_numbers
        or signals.exact_label
        or signals.theme_match
    ):
        return True
    return False


def retrieve_candidates(
    current: MatchProfile,
    candidate_profiles: Iterable[MatchProfile],
    *,
    limit: int = DEFAULT_CANDIDATE_LIMIT,
) -> list[RetrievedCandidate]:
    candidates = list(candidate_profiles)
    rare = rare_tokens((current, *candidates))
    retrieved = []
    for candidate in candidates:
        signals = candidate_signals(current, candidate, rare=rare)
        if not is_plausible_candidate(signals):
            continue
        retrieved.append(RetrievedCandidate(candidate, signals))
    retrieved.sort(
        key=lambda item: (
            -item.signals.score,
            normalize_text(item.profile.label),
            item.profile.profile_id,
        )
    )
    return retrieved[:limit]

