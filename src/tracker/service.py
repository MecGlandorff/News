import json
import logging

from src import observability
from src.article_dates import editorial_today
from src.config import (
    ARC_ASSIGNMENT_MODEL,
    DEFAULT_LOOKBACK_DAYS,
    TRACKER_MODEL,
    STORY_MATCH_VERIFIER_MODEL,
)
from src.tracker import matching, occurrences, store


logger = logging.getLogger(__name__)


def _record_story_match_verification_totals(decisions):
    if not decisions:
        return
    observability.update_run_totals(
        story_match_verifications=len(decisions),
        story_match_accepts=sum(1 for decision in decisions if decision.get("accepted")),
        story_match_rejections=sum(1 for decision in decisions if not decision.get("accepted")),
    )


def _record_matching_audit_totals(
    same_day_decisions,
    story_decisions,
    arc_decisions,
):
    decisions = [
        *same_day_decisions,
        *story_decisions,
        *arc_decisions,
    ]
    observability.update_run_totals(
        same_day_match_candidates=len(same_day_decisions),
        same_day_match_accepts=sum(
            1 for decision in same_day_decisions if decision.get("accepted")
        ),
        matching_deterministic_decisions=sum(
            1 for decision in decisions
            if decision.get("decision_route") == "deterministic"
        ),
        matching_mini_decisions=sum(
            1 for decision in decisions
            if decision.get("decision_route") == "mini"
        ),
        matching_fail_closed_decisions=sum(
            1 for decision in decisions
            if decision.get("decision_route") == "fail_closed"
        ),
        matching_ambiguous_cases=sum(
            1 for decision in decisions
            if decision.get("ambiguity_reason")
        ),
    )


def _ensure_match_article_text(story_groups, labels, fetch_article_text):
    fetch_successes = 0
    fetch_failures = 0
    enriched_articles = []
    for label in labels:
        for article in story_groups.get(label, []):
            if (article.get("text") or "").strip():
                continue
            url = article.get("url")
            if not url:
                continue
            try:
                article["text"] = fetch_article_text(url)
                if (article.get("text") or "").strip():
                    fetch_successes += 1
                    enriched_articles.append(article)
                else:
                    fetch_failures += 1
            except Exception:
                # Network fetch failure falls back to existing RSS text and is counted.
                article["text"] = article.get("text") or ""
                fetch_failures += 1
    observability.increment_run_totals(
        article_text_fetch_successes=fetch_successes,
        article_text_fetch_failures=fetch_failures,
    )
    return enriched_articles


def _record_article_occurrences(articles, editorial_date, db_path):
    conn = store.get_db(db_path)
    try:
        with conn:
            return occurrences.record_occurrences(conn, articles, editorial_date)
    finally:
        conn.close()


