from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from src.llm import (
    create_cached_chat_completion,
    mark_schema_failure,
    parse_json_object,
    save_cached_chat_completion,
)
from src.tracker.matching.gate import (
    ACCEPTED_STORY_RELATIONSHIPS,
    CONFIDENT_DECISIONS,
    grounded_shared_anchors,
    has_sufficient_shared_anchors,
    retrieval_signal_anchors,
)
from src.tracker.matching.profiles import (
    MatchProfile,
    distinctive_tokens,
    normalize_text,
    profile_from_articles,
)
from src.tracker.matching.retrieval import (
    CandidateSignals,
    candidate_signals,
    rare_tokens,
    retrieve_candidates,
)
from src.tracker.matching.schemas import (
    SAME_DAY_DECISION_RESPONSE_FORMAT,
    decision_response_keys,
    decisions_by_case_id,
    keyed_decision_response_format,
)


logger = logging.getLogger(__name__)

SAME_DAY_PROMPT_VERSION = "2026-07-23-v5"
SAME_DAY_CASES_PER_CALL = 25
SAME_DAY_CANDIDATES_PER_ARTICLE = 5
SAME_DAY_PROMPT = """You decide whether two current news articles describe the same
specific real-world event or a direct continuation of that event.

Accept only:
- the same named incident, decision, case, operation, negotiation, competition,
  investigation, or other concrete event; or
- a direct factual follow-up whose identity depends on that same concrete event.

Reject articles that merely share a broad topic, place, actor, conflict, sport,
policy area, accident type, or recurring content format. A classifier label is
only a retrieval hint and is never proof. Sharing a named tournament is not
enough: different matches, stages, incidents, or results are separate stories
that may belong to the same arc. Unrelated transfer rumours, crashes, attacks,
lawsuits, or generic updates are separate stories.

Use only the supplied titles and descriptions. Put concrete names, places,
organizations, case names, dates, or other shared identifiers in shared_anchors.
Copy anchors from the supplied evidence in its original language; do not
translate them. List only mutually incompatible identity facts in conflicts,
not ordinary follow-up differences. If the evidence is incomplete or ambiguous,
return uncertain and same_story=false.

Return one decision under every supplied response_key. Never alter, omit, or
invent response keys.

An analysis, explainer, or commentary can continue the same story as a breaking
report when both clearly refer to the same unusual incident; article genre alone
is not an identity conflict. retrieval_signals.shared_semantic_tokens are
deterministic cross-language hints, not proof. Use a distinctive combination
such as an actor plus unusual incident wording, but never a generic token alone."""


@dataclass(frozen=True)
class CandidateEdge:
    left: MatchProfile
    right: MatchProfile
    signals: CandidateSignals

    @property
    def key(self) -> tuple[str, str]:
        left_id, right_id = sorted((self.left.profile_id, self.right.profile_id))
        return left_id, right_id

    @property
    def case_id(self) -> str:
        return "::".join(self.key)


@dataclass(frozen=True)
class TodayStoryGroup:
    group_id: str
    label: str
    articles: tuple[Mapping[str, object], ...]
    profile: MatchProfile


def _article_profile(article: Mapping[str, object], index: int) -> MatchProfile:
    occurrence_id = article.get("occurrence_id")
    article_id = article.get("id")
    stable_id = occurrence_id if occurrence_id is not None else article_id
    return profile_from_articles(
        [article],
        profile_id=f"today:{stable_id if stable_id not in (None, '') else index}",
    )


def _ordered_edge(
    left: MatchProfile,
    right: MatchProfile,
    signals: CandidateSignals,
) -> CandidateEdge:
    if left.profile_id <= right.profile_id:
        return CandidateEdge(left, right, signals)
    return CandidateEdge(right, left, signals)


