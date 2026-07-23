from __future__ import annotations

import json
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
)
from src.tracker.matching.profiles import (
    MatchProfile,
    profile_from_articles,
    profile_from_story,
)
from src.tracker.matching.retrieval import CandidateSignals, retrieve_candidates
from src.tracker.matching.schemas import STORY_DECISION_RESPONSE_FORMAT


CROSS_DAY_PROMPT_VERSION = "2026-07-23-v2"
CROSS_DAY_CASES_PER_CALL = 25
CROSS_DAY_PROMPT = """You decide whether a current article group continues one
specific tracked news story.

Accept only the same concrete event or a direct factual continuation: the same
named incident, case, operation, negotiation, investigation, policy decision,
competition, or other identifiable real-world event. Reject broad topic,
country, actor, conflict, market, sport, accident-type, or recurring-format
similarity. An existing label, arc label, and retrieval score are hints, never
proof.

Use only the supplied current evidence and stored source-grounded memory.
Put concrete shared identifiers in shared_anchors, copying their original
wording rather than translating them. Put only mutually incompatible identity
facts in conflicts, not ordinary follow-up differences. If identity or
continuity is ambiguous, return uncertain and same_story=false."""


@dataclass(frozen=True)
class CrossDayCase:
    today_label: str
    current: MatchProfile
    candidate_label: str
    candidate: MatchProfile
    candidate_story: Mapping[str, object]
    signals: CandidateSignals

    @property
    def case_id(self) -> str:
        return f"{self.current.profile_id}=>{self.candidate.profile_id}"


def _compact_profile(profile: MatchProfile) -> dict[str, object]:
    return {
        "profile_id": profile.profile_id,
        "label": profile.label,
        "theme": profile.theme,
        "date": profile.date,
        "titles": list(profile.titles),
        "descriptions": list(profile.descriptions),
        "memory_summaries": list(profile.summaries),
        "urls": sorted(profile.urls),
    }


def _prompt_case(case: CrossDayCase) -> dict[str, object]:
    return {
        "case_id": case.case_id,
        "current": _compact_profile(case.current),
        "candidate_story": {
            **_compact_profile(case.candidate),
            "story_id": case.candidate_story.get("story_id"),
            "first_seen": case.candidate_story.get("first_seen", ""),
            "active_days": case.candidate_story.get("active_days", 0),
        },
        "retrieval_signals": case.signals.as_dict(),
    }


def story_candidate_cases(
    today_labels: Iterable[str],
    recent_stories: Mapping[str, Mapping[str, object]],
    story_groups: Mapping[str, list[Mapping[str, object]]],
) -> list[CrossDayCase]:
    candidate_profiles = {
        label: profile_from_story(label, story)
        for label, story in recent_stories.items()
    }
    label_by_profile_id = {
        profile.profile_id: label
        for label, profile in candidate_profiles.items()
    }
    cases = []
    for today_label in sorted(today_labels):
        articles = story_groups.get(today_label, [])
        if not articles:
            continue
        current = profile_from_articles(
            articles,
            label=today_label,
            profile_id=f"today-group:{today_label}",
        )
        for retrieved in retrieve_candidates(current, candidate_profiles.values()):
            candidate_label = label_by_profile_id[retrieved.profile.profile_id]
            cases.append(
                CrossDayCase(
                    today_label=today_label,
                    current=current,
                    candidate_label=candidate_label,
                    candidate=retrieved.profile,
                    candidate_story=recent_stories[candidate_label],
                    signals=retrieved.signals,
                )
            )
    return cases


def _clean_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        text
        for item in value
        if (text := " ".join(str(item or "").split()))
    ]


def _base_decision(
    case: CrossDayCase,
    model: str,
    effort: str,
) -> dict[str, Any]:
    return {
        "today_label": case.today_label,
        "candidate_label": case.candidate_label,
        "candidate_story_id": case.candidate_story.get("story_id"),
        "accepted": False,
        "same_event": False,
        "relationship": "uncertain",
        "confidence": "low",
        "article_dates": [case.current.date] if case.current.date else [],
        "candidate_last_seen": case.candidate_story.get("last_seen", ""),
        "continuity_evidence": [],
        "reject_reason": "",
        "verifier_model": model,
        "prompt_version": CROSS_DAY_PROMPT_VERSION,
        "decision_route": "fail_closed",
        "candidate_signals": case.signals.as_dict(),
        "conflicts": [],
        "ambiguity_reason": "",
        "reasoning_effort": effort,
        "case_id": case.case_id,
    }


