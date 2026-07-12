from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.briefing import generation, grounding, markdown, selection, service
from src.briefing.constants import (
    BRIEFING_PROMPT,
    BRIEFING_PROMPT_VERSION,
    CONFIDENCE_VALUES,
    DISPUTE_FLAG_VALUES,
    SOURCE_AGREEMENT_VALUES,
    STATUS_VALUES,
)
from src.briefing.types import BriefingCard, BriefingPackage
from src.config import BRIEFING_MODEL
from src.llm import get_openai_client
from src.tracker import save_observation_memory


BRIEFINGS_DIR = Path("briefings")
THEME_ORDER = selection.THEME_ORDER
POLITICS_THEMES = selection.POLITICS_THEMES
LOW_INTEREST_KEYWORDS = selection.LOW_INTEREST_KEYWORDS
TREND_SCORE = selection.TREND_SCORE

choice = grounding.choice
display_choice = grounding.display_choice
clean_open_questions = grounding.clean_open_questions
local_dispute_flag = grounding.local_dispute_flag
default_status = grounding.default_status
default_confidence = grounding.default_confidence
default_source_agreement = grounding.default_source_agreement
default_briefing_payload = grounding.default_briefing_payload
defaults_by_label = grounding.defaults_by_label
normalize_briefing_payloads = grounding.normalize_briefing_payloads
merge_briefing_payloads = grounding.merge_briefing_payloads
payload_briefing = grounding.payload_briefing
fallback_delta_summary = grounding.fallback_delta_summary
missing_briefing_stories = grounding.missing_briefing_stories
fallback_briefing = grounding.fallback_briefing
get_briefings = generation.get_briefings


def _get_briefings(stories, include_evidence=False):
    return generation.get_briefings(
        stories,
        get_client=get_openai_client,
        model=BRIEFING_MODEL,
        include_evidence=include_evidence,
    )


def _evidence_lines(story_id, as_of_date=None):
    return markdown._evidence_lines(story_id, as_of_date=as_of_date)


def build_briefing_package(
    tracked,
    n=3,
    global_n=10,
    include_evidence=False,
) -> BriefingPackage:
    return service.build_briefing_package(
        tracked,
        n=n,
        global_n=global_n,
        include_evidence=include_evidence,
        get_briefings=_get_briefings,
        save_observation_memory=save_observation_memory,
    )


def build_briefing_markdown(
    tracked,
    n=3,
    global_n=10,
    package=None,
    show_evidence=False,
):
    package = package or build_briefing_package(
        tracked,
        n=n,
        global_n=global_n,
        include_evidence=show_evidence,
    )
    return markdown.build_briefing_markdown(
        tracked,
        n=n,
        global_n=global_n,
        package=package,
        show_evidence=show_evidence,
    )


def write_top10(tracked, n=3, package=None, show_evidence=False):
    BRIEFINGS_DIR.mkdir(exist_ok=True)
    rendered = build_briefing_markdown(
        tracked,
        n=n,
        package=package,
        show_evidence=show_evidence,
    )
    output_path = BRIEFINGS_DIR / f"briefing_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    output_path.write_text(rendered, encoding="utf-8")
    print(f"Written: {output_path}")
    return output_path


__all__ = [
    "BRIEFINGS_DIR",
    "BRIEFING_PROMPT",
    "BRIEFING_PROMPT_VERSION",
    "BriefingCard",
    "BriefingPackage",
    "CONFIDENCE_VALUES",
    "DISPUTE_FLAG_VALUES",
    "LOW_INTEREST_KEYWORDS",
    "POLITICS_THEMES",
    "SOURCE_AGREEMENT_VALUES",
    "STATUS_VALUES",
    "THEME_ORDER",
    "TREND_SCORE",
    "build_briefing_markdown",
    "build_briefing_package",
    "clean_open_questions",
    "choice",
    "default_briefing_payload",
    "default_confidence",
    "default_source_agreement",
    "default_status",
    "display_choice",
    "fallback_briefing",
    "fallback_delta_summary",
    "get_briefings",
    "local_dispute_flag",
    "merge_briefing_payloads",
    "missing_briefing_stories",
    "normalize_briefing_payloads",
    "payload_briefing",
    "write_top10",
]
