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
    CONFIDENT_DECISIONS,
    grounded_shared_anchors,
    has_sufficient_shared_anchors,
)
from src.tracker.matching.profiles import (
    MatchProfile,
    content_tokens,
    distinctive_tokens,
    normalize_text,
    profile_from_arc,
    profile_from_articles,
)
from src.tracker.matching.retrieval import CandidateSignals, retrieve_candidates
from src.tracker.matching.schemas import ARC_DECISION_RESPONSE_FORMAT


ARC_EVIDENCE_PROMPT_VERSION = "2026-07-23-v2"
ARC_EVIDENCE_CASES_PER_CALL = 20
ARC_EVIDENCE_PROMPT = """You decide whether a new concrete news story belongs
inside one existing named, continuing real-world event arc.

This is not a same-story merge. Accept same_arc only when the new event and the
candidate are distinct developments inside the same identifiable ongoing
container, such as a named war, election, tournament, court case, negotiation,
investigation, disaster, or policy rollout. Use parent_context only when the new
story is a direct consequence or specific follow-up of one supplied child story;
otherwise parent_story_id must be null.

Reject broad topic, country, actor, industry, sport, generic accident type,
recurring entertainment format, episode recap, spoiler stream, transfer-rumour
roundup, or weak contextual similarity.

Use concrete shared names, places, organizations, case names, competition names,
dates, or other identifiers as shared_anchors. List material conflicts. When a
one-story arc has an overly narrow label, proposed_arc_label may supply a short,
source-grounded named umbrella; otherwise repeat the existing arc label. If
evidence is ambiguous, return uncertain and belongs_to_arc=false. Copy anchors
from the supplied evidence in its original language. Do not list the expected
difference between two developments, a follow-up sequence, or an overly narrow
arc label as a conflict; conflicts are mutually incompatible container identity
facts."""

RECURRING_FORMAT_TERMS = {
    "daily roundup",
    "episode recap",
    "live blog",
    "recap",
    "rumour roundup",
    "rumor roundup",
    "soap spoilers",
    "spoilers",
    "transfer news",
    "transfer rumours",
    "transfer rumors",
}

NON_MATERIAL_ARC_DIFFERENCE_CUES = {
    "broader",
    "different specific development",
    "distinct development",
    "follow-up",
    "general",
    "narrowly phrased",
    "overly narrow",
    "temporal sequence",
}


def material_arc_conflicts(conflicts: Iterable[str]) -> list[str]:
    material = []
    for conflict in conflicts:
        normalized = normalize_text(conflict)
        if any(cue in normalized for cue in NON_MATERIAL_ARC_DIFFERENCE_CUES):
            continue
        material.append(conflict)
    return material


@dataclass(frozen=True)
class ArcEvidenceCase:
    today_label: str
    current: MatchProfile
    arc: MatchProfile
    arc_option: Mapping[str, object]
    signals: CandidateSignals

    @property
    def case_id(self) -> str:
        return f"{self.current.profile_id}=>{self.arc.profile_id}"


def is_recurring_content_format(*values: object) -> bool:
    text = normalize_text(" ".join(str(value or "") for value in values))
    return any(term in text for term in RECURRING_FORMAT_TERMS)


def _valid_parent_ids(case: ArcEvidenceCase) -> set[int]:
    result: set[int] = set()
    recent_stories = case.arc_option.get("recent_stories")
    if not isinstance(recent_stories, list):
        return result
    for story in recent_stories:
        if not isinstance(story, Mapping):
            continue
        for field in ("story_id", "parent_story_id"):
            value = story.get(field)
            if isinstance(value, int):
                result.add(value)
    return result


def _compact_profile(profile: MatchProfile) -> dict[str, object]:
    return {
        "profile_id": profile.profile_id,
        "label": profile.label,
        "theme": profile.theme,
        "date": profile.date,
        "titles": list(profile.titles),
        "descriptions": list(profile.descriptions),
        "memory_summaries": list(profile.summaries),
    }


