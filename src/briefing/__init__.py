from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.briefing import generation, markdown, selection, service
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

def generate_briefings(
    stories,
    include_evidence=False,
    *,
    client_factory=None,
    claims_provider=None,
):
    resolved_client_factory = (
        client_factory if client_factory is not None else get_openai_client
    )
    return generation.get_briefings(
        stories,
        get_client=resolved_client_factory,
        model=BRIEFING_MODEL,
        include_evidence=include_evidence,
        get_claims=claims_provider,
    )


def build_briefing_package(
    tracked,
    n=3,
    global_n=10,
    include_evidence=False,
    *,
    briefing_provider=None,
    save_memory=None,
    client_factory=None,
    claims_provider=None,
) -> BriefingPackage:
    resolved_provider = briefing_provider
    if resolved_provider is None:
        def generated_provider(stories, include_evidence=False):
            return generate_briefings(
                stories,
                include_evidence=include_evidence,
                client_factory=client_factory,
                claims_provider=claims_provider,
            )

        resolved_provider = generated_provider

    resolved_save_memory = (
        save_memory if save_memory is not None else save_observation_memory
    )

    return service.build_briefing_package(
        tracked,
        n=n,
        global_n=global_n,
        include_evidence=include_evidence,
        get_briefings=resolved_provider,
        save_observation_memory=resolved_save_memory,
    )


def build_briefing_markdown(
    tracked,
    n=3,
    global_n=10,
    package=None,
    show_evidence=False,
    *,
    briefing_provider=None,
    save_memory=None,
    client_factory=None,
    claims_provider=None,
):
    package = package or build_briefing_package(
        tracked,
        n=n,
        global_n=global_n,
        include_evidence=show_evidence,
        briefing_provider=briefing_provider,
        save_memory=save_memory,
        client_factory=client_factory,
        claims_provider=claims_provider,
    )
    return markdown.build_briefing_markdown(
        tracked,
        n=n,
        global_n=global_n,
        package=package,
        show_evidence=show_evidence,
        get_claims=claims_provider,
    )


def write_top10(
    tracked,
    n=3,
    package=None,
    show_evidence=False,
    *,
    output_dir=None,
    briefing_provider=None,
    save_memory=None,
    client_factory=None,
    claims_provider=None,
):
    output_dir = Path(output_dir) if output_dir is not None else BRIEFINGS_DIR
    output_dir.mkdir(exist_ok=True)
    rendered = build_briefing_markdown(
        tracked,
        n=n,
        package=package,
        show_evidence=show_evidence,
        briefing_provider=briefing_provider,
        save_memory=save_memory,
        client_factory=client_factory,
        claims_provider=claims_provider,
    )
    output_path = output_dir / f"briefing_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
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
    "generate_briefings",
    "write_top10",
]