def same_day_candidate_edges(profiles: Iterable[MatchProfile]) -> list[CandidateEdge]:
    """Retrieve a capped set of evidence pairs, using labels only as a signal."""
    items = list(profiles)
    rare = rare_tokens(items)
    by_key: dict[tuple[str, str], CandidateEdge] = {}

    for index, current in enumerate(items):
        label_edges: dict[tuple[str, str], CandidateEdge] = {}
        retrieved_edges: dict[tuple[str, str], CandidateEdge] = {}
        for retrieved in retrieve_candidates(current, items[index + 1:]):
            edge = _ordered_edge(current, retrieved.profile, retrieved.signals)
            retrieved_edges[edge.key] = edge
        for right in items[index + 1:]:
            exact_classifier_label = (
                bool(normalize_text(current.label))
                and normalize_text(current.label) == normalize_text(right.label)
            )
            exact_url = bool(current.urls & right.urls)
            if not exact_classifier_label and not exact_url:
                continue
            signals = candidate_signals(current, right, rare=rare)
            edge = _ordered_edge(current, right, signals)
            if exact_url:
                by_key[edge.key] = edge
            else:
                label_edges[edge.key] = edge
        ranked_labels = sorted(
            label_edges.values(),
            key=lambda edge: (-edge.signals.score, edge.key),
        )
        remaining = max(
            0,
            SAME_DAY_CANDIDATES_PER_ARTICLE - len(ranked_labels),
        )
        ranked_retrieved = sorted(
            (
                edge
                for key, edge in retrieved_edges.items()
                if key not in label_edges
            ),
            key=lambda edge: (-edge.signals.score, edge.key),
        )
        for edge in (
            ranked_labels[:SAME_DAY_CANDIDATES_PER_ARTICLE]
            + ranked_retrieved[:remaining]
        ):
            by_key[edge.key] = edge

    return sorted(
        by_key.values(),
        key=lambda edge: (-edge.signals.score, edge.key),
    )


def _compact_profile(profile: MatchProfile) -> dict[str, object]:
    return {
        "profile_id": profile.profile_id,
        "classifier_label": profile.label,
        "theme": profile.theme,
        "date": profile.date,
        "titles": list(profile.titles),
        "descriptions": list(profile.descriptions),
        "urls": sorted(profile.urls),
    }


def _case_for_prompt(edge: CandidateEdge) -> dict[str, object]:
    return {
        "case_id": edge.case_id,
        "left": _compact_profile(edge.left),
        "right": _compact_profile(edge.right),
        "retrieval_signals": edge.signals.as_dict(),
    }


def _clean_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        text
        for item in value
        if (text := " ".join(str(item or "").split()))
    ]


def _occurrence_id(profile: MatchProfile) -> int | None:
    return profile.occurrence_ids[0] if profile.occurrence_ids else None


def _base_decision(edge: CandidateEdge, model: str, effort: str) -> dict[str, Any]:
    return {
        "left_occurrence_id": _occurrence_id(edge.left),
        "right_occurrence_id": _occurrence_id(edge.right),
        "candidate_signals": edge.signals.as_dict(),
        "accepted": False,
        "same_event": False,
        "relationship": "uncertain",
        "confidence": "low",
        "continuity_evidence": [],
        "conflicts": [],
        "reject_reason": "",
        "decision_route": "fail_closed",
        "ambiguity_reason": "",
        "matching_model": model,
        "reasoning_effort": effort,
        "prompt_version": SAME_DAY_PROMPT_VERSION,
        "case_id": edge.case_id,
    }


def _deterministic_duplicate_decision(
    edge: CandidateEdge,
    model: str,
    effort: str,
) -> dict[str, Any]:
    decision = _base_decision(edge, model, effort)
    decision.update(
        {
            "accepted": True,
            "same_event": True,
            "relationship": "same_event",
            "confidence": "high",
            "continuity_evidence": ["exact normalized article URL"],
            "decision_route": "deterministic",
        }
    )
    return decision