def _prompt_case(case: ArcEvidenceCase) -> dict[str, object]:
    recent_stories = case.arc_option.get("recent_stories")
    valid_stories = recent_stories if isinstance(recent_stories, list) else []
    return {
        "case_id": case.case_id,
        "current_story": _compact_profile(case.current),
        "candidate_arc": {
            **_compact_profile(case.arc),
            "arc_id": case.arc_option.get("arc_id"),
            "active_days": case.arc_option.get("active_days", 0),
            "recent_stories": [
                {
                    "story_id": story.get("story_id"),
                    "label": story.get("canonical_label", ""),
                    "parent_story_id": story.get("parent_story_id"),
                    "parent_label": story.get("parent_label", ""),
                    "summary": story.get("summary", ""),
                    "last_delta": story.get("delta_summary", ""),
                }
                for story in valid_stories
                if isinstance(story, Mapping)
            ],
        },
        "retrieval_signals": case.signals.as_dict(),
    }


def arc_evidence_cases(
    today_labels: Iterable[str],
    recent_arcs: Mapping[int, Mapping[str, object]],
    story_groups: Mapping[str, list[Mapping[str, object]]],
) -> list[ArcEvidenceCase]:
    arc_profiles = {
        arc_id: profile_from_arc(arc)
        for arc_id, arc in recent_arcs.items()
    }
    arc_id_by_profile = {
        profile.profile_id: arc_id
        for arc_id, profile in arc_profiles.items()
    }
    cases = []
    for today_label in sorted(today_labels):
        articles = story_groups.get(today_label, [])
        if not articles:
            continue
        current = profile_from_articles(
            articles,
            label=today_label,
            profile_id=f"today-arc:{today_label}",
        )
        for retrieved in retrieve_candidates(current, arc_profiles.values()):
            arc_id = arc_id_by_profile[retrieved.profile.profile_id]
            cases.append(
                ArcEvidenceCase(
                    today_label=today_label,
                    current=current,
                    arc=retrieved.profile,
                    arc_option=recent_arcs[arc_id],
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


def _grounded_promotion_label(
    proposed: object,
    case: ArcEvidenceCase,
) -> str:
    label = " ".join(str(proposed or "").split())
    if not label or len(label) > 100 or len(label.split()) > 10:
        return case.arc.label
    if is_recurring_content_format(label):
        return case.arc.label
    tokens = content_tokens(label)
    if len(distinctive_tokens(label)) < 2:
        return case.arc.label
    if not tokens <= (case.current.tokens | case.arc.tokens):
        return case.arc.label
    shared_identity = (
        distinctive_tokens(label)
        & case.current.distinctive
        & case.arc.distinctive
    )
    if len(shared_identity) < 2:
        return case.arc.label
    return label


def _base_decision(
    case: ArcEvidenceCase,
    model: str,
    effort: str,
) -> dict[str, Any]:
    arc_id = case.arc_option.get("arc_id")
    previous_label = str(case.arc_option.get("canonical_label") or case.arc.label)
    return {
        "today_label": case.today_label,
        "arc_id": None,
        "parent_story_id": None,
        "proposed_arc_id": arc_id,
        "proposed_parent_story_id": None,
        "accepted": False,
        "relationship": "uncertain",
        "confidence": "low",
        "continuity_evidence": [],
        "conflicts": [],
        "reject_reason": "",
        "verifier_model": model,
        "prompt_version": ARC_EVIDENCE_PROMPT_VERSION,
        "decision_route": "fail_closed",
        "candidate_signals": case.signals.as_dict(),
        "ambiguity_reason": "",
        "reasoning_effort": effort,
        "previous_arc_label": previous_label,
        "proposed_arc_label": previous_label,
        "final_arc_label": previous_label,
        "case_id": case.case_id,
    }


def _format_rejection(
    case: ArcEvidenceCase,
    model: str,
    effort: str,
) -> dict[str, Any]:
    decision = _base_decision(case, model, effort)
    decision.update(
        {
            "relationship": "unrelated",
            "confidence": "high",
            "reject_reason": "Recurring content formats do not form durable event arcs.",
            "decision_route": "deterministic",
        }
    )
    return decision


def _decision_from_model(
    raw: object,
    case: ArcEvidenceCase,
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
    reported_conflicts = _clean_strings(raw.get("conflicts"))
    conflicts = material_arc_conflicts(reported_conflicts)
    grounded = grounded_shared_anchors(
        _clean_strings(raw.get("shared_anchors")),
        case.current,
        case.arc,
    )
    has_anchors = has_sufficient_shared_anchors(
        grounded,
        case.current,
        case.arc,
    )
    raw_parent_id = raw.get("parent_story_id")
    proposed_parent_id = raw_parent_id if isinstance(raw_parent_id, int) else None
    parent_id = (
        proposed_parent_id
        if relationship == "parent_context"
        and proposed_parent_id in _valid_parent_ids(case)
        else None
    )
    valid_parent = relationship != "parent_context" or parent_id is not None
    model_accepts = raw.get("belongs_to_arc") is True
    accepted = (
        model_accepts
        and relationship in {"same_arc", "parent_context"}
        and confidence in CONFIDENT_DECISIONS
        and has_anchors
        and not conflicts
        and valid_parent
        and not is_recurring_content_format(
            case.today_label,
            *case.current.titles,
            case.arc.label,
        )
    )
    previous_label = str(
        case.arc_option.get("canonical_label") or case.arc.label
    )
    recent_stories = case.arc_option.get("recent_stories")
    one_story_arc = (
        isinstance(recent_stories, list)
        and len(recent_stories) == 1
    )
    proposed_label = " ".join(
        str(raw.get("proposed_arc_label") or previous_label).split()
    )
    final_label = (
        _grounded_promotion_label(proposed_label, case)
        if accepted and one_story_arc
        else previous_label
    )
    decision.update(
        {
            "arc_id": case.arc_option.get("arc_id") if accepted else None,
            "parent_story_id": parent_id if accepted else None,
            "proposed_parent_story_id": proposed_parent_id,
            "accepted": accepted,
            "relationship": (
                relationship
                if relationship
                in {
                    "same_arc",
                    "parent_context",
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
            "proposed_arc_label": proposed_label,
            "final_arc_label": final_label,
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
    elif model_accepts and not valid_parent:
        decision["ambiguity_reason"] = "invalid_parent_context"
        decision["decision_route"] = "fail_closed"
    elif relationship == "uncertain":
        decision["ambiguity_reason"] = "model_uncertain"
        decision["decision_route"] = "fail_closed"
    if not decision["reject_reason"]:
        decision["reject_reason"] = "Evidence did not clear the named-arc gate."
    return decision


def _chunks(
    values: list[ArcEvidenceCase],
    size: int,
) -> Iterable[list[ArcEvidenceCase]]:
    for index in range(0, len(values), size):
        yield values[index:index + size]


def assign_story_arcs_evidence(
    today_labels: Iterable[str],
    recent_arcs: Mapping[int, Mapping[str, object]],
    story_groups: Mapping[str, list[Mapping[str, object]]],
    *,
    get_client: Callable[[], object],
    model: str,
    reasoning_effort: str = "none",
) -> dict[str, dict[str, Any]]:
    cases = arc_evidence_cases(today_labels, recent_arcs, story_groups)
    decisions: list[dict[str, Any]] = []
    model_cases = []
    for case in cases:
        if is_recurring_content_format(
            case.today_label,
            *case.current.titles,
            case.arc.label,
        ):
            decisions.append(_format_rejection(case, model, reasoning_effort))
        else:
            model_cases.append(case)

    for batch in _chunks(model_cases, ARC_EVIDENCE_CASES_PER_CALL):
        messages = [
            {"role": "system", "content": ARC_EVIDENCE_PROMPT},
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
            purpose="match-arc-evidence",
            prompt_version=ARC_EVIDENCE_PROMPT_VERSION,
            response_format=ARC_DECISION_RESPONSE_FORMAT,
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
                "Arc response decisions must be an array",
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
                "Arc response must contain each supplied case exactly once",
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

    by_label: dict[str, list[dict[str, Any]]] = {}
    for decision in decisions:
        by_label.setdefault(str(decision["today_label"]), []).append(decision)

    assignments = {}
    for today_label, label_decisions in by_label.items():
        accepted = [decision for decision in label_decisions if decision["accepted"]]
        if len(accepted) == 1:
            chosen = accepted[0]
        elif len(accepted) > 1:
            chosen = label_decisions[0]
            for decision in accepted:
                decision["accepted"] = False
                decision["arc_id"] = None
                decision["parent_story_id"] = None
                decision["decision_route"] = "fail_closed"
                decision["ambiguity_reason"] = "multiple_accepted_arcs"
                decision["reject_reason"] = (
                    "Multiple arcs cleared the gate; a new arc was created."
                )
        else:
            chosen = label_decisions[0]
        chosen["candidates"] = [
            {
                "arc_id": decision.get("proposed_arc_id"),
                "arc_label": decision.get("previous_arc_label", ""),
                "score": decision.get("candidate_signals", {}).get("score", 0),
            }
            for decision in label_decisions
        ]
        assignments[today_label] = chosen
    return assignments
