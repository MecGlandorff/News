from __future__ import annotations

from datetime import datetime
from typing import Any, TypedDict


class BriefingCard(TypedDict, total=False):
    briefing: str
    delta_summary: str
    status: str
    confidence: str
    source_agreement: str
    dispute_flag: str
    open_questions: list[str]


class BriefingPackage(TypedDict):
    generated_at: datetime
    stories: list[dict[str, Any]]
    sections: list[tuple[str, list[dict[str, Any]]]]
    display_stories: list[dict[str, Any]]
    briefings: dict[str, str]
    deltas: dict[str, str]
    briefing_cards: dict[str, BriefingCard]
