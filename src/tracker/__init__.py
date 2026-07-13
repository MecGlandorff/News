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

CONSOLIDATE_PROMPT = story_matching.CONSOLIDATE_PROMPT
MATCH_PROMPT = story_matching.MATCH_PROMPT
LABEL_STOPWORDS = story_matching.LABEL_STOPWORDS
GENERIC_EVENT_TOKENS = story_matching.GENERIC_EVENT_TOKENS
CANDIDATES_PER_LABEL = story_matching.CANDIDATES_PER_LABEL
SUMMARY_CHAR_LIMIT = story_matching.SUMMARY_CHAR_LIMIT
DELTA_CHAR_LIMIT = story_matching.DELTA_CHAR_LIMIT
TITLE_CHAR_LIMIT = story_matching.TITLE_CHAR_LIMIT
VERIFY_PROMPT_VERSION = story_matching.VERIFY_PROMPT_VERSION

ReplayError = replay.ReplayError
ReplayResult = replay.ReplayResult
rebuild_from_date = replay.rebuild_from_date


def _get_db():
    return tracker_store.get_db(DB_PATH)


def _create_story_arc(conn, canonical_label, theme, first_seen, last_seen):
    return tracker_store.create_story_arc(
        conn,
        canonical_label,
        theme,
        first_seen,
        last_seen,
    )


def _get_recent_stories(conn, today, lookback_days=DEFAULT_LOOKBACK_DAYS):
    return tracker_store.get_recent_stories(conn, today, lookback_days)


def _trend(story_id, today_count, conn, today):
    return tracker_store.trend(story_id, today_count, conn, today)


def save_observation_memory(memories, *, db_path=None):
    return tracker_store.save_observation_memory(db_path or DB_PATH, memories)


def _fetch_article_text_for_match(url):
    from src.scraper import fetch_article_text

    return fetch_article_text(url)


def _consolidate_today(story_groups):
    return story_matching.consolidate_today(
        story_groups,
        get_client=get_openai_client,
        model=TRACKER_MODEL,
    )


def _candidate_cases_for_prompt(
    today_labels,
    recent_stories,
    today=None,
    limit=CANDIDATES_PER_LABEL,
):
    return story_matching.candidate_cases_for_prompt(
        today_labels,
        recent_stories,
        today=today,
        limit=limit,
        default_days=DEFAULT_LOOKBACK_DAYS,
    )


def _match_labels(today_labels, recent_stories, today=None):
    return story_matching.match_labels(
        today_labels,
        recent_stories,
        get_client=get_openai_client,
        model=CROSSDAY_MATCH_MODEL,
        today=today,
        default_days=DEFAULT_LOOKBACK_DAYS,
    )


def _verify_story_matches(label_map, recent_stories, story_groups, today=None):
    return story_matching.verify_story_matches(
        label_map,
        recent_stories,
        story_groups,
        get_client=get_openai_client,
        model=STORY_MATCH_VERIFIER_MODEL,
        today=today,
    )


def _assign_story_arcs(today_labels, recent_arcs, story_groups, today=None):
    return story_matching.assign_story_arcs(
        today_labels,
        recent_arcs,
        story_groups,
        get_client=get_openai_client,
        model=ARC_ASSIGNMENT_MODEL,
        today=today,
        default_days=DEFAULT_LOOKBACK_DAYS,
    )


def _callbacks_for(client_factory):
    if client_factory is None:
        return (
            _consolidate_today,
            _match_labels,
            _verify_story_matches,
            _assign_story_arcs,
        )
    return (
        lambda groups: story_matching.consolidate_today(
            groups,
            get_client=client_factory,
            model=TRACKER_MODEL,
        ),
        lambda labels, recent, today=None: story_matching.match_labels(
            labels,
            recent,
            get_client=client_factory,
            model=CROSSDAY_MATCH_MODEL,
            today=today,
            default_days=DEFAULT_LOOKBACK_DAYS,
        ),
        lambda label_map, recent, groups, today=None: story_matching.verify_story_matches(
            label_map,
            recent,
            groups,
            get_client=client_factory,
            model=STORY_MATCH_VERIFIER_MODEL,
            today=today,
        ),
        lambda labels, arcs, groups, today=None: story_matching.assign_story_arcs(
            labels,
            arcs,
            groups,
            get_client=client_factory,
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
):
    consolidate, match, verify, assign = _callbacks_for(client_factory)
    return service.track(
        classified,
        today=today,
        lookback_days=lookback_days,
        verify_story_matches=verify_story_matches,
        db_path=Path(db_path) if db_path is not None else DB_PATH,
        data_dir=Path(data_dir) if data_dir is not None else DATA_DIR,
        consolidate_today=consolidate,
        match_labels=match,
        verify_matches=verify,
        assign_arcs=assign,
        fetch_article_text=fetch_article_text or _fetch_article_text_for_match,
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
