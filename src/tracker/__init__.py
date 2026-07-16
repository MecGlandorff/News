from pathlib import Path

from src.config import (
    ARC_ASSIGNMENT_MODEL,
    CROSSDAY_MATCH_MODEL,
    DEFAULT_LOOKBACK_DAYS,
    STORY_MATCH_VERIFIER_MODEL,
    TRACKER_MODEL,
)
from src.llm import get_openai_client
from src.tracker import matching as story_matching
from src.tracker import replay, service
from src.tracker import store as tracker_store


DB_PATH = Path("data/stories.db")
DATA_DIR = Path("data/daily")

ReplayError = replay.ReplayError
ReplayResult = replay.ReplayResult
rebuild_from_date = replay.rebuild_from_date


def save_observation_memory(memories, *, db_path=None):
    resolved_db_path = Path(db_path) if db_path is not None else DB_PATH
    return tracker_store.save_observation_memory(resolved_db_path, memories)


def _fetch_article_text_for_match(url):
    from src.scraper import fetch_article_text

    return fetch_article_text(url)


def _callbacks_for(client_factory):
    resolved_client_factory = (
        client_factory if client_factory is not None else get_openai_client
    )
    return (
        lambda groups: story_matching.consolidate_today(
            groups,
            get_client=resolved_client_factory,
            model=TRACKER_MODEL,
        ),
        lambda labels, recent, today=None: story_matching.match_labels(
            labels,
            recent,
            get_client=resolved_client_factory,
            model=CROSSDAY_MATCH_MODEL,
            today=today,
            default_days=DEFAULT_LOOKBACK_DAYS,
        ),
        lambda label_map, recent, groups, today=None: story_matching.verify_story_matches(
            label_map,
            recent,
            groups,
            get_client=resolved_client_factory,
            model=STORY_MATCH_VERIFIER_MODEL,
            today=today,
        ),
        lambda labels, arcs, groups, today=None: story_matching.assign_story_arcs(
            labels,
            arcs,
            groups,
            get_client=resolved_client_factory,
            model=ARC_ASSIGNMENT_MODEL,
            today=today,
            default_days=DEFAULT_LOOKBACK_DAYS,
        ),
    )


def track(
    classified,
    today=None,
    lookback_days=DEFAULT_LOOKBACK_DAYS,
    verify_story_matches=True,
    *,
    db_path=None,
    data_dir=None,
    client_factory=None,
    fetch_article_text=None,
    consolidate_today=None,
    match_labels=None,
    verify_matches=None,
    assign_arcs=None,
):
    default_consolidate, default_match, default_verify, default_assign = _callbacks_for(
        client_factory
    )
    return service.track(
        classified,
        today=today,
        lookback_days=lookback_days,
        verify_story_matches=verify_story_matches,
        db_path=Path(db_path) if db_path is not None else DB_PATH,
        data_dir=Path(data_dir) if data_dir is not None else DATA_DIR,
        consolidate_today=(
            consolidate_today if consolidate_today is not None else default_consolidate
        ),
        match_labels=match_labels if match_labels is not None else default_match,
        verify_matches=verify_matches if verify_matches is not None else default_verify,
        assign_arcs=assign_arcs if assign_arcs is not None else default_assign,
        fetch_article_text=(
            fetch_article_text
            if fetch_article_text is not None
            else _fetch_article_text_for_match
        ),
    )


__all__ = [
    "DATA_DIR",
    "DB_PATH",
    "ReplayError",
    "ReplayResult",
    "rebuild_from_date",
    "save_observation_memory",
    "track",
]