def _decision_from_model(
    raw: object,
    edge: CandidateEdge,
    model: str,
    effort: str,
) -> dict[str, Any]:
    decision = _base_decision(edge, model, effort)
    if not isinstance(raw, dict) or raw.get("case_id") != edge.case_id:
        decision["reject_reason"] = "Model response did not match the supplied case."
        decision["ambiguity_reason"] = "invalid_or_missing_case"
        return decision

    relationship = raw.get("relationship")
    confidence = raw.get("confidence")
    anchors = _clean_strings(raw.get("shared_anchors"))
    conflicts = _clean_strings(raw.get("conflicts"))
    grounded = grounded_shared_anchors(anchors, edge.left, edge.right)
    model_accepts = raw.get("same_story") is True
    grounded_sufficient = has_sufficient_shared_anchors(
        grounded,
        edge.left,
        edge.right,
    )
    signal_anchors = (
        []
        if grounded_sufficient
        else retrieval_signal_anchors(edge.signals.shared_headline_tokens)
    )
    has_anchors = grounded_sufficient or bool(signal_anchors)
    accepted = (
        model_accepts
        and relationship in ACCEPTED_STORY_RELATIONSHIPS
        and confidence in CONFIDENT_DECISIONS
        and has_anchors
        and not conflicts
    )
    decision.update(
        {
            "accepted": accepted,
            "same_event": accepted,
            "relationship": (
                relationship
                if relationship
                in {
                    "same_event",
                    "direct_continuation",
                    "related_context",
                    "unrelated",
                    "uncertain",
                }
                else "uncertain"
            ),
            "confidence": (
                confidence if confidence in {"high", "medium", "low"} else "low"
            ),
            "continuity_evidence": list(
                dict.fromkeys([*grounded, *signal_anchors])
            ),
            "conflicts": conflicts,
            "reject_reason": " ".join(str(raw.get("reject_reason") or "").split()),
            "decision_route": "mini",
        }
    )
    if accepted:
        return decision

    if model_accepts and not has_anchors:
        decision["ambiguity_reason"] = "insufficient_grounded_shared_anchors"
        decision["decision_route"] = "fail_closed"
    elif model_accepts and conflicts:
        decision["ambiguity_reason"] = "material_conflict"
        decision["decision_route"] = "fail_closed"
    elif relationship == "uncertain":
        decision["ambiguity_reason"] = "model_uncertain"
        decision["decision_route"] = "fail_closed"
    if not decision["reject_reason"]:
        decision["reject_reason"] = "Evidence did not clear the same-story gate."
    return decision


def _chunked(items: list[CandidateEdge], size: int) -> Iterable[list[CandidateEdge]]:
    for index in range(0, len(items), size):
        yield items[index:index + size]