def _write_daily_articles(path, articles):
    path.write_text(
        json.dumps(articles, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def track(
    classified,
    today=None,
    lookback_days=DEFAULT_LOOKBACK_DAYS,
    verify_story_matches=True,
    *,
    db_path,
    data_dir,
    consolidate_today,
    match_labels,
    verify_matches,
    assign_arcs,
    fetch_article_text,
    group_evidence=None,
    match_evidence=None,
):
    if not classified:
        return []

    today = today or str(editorial_today())
    data_dir.mkdir(parents=True, exist_ok=True)

    # Capture source evidence before any model-driven grouping. Raw occurrence
    # rows survive reruns and historical replay; only their derived snapshots
    # may be updated.
    occurrence_ids = _record_article_occurrences(classified, today, db_path)
    classified = [
        {
            **article,
            "occurrence_id": occurrence_ids[str(article["id"])],
            "editorial_date": today,
        }
        for article in classified
    ]

    # Save full articles to daily JSON
    daily_path = data_dir / today
    daily_path.mkdir(exist_ok=True)
    daily_articles_path = daily_path / "articles.json"
    _write_daily_articles(daily_articles_path, classified)

    same_day_decisions = []
    if group_evidence is not None:
        story_groups, same_day_decisions = group_evidence(classified)
    else:
        # Legacy/explicit opt-out path retained for replay and injected tests.
        from collections import defaultdict
        raw_groups = defaultdict(list)
        for a in classified:
            raw_groups[a["story_label"]].append(a)
        story_groups = consolidate_today(raw_groups)

    conn = store.get_db(db_path)
    try:
        with conn:
            store.quarantine_uncategorized_memory(conn)
        recent_story_options = store.get_recent_story_options(conn, today, lookback_days)
        recent_arc_options = store.get_recent_arc_options(conn, today, lookback_days)
        recent_stories = {
            label: option["story_id"]
            for label, option in recent_story_options.items()
        }
    finally:
        conn.close()

    # Match current evidence to recent source-grounded memory outside the write
    # transaction. The default path retrieves locally and uses one mini stage.
    match_decisions = []
    if match_evidence is not None:
        label_map, match_decisions = match_evidence(
            set(story_groups.keys()),
            recent_story_options,
            story_groups,
            today=today,
        )
    else:
        label_map = match_labels(
            set(story_groups.keys()),
            recent_story_options,
            today=today,
        )
    if verify_story_matches and match_evidence is None:
        candidate_labels = {
            label
            for label, canonical in label_map.items()
            if canonical != "NEW" and canonical in recent_story_options
        }
        enriched_articles = _ensure_match_article_text(story_groups, candidate_labels, fetch_article_text)
        if enriched_articles:
            enriched_occurrence_ids = _record_article_occurrences(enriched_articles, today, db_path)
            for article in enriched_articles:
                article["occurrence_id"] = enriched_occurrence_ids[str(article["id"])]
            _write_daily_articles(daily_articles_path, classified)
        label_map, match_decisions = verify_matches(
            label_map,
            recent_story_options,
            story_groups,
            today=today,
        )
    rejected_story_ids = matching.rejected_candidate_story_ids(match_decisions)
    unmatched_labels = {
        label
        for label, canonical in label_map.items()
        if canonical == "NEW" or canonical not in recent_stories
    }
    arc_assignments = assign_arcs(
        unmatched_labels,
        recent_arc_options,
        story_groups,
        today=today,
    )

    conn = store.get_db(db_path)
    try:
        with conn:
            store.save_same_day_match_decisions(
                conn,
                [
                    decision
                    for decision in same_day_decisions
                    if decision.get("left_occurrence_id") is not None
                    and decision.get("right_occurrence_id") is not None
                ],
                today,
                TRACKER_MODEL,
                matching.SAME_DAY_PROMPT_VERSION,
            )
            store.save_story_match_decisions(
                conn,
                match_decisions,
                today,
                STORY_MATCH_VERIFIER_MODEL,
                matching.VERIFY_PROMPT_VERSION,
            )
            store.reset_tracking_date(conn, today)
            occurrences.clear_assignments_for_date(conn, today)

            # Resolve today's labels to concrete stories. Same-story matches
            # reuse story rows; arc matches create child story rows under the
            # broader arc without merging the concrete events.
            assignments = []
            new_parent_count = 0
            new_child_count = 0
            new_arc_count = 0
            arc_attachment_count = 0
            promoted_arc_ids = set()
            for story_label, articles in story_groups.items():
                canonical = label_map.get(story_label, "NEW")
                arc_assignment = arc_assignments.get(story_label) or {}
                development_status = "continuing"
                parent_relationship = ""
                parent_confidence = ""
                created_new_story = False

                if canonical == "NEW" or canonical not in recent_stories:
                    story_id = store.find_story_by_label(conn, story_label, today, lookback_days)
                    if story_id in rejected_story_ids.get(story_label, ()):
                        # The verifier rejected this candidate as the same
                        # event; exact-label reuse must not remake the merge
                        # it just blocked (ADR 0008).
                        story_id = None
                    if story_id:
                        conn.execute(
                            "UPDATE stories SET last_seen = ? WHERE story_id = ?",
                            (today, story_id)
                        )
                        if arc_assignment.get("accepted"):
                            development_status = "new_child"
                            parent_relationship = arc_assignment.get("relationship", "")
                            parent_confidence = arc_assignment.get("confidence", "")
                            new_child_count += 1
                            arc_attachment_count += 1
                        else:
                            development_status = "new_parent"
                    else:
                        parent_story_id = None
                        if arc_assignment.get("accepted"):
                            arc_id = arc_assignment["arc_id"]
                            parent_story_id = arc_assignment.get("parent_story_id")
                            development_status = "new_child"
                            parent_relationship = arc_assignment.get("relationship", "")
                            parent_confidence = arc_assignment.get("confidence", "")
                            new_child_count += 1
                            arc_attachment_count += 1
                        else:
                            arc_id = store.create_story_arc(
                                conn,
                                story_label,
                                articles[0]["theme"],
                                today,
                                today,
                            )
                            development_status = "new_parent"
                            new_arc_count += 1
                        cur = conn.execute(
                            """
                            INSERT INTO stories (
                                arc_id, parent_story_id, canonical_label,
                                theme, first_seen, last_seen
                            )
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                arc_id,
                                parent_story_id,
                                story_label,
                                articles[0]["theme"],
                                today,
                                today,
                            )
                        )
                        story_id = cur.lastrowid
                        created_new_story = True
                    canonical_label = story_label
                    new_parent_count += (
                        1
                        if created_new_story and development_status == "new_parent"
                        else 0
                    )
                else:
                    story_id = recent_stories[canonical]
                    canonical_label = canonical
                    conn.execute(
                        "UPDATE stories SET last_seen = ? WHERE story_id = ?",
                        (today, story_id)
                    )
                promoted_arc_label = arc_assignment.get("final_arc_label", "")
                previous_arc_label = arc_assignment.get("previous_arc_label", "")
                promoted_arc_id = arc_assignment.get("arc_id")
                if (
                    arc_assignment.get("accepted")
                    and promoted_arc_id is not None
                    and promoted_arc_label
                    and promoted_arc_label != previous_arc_label
                ):
                    conn.execute(
                        "UPDATE story_arcs SET canonical_label = ? WHERE arc_id = ?",
                        (promoted_arc_label, promoted_arc_id),
                    )
                    promoted_arc_ids.add(promoted_arc_id)
                hierarchy = store.get_story_hierarchy(conn, story_id)

                assignments.append({
                    "story_label": story_label,
                    "canonical_label": canonical_label,
                    "story_id": story_id,
                    "arc_id": hierarchy["arc_id"],
                    "arc_label": hierarchy["arc_label"],
                    "parent_story_id": hierarchy["parent_story_id"],
                    "parent_label": hierarchy["parent_label"],
                    "articles": articles,
                    "development_status": development_status,
                    "parent_relationship": parent_relationship,
                    "parent_confidence": parent_confidence,
                })

            # Persist arc-assignment decisions once labels have resolved to
            # story rows, so each decision links to the story it produced.
            store.save_story_arc_decisions(
                conn,
                list(arc_assignments.values()),
                today,
                ARC_ASSIGNMENT_MODEL,
                matching.ARC_ASSIGNMENT_PROMPT_VERSION,
                story_ids={
                    assignment["story_label"]: assignment["story_id"]
                    for assignment in assignments
                },
            )

            from collections import defaultdict
            parent_groups = defaultdict(lambda: {
                "canonical_label": "",
                "arc_id": None,
                "arc_label": "",
                "parent_story_id": None,
                "parent_label": "",
                "articles": [],
                "assignments": [],
                "labels": [],
            })
            for assignment in assignments:
                parent = parent_groups[assignment["story_id"]]
                parent["canonical_label"] = assignment["canonical_label"]
                parent["arc_id"] = assignment["arc_id"]
                parent["arc_label"] = assignment["arc_label"]
                parent["parent_story_id"] = assignment["parent_story_id"]
                parent["parent_label"] = assignment["parent_label"]
                parent["articles"].extend(assignment["articles"])
                parent["assignments"].append(assignment)
                parent["labels"].append(assignment["story_label"])

            tracked = []
            for story_id, parent in parent_groups.items():
                articles = parent["articles"]
                labels = parent["labels"]
                previous_context = store.get_previous_story_context(conn, story_id, today)
                source_count   = len(set(a["source"] for a in articles))
                importance_avg = sum(a["importance"] for a in articles) / len(articles)
                trend          = store.trend(story_id, source_count, conn, today)

                conn.execute(
                    """
                    INSERT OR REPLACE INTO story_daily (story_id, date, source_count, importance_avg, labels_seen)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (story_id, today, source_count, importance_avg, json.dumps(labels, ensure_ascii=False))
                )

                label_seen = labels[0] if len(labels) == 1 else json.dumps(labels, ensure_ascii=False)
                conn.execute("""
                    INSERT INTO story_observations (
                        story_id, date, label_seen, source_count, article_count, importance_avg
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(story_id, date) DO UPDATE SET
                        label_seen = excluded.label_seen,
                        source_count = excluded.source_count,
                        article_count = excluded.article_count,
                        importance_avg = excluded.importance_avg,
                        created_at = CURRENT_TIMESTAMP
                """, (story_id, today, label_seen, source_count, len(articles), importance_avg))
                observation_id = conn.execute(
                    "SELECT observation_id FROM story_observations WHERE story_id = ? AND date = ?",
                    (story_id, today)
                ).fetchone()["observation_id"]

                conn.execute(
                    "DELETE FROM articles WHERE story_id = ? AND date = ?",
                    (story_id, today)
                )
                conn.execute(
                    "DELETE FROM article_story_links WHERE story_id = ? AND observation_id = ?",
                    (story_id, observation_id)
                )
                for assignment in parent["assignments"]:
                    development_articles = assignment["articles"]
                    development_source_count = len(set(a["source"] for a in development_articles))
                    development_importance = (
                        sum(a["importance"] for a in development_articles) / len(development_articles)
                    )
                    conn.execute("""
                        INSERT INTO story_developments (
                            story_id, observation_id, date, development_label,
                            development_status, source_count, article_count, importance_avg,
                            parent_relationship, parent_confidence
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(story_id, date, development_label) DO UPDATE SET
                            observation_id = excluded.observation_id,
                            development_status = excluded.development_status,
                            source_count = excluded.source_count,
                            article_count = excluded.article_count,
                            importance_avg = excluded.importance_avg,
                            parent_relationship = excluded.parent_relationship,
                            parent_confidence = excluded.parent_confidence,
                            created_at = CURRENT_TIMESTAMP
                    """, (
                        story_id,
                        observation_id,
                        today,
                        assignment["story_label"],
                        assignment["development_status"],
                        development_source_count,
                        len(development_articles),
                        development_importance,
                        assignment["parent_relationship"],
                        assignment["parent_confidence"],
                    ))
                    development_id = conn.execute("""
                        SELECT development_id
                        FROM story_developments
                        WHERE story_id = ? AND date = ? AND development_label = ?
                    """, (
                        story_id,
                        today,
                        assignment["story_label"],
                    )).fetchone()["development_id"]

                    for a in development_articles:
                        source_id = store.source_id_for_name(conn, a.get("source"))
                        conn.execute("""
                            INSERT INTO articles (
                                id, occurrence_id, story_id, date, source_id, source,
                                title, description, url, published_at, importance
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            a["id"],
                            a.get("occurrence_id"),
                            story_id,
                            today,
                            source_id,
                            a["source"],
                            a["title"],
                            a.get("description", ""),
                            a["url"],
                            a["published_at"],
                            a["importance"],
                        ))
                        conn.execute("""
                            INSERT OR REPLACE INTO article_story_links (
                                article_id, occurrence_id, story_id, observation_id, relevance
                            )
                            VALUES (?, ?, ?, ?, ?)
                        """, (
                            str(a["id"]),
                            a.get("occurrence_id"),
                            story_id,
                            observation_id,
                            1.0,
                        ))
                        tracked.append({
                            **a,
                            "source_id": source_id,
                            "editorial_date": today,
                            "story_id": story_id,
                            "arc_id": assignment["arc_id"],
                            "arc_label": assignment["arc_label"],
                            "parent_story_id": assignment["parent_story_id"],
                            "parent_label": assignment["parent_label"],
                            "observation_id": observation_id,
                            "development_id": development_id,
                            "canonical_label": assignment["canonical_label"],
                            "development_label": assignment["story_label"],
                            "development_status": assignment["development_status"],
                            "parent_relationship": assignment["parent_relationship"],
                            "parent_confidence": assignment["parent_confidence"],
                            "trend": trend,
                            "previous_context": previous_context,
                        })

            occurrences.save_assignments(conn, tracked)
            store.sync_story_dates(conn)
    finally:
        conn.close()

    _record_story_match_verification_totals(match_decisions)
    _record_matching_audit_totals(
        same_day_decisions,
        match_decisions,
        list(arc_assignments.values()),
    )
    observability.update_run_totals(
        story_developments_saved=len(story_groups),
        story_parent_attachments=arc_attachment_count,
        story_arc_assignments=len(arc_assignments),
        story_arc_attachments=arc_attachment_count,
        story_new_arcs=new_arc_count,
        story_new_parent_arcs=new_parent_count,
        story_unmatched_new_stories=new_parent_count,
        story_arc_label_promotions=len(promoted_arc_ids),
    )
    logger.info(
        "Tracked %s stories (%s new arcs, %s new arc attachments)",
        len(parent_groups),
        new_arc_count,
        new_child_count,
    )
    return tracked