def _exact_url_decision(
    case: CrossDayCase,
    model: str,
    effort: str,
) -> dict[str, Any]:
    decision = _base_decision(case, model, effort)
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
    case: CrossDayCase,
    model: str,
    effort: str,
) -> dict[str, Any]:
    decision = _base_decision(case, model, effort)
    if not isinstance(raw, dict) or raw.get("case_id") != case.case_id:
        decision["reject_reason"] = "Model response did not match the supplied case."
        decision["ambiguity_reason"] = "invalid_or_missing_case"
        return decision

    relationship = raw.get("relationship")
    confidence = raw.get("confidence")
    conflicts = _clean_strings(raw.get("conflicts"))
    grounded = grounded_shared_anchors(
        _clean_strings(raw.get("shared_anchors")),
        case.current,
        case.candidate,
    )
    model_accepts = raw.get("same_story") is True
    has_anchors = has_sufficient_shared_anchors(
        grounded,
        case.current,
        case.candidate,
    )
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
            "continuity_evidence": grounded,
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


def _chunks(
    values: list[CrossDayCase],
    size: int,
) -> Iterable[list[CrossDayCase]]:
    for index in range(0, len(values), size):
        yield values[index:index + size]


def match_story_groups(
    today_labels: Iterable[str],
    recent_stories: Mapping[str, Mapping[str, object]],
    story_groups: Mapping[str, list[Mapping[str, object]]],
    *,
    get_client: Callable[[], object],
    model: str,
    reasoning_effort: str = "none",
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Retrieve and judge cross-day candidates in one mini stage."""
    labels = set(today_labels)
    cases = story_candidate_cases(labels, recent_stories, story_groups)
    decisions: list[dict[str, Any]] = []
    model_cases = []
    for case in cases:
        if case.signals.exact_url:
            decisions.append(_exact_url_decision(case, model, reasoning_effort))
        else:
            model_cases.append(case)

    for batch in _chunks(model_cases, CROSS_DAY_CASES_PER_CALL):
        messages = [
            {"role": "system", "content": CROSS_DAY_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {"cases": [_prompt_case(case) for case in batch]},
                    ensure_ascii=False,
                ),
            },
        ]
        response, cache_metadata, cache_hit = create_cached_chat_completion(
            get_client,
            model=model,
            messages=messages,
            purpose="match-crossday-evidence",
            prompt_version=CROSS_DAY_PROMPT_VERSION,
            response_format=STORY_DECISION_RESPONSE_FORMAT,
            reasoning_effort=reasoning_effort,
        )
        try:
            payload = parse_json_object(response)
        except ValueError:
            decisions.extend(
                _decision_from_model(None, case, model, reasoning_effort)
                for case in batch
            )
            continue
        raw_decisions = payload.get("decisions")
        if not isinstance(raw_decisions, list):
            mark_schema_failure(
                "Cross-day response decisions must be an array",
                response=response,
            )
            raw_decisions = []
        by_case = {
            raw.get("case_id"): raw
            for raw in raw_decisions
            if isinstance(raw, dict) and isinstance(raw.get("case_id"), str)
        }
        expected_ids = {case.case_id for case in batch}
        if set(by_case) != expected_ids:
            mark_schema_failure(
                "Cross-day response must contain each supplied case exactly once",
                response=response,
            )
        decisions.extend(
            _decision_from_model(
                by_case.get(case.case_id),
                case,
                model,
                reasoning_effort,
            )
            for case in batch
        )
        if not cache_hit and set(by_case) == expected_ids:
            save_cached_chat_completion(cache_metadata, response)

    label_map = {label: "NEW" for label in labels}
    for today_label in labels:
        accepted = [
            decision
            for decision in decisions
            if decision["today_label"] == today_label and decision["accepted"]
        ]
        if len(accepted) == 1:
            label_map[today_label] = str(accepted[0]["candidate_label"])
            continue
        if len(accepted) > 1:
            for decision in accepted:
                decision["accepted"] = False
                decision["same_event"] = False
                decision["decision_route"] = "fail_closed"
                decision["ambiguity_reason"] = "multiple_accepted_candidates"
                decision["reject_reason"] = (
                    "Multiple candidate stories cleared the gate; no merge was made."
                )
    return label_map, decisions