def judge_same_day_edges(
    edges: Iterable[CandidateEdge],
    *,
    get_client: Callable[[], object],
    model: str,
    reasoning_effort: str = "none",
) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    model_edges = []
    for edge in edges:
        if edge.signals.exact_url:
            decisions.append(
                _deterministic_duplicate_decision(edge, model, reasoning_effort)
            )
        else:
            model_edges.append(edge)

    for batch in _chunked(model_edges, SAME_DAY_CASES_PER_CALL):
        response_keys = decision_response_keys(len(batch))
        messages = [
            {"role": "system", "content": SAME_DAY_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "cases": [
                            {
                                "response_key": response_key,
                                **_case_for_prompt(edge),
                            }
                            for response_key, edge in zip(
                                response_keys,
                                batch,
                                strict=True,
                            )
                        ]
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        response, cache_metadata, cache_hit = create_cached_chat_completion(
            get_client,
            model=model,
            messages=messages,
            purpose="match-sameday-evidence",
            prompt_version=SAME_DAY_PROMPT_VERSION,
            response_format=keyed_decision_response_format(
                SAME_DAY_DECISION_RESPONSE_FORMAT,
                len(batch),
            ),
            reasoning_effort=reasoning_effort,
        )
        try:
            payload = parse_json_object(response)
        except ValueError:
            decisions.extend(
                _decision_from_model(None, edge, model, reasoning_effort)
                for edge in batch
            )
            continue
        raw_decisions = payload.get("decisions")
        by_case, complete = decisions_by_case_id(
            raw_decisions,
            [edge.case_id for edge in batch],
        )
        if not complete:
            mark_schema_failure(
                "Same-day response must contain every supplied response key",
                response=response,
            )
        decisions.extend(
            _decision_from_model(
                by_case.get(edge.case_id),
                edge,
                model,
                reasoning_effort,
            )
            for edge in batch
        )
        if not cache_hit and complete:
            save_cached_chat_completion(cache_metadata, response)
    return decisions


def _canonical_label(profiles: Iterable[MatchProfile]) -> str:
    labels = [profile.label.strip() for profile in profiles if profile.label.strip()]
    if not labels:
        return "Unlabeled event"
    counts = Counter(labels)
    return sorted(
        counts,
        key=lambda label: (
            -len(distinctive_tokens(label)),
            -counts[label],
            len(label),
            normalize_text(label),
        ),
    )[0]


def _cluster_profiles(
    profiles: list[MatchProfile],
    edges: list[CandidateEdge],
    decisions: Iterable[Mapping[str, object]],
) -> list[list[MatchProfile]]:
    accepted = {
        (
            str(decision["case_id"]).split("::", 1)[0],
            str(decision["case_id"]).split("::", 1)[1],
        )
        for decision in decisions
        if decision.get("accepted") and "::" in str(decision.get("case_id"))
    }
    edge_scores = {edge.key: edge.signals.score for edge in edges}
    clusters = [[profile] for profile in profiles]
    ordered_pairs = sorted(
        accepted,
        key=lambda pair: (-edge_scores.get(pair, 0), pair),
    )
    for left_id, right_id in ordered_pairs:
        left_cluster = next(
            (cluster for cluster in clusters if any(p.profile_id == left_id for p in cluster)),
            None,
        )
        right_cluster = next(
            (cluster for cluster in clusters if any(p.profile_id == right_id for p in cluster)),
            None,
        )
        if left_cluster is None or right_cluster is None or left_cluster is right_cluster:
            continue
        if all(
            tuple(sorted((left.profile_id, right.profile_id))) in accepted
            for left in left_cluster
            for right in right_cluster
        ):
            left_cluster.extend(right_cluster)
            clusters.remove(right_cluster)
    return clusters


def group_today_articles(
    articles: Iterable[Mapping[str, object]],
    *,
    get_client: Callable[[], object],
    model: str,
    reasoning_effort: str = "none",
) -> tuple[list[TodayStoryGroup], list[dict[str, Any]]]:
    """Group today's individual articles without trusting classifier labels."""
    items = list(articles)
    profiles = [_article_profile(article, index) for index, article in enumerate(items)]
    articles_by_profile = dict(zip((profile.profile_id for profile in profiles), items))
    edges = same_day_candidate_edges(profiles)
    decisions = judge_same_day_edges(
        edges,
        get_client=get_client,
        model=model,
        reasoning_effort=reasoning_effort,
    )
    clusters = _cluster_profiles(profiles, edges, decisions)
    groups = []
    for cluster in clusters:
        label = _canonical_label(cluster)
        cluster_articles = tuple(articles_by_profile[profile.profile_id] for profile in cluster)
        group_key = ",".join(sorted(profile.profile_id for profile in cluster))
        groups.append(
            TodayStoryGroup(
                group_id=f"group:{group_key}",
                label=label,
                articles=cluster_articles,
                profile=profile_from_articles(
                    cluster_articles,
                    label=label,
                    profile_id=f"group:{group_key}",
                ),
            )
        )
    groups.sort(key=lambda group: group.group_id)
    logger.info(
        "  Evidence-grouped %s articles -> %s current stories",
        len(items),
        len(groups),
    )
    return groups, decisions


def groups_as_story_mapping(
    groups: Iterable[TodayStoryGroup],
) -> dict[str, list[Mapping[str, object]]]:
    """Return unique grounded labels for the legacy tracker mapping contract."""
    items = list(groups)
    label_counts = Counter(normalize_text(group.label) for group in items)
    mapped: dict[str, list[Mapping[str, object]]] = {}
    for group in items:
        label = group.label
        if label_counts[normalize_text(label)] > 1:
            label = group.profile.titles[0] if group.profile.titles else label
        base = label
        suffix = 2
        while label in mapped:
            label = f"{base} ({suffix})"
            suffix += 1
        mapped[label] = list(group.articles)
    return mapped
