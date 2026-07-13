import json
import logging

from src.llm import (
    create_cached_chat_completion,
    mark_schema_failure,
    parse_json_object,
    save_cached_chat_completion,
)
from src.tracker.matching.constants import CONSOLIDATE_PROMPT, CONSOLIDATE_PROMPT_VERSION
from src.tracker.matching.labels import (
    canonical_for_cluster,
    clean_string,
    compatible_label_clusters,
)


logger = logging.getLogger(__name__)


def validated_consolidation_groups(groups, known_labels):
    """Return normalized model groups only when they form an exact partition."""
    if not isinstance(groups, list) or not groups:
        return None

    normalized = []
    seen_labels = set()
    seen_canonicals = set()
    for group in groups:
        if not isinstance(group, dict):
            return None
        canonical = group.get("canonical_label")
        group_labels = group.get("labels")
        if not isinstance(canonical, str) or not clean_string(canonical):
            return None
        if not isinstance(group_labels, list) or not group_labels:
            return None
        if not all(isinstance(label, str) and label in known_labels for label in group_labels):
            return None
        if len(group_labels) != len(set(group_labels)):
            return None

        canonical_key = clean_string(canonical).casefold()
        if canonical_key in seen_canonicals or seen_labels.intersection(group_labels):
            return None
        seen_canonicals.add(canonical_key)
        seen_labels.update(group_labels)
        normalized.append((clean_string(canonical), list(group_labels)))

    if seen_labels != set(known_labels):
        return None
    return normalized


def consolidate_today(story_groups, get_client, model):
    """Merge story labels that refer to the same event within today's batch."""
    labels = list(story_groups.keys())
    if len(labels) <= 1:
        return story_groups

    messages = [
        {"role": "system", "content": CONSOLIDATE_PROMPT},
        {"role": "user", "content": json.dumps(labels, ensure_ascii=False)},
    ]
    response, cache_metadata, cache_hit = create_cached_chat_completion(
        get_client,
        model=model,
        messages=messages,
        purpose="match-sameday",
        prompt_version=CONSOLIDATE_PROMPT_VERSION,
        response_format={"type": "json_object"},
    )
    try:
        payload = parse_json_object(response)
    except ValueError as exc:
        logger.warning(
            "Rejected invalid same-day consolidation response; keeping original labels: %s",
            exc,
        )
        return story_groups
    groups = validated_consolidation_groups(payload.get("groups"), labels)
    if groups is None:
        mark_schema_failure(
            "Consolidation response must partition every input label exactly once "
            "with unique canonical labels",
            response=response,
        )
        logger.warning("Rejected malformed same-day consolidation; keeping original labels")
        return story_groups
    if not cache_hit:
        save_cached_chat_completion(cache_metadata, response)

    from collections import defaultdict
    consolidated = defaultdict(list)
    for canonical, group_labels in groups:
        clusters = compatible_label_clusters(group_labels)
        split_group = len(clusters) > 1
        for cluster in clusters:
            cluster_canonical = canonical_for_cluster(canonical, cluster, split_group)
            for label in cluster:
                consolidated[cluster_canonical].extend(story_groups[label])

    logger.info("  Consolidated %s labels -> %s stories", len(story_groups), len(consolidated))
    return consolidated
