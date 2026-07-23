from src.tracker.matching import (
    candidate_signals,
    profile_from_arc,
    profile_from_articles,
    profile_from_story,
    rare_tokens,
    retrieve_candidates,
)


def _article(
    article_id,
    title,
    label,
    *,
    description="",
    theme="Other",
    date="2026-07-22T09:00:00+00:00",
    url=None,
):
    return {
        "id": str(article_id),
        "occurrence_id": article_id,
        "title": title,
        "description": description,
        "story_label": label,
        "theme": theme,
        "importance": 3,
        "published_at": date,
        "url": url or f"https://example.com/{article_id}",
    }


def test_article_profile_preserves_source_evidence_signals():
    profile = profile_from_articles(
        [
            _article(
                1,
                "France approves social media ban for children under 15",
                "Phone-free youth",
                description="The French parliament backed the restriction.",
                theme="Tech",
            )
        ]
    )

    assert profile.label == "Phone-free youth"
    assert profile.occurrence_ids == (1,)
    assert {"france", "social", "media", "children"} <= profile.distinctive
    assert "15" in profile.numbers
    assert "france approves" in profile.phrases
    assert "French parliament" in profile.evidence_text()


def test_retrieval_finds_label_mismatch_with_grounded_anchor_and_number():
    current = profile_from_articles(
        [
            _article(
                1,
                "France teenagers face phone restrictions under age 15",
                "Phone-free youth",
                theme="Tech",
            )
        ]
    )
    candidate = profile_from_story(
        "France social media ban",
        {
            "story_id": 10,
            "canonical_label": "France social media ban",
            "theme": "Tech",
            "last_seen": "2026-07-21",
            "recent_articles": [
                {
                    "title": "France bans social media for children under 15",
                }
            ],
        },
    )

    retrieved = retrieve_candidates(current, [candidate])

    assert [item.profile.profile_id for item in retrieved] == ["story:10"]
    assert "france" in retrieved[0].signals.shared_rare_tokens
    assert "15" in retrieved[0].signals.shared_numbers


def test_retrieval_does_not_qualify_generic_topic_overlap():
    current = profile_from_articles(
        [_article(1, "Tram collides on Erasmus Bridge", "Erasmus Bridge tram crash")]
    )
    candidate = profile_from_story(
        "Bridge safety inspections",
        {
            "story_id": 20,
            "canonical_label": "Bridge safety inspections",
            "last_seen": "2026-07-21",
            "recent_articles": [
                {"title": "Inspectors review ageing motorway bridges"}
            ],
        },
    )

    signals = candidate_signals(
        current,
        candidate,
        rare=rare_tokens([current, candidate]),
    )

    assert signals.shared_distinctive_tokens == ("bridge",)
    assert retrieve_candidates(current, [candidate]) == []


def test_retrieval_accepts_exact_url_as_deterministic_candidate():
    shared_url = "https://example.com/shared"
    current = profile_from_articles(
        [_article(1, "First wording", "First label", url=shared_url)]
    )
    candidate = profile_from_articles(
        [_article(2, "Second wording", "Second label", url=shared_url)],
        profile_id="memory:2",
    )

    retrieved = retrieve_candidates(current, [candidate])

    assert retrieved[0].signals.exact_url is True
    assert retrieved[0].signals.score >= 1_000


def test_arc_profile_includes_recent_child_memory():
    profile = profile_from_arc(
        {
            "arc_id": 12,
            "canonical_label": "Tour de France crash",
            "theme": "Sports",
            "last_seen": "2026-07-21",
            "recent_stories": [
                {
                    "canonical_label": "Lipowitz Tour de France crash",
                    "summary": "A rider broke his collarbone during the race.",
                }
            ],
        }
    )

    assert profile.profile_id == "arc:12"
    assert "lipowitz" in profile.distinctive
    assert "rider" in profile.evidence_text()


def test_retrieval_limits_and_sorts_candidates_by_evidence_score():
    current = profile_from_articles(
        [_article(1, "World Matchplay darts incident", "World Matchplay incident")]
    )
    candidates = [
        profile_from_story(
            f"World Matchplay darts {index}",
            {
                "story_id": index,
                "canonical_label": f"World Matchplay darts {index}",
                "last_seen": "2026-07-21",
                "recent_articles": [{"title": "World Matchplay darts"}],
            },
        )
        for index in range(1, 8)
    ]

    retrieved = retrieve_candidates(current, candidates, limit=3)

    assert len(retrieved) == 3
    assert all(item.signals.shared_phrases for item in retrieved)
