import pytest

from news import trajectory
from news.domain import canonical, validate_input


def snapshot(day, text, *, article_id="one"):
    return validate_input(
        {
            "day": day,
            "articles": [
                {
                    "id": article_id,
                    "source": "Test",
                    "title": text,
                    "text": text,
                    "url": f"https://example.test/{article_id}",
                    "published_at": day + "T12:00:00Z",
                }
            ],
        }
    )


def accept(db, snapshot, *, title, run_id, story_id=None, event_id=None):
    payload, _ = trajectory.retrieve(db, snapshot)
    article = payload["articles"][0]
    continuity = []
    if story_id is not None:
        prior = next(s for s in payload["prior_sources"] if s["story_id"] == story_id)
        continuity = [{"capture_id": prior["capture_id"], "quote": prior["text"]}]
    decision = {
        "stories": [
            {
                "story_id": story_id,
                "title": title,
                "events": [
                    {
                        "event_id": event_id,
                        "title": title,
                        "identity_uncertain": False,
                        "continuity_evidence": continuity,
                        "observations": [
                            {
                                "article_ids": [article["id"]],
                                "summary": title,
                                "change": "new_development",
                                "unresolved": None,
                                "evidence": [
                                    {"capture_id": article["capture_id"], "quote": article["text"]}
                                ],
                                "comparison_evidence": [],
                            }
                        ],
                    }
                ],
            }
        ]
    }
    trajectory.validate(payload, decision)
    result = trajectory._materialize(payload, decision, run_id)
    with db:
        db.execute(
            "INSERT INTO runs VALUES (?,?,?,?,?,?)",
            (
                run_id,
                run_id,
                snapshot["day"],
                snapshot["day"],
                canonical(payload),
                canonical(result),
            ),
        )
    return article, result


@pytest.mark.parametrize(
    "label,current_text",
    [
        ("Bridge permit approved", "Bridge construction begins."),
        ("Jupiter rocket launch", "Jupiter mission launched."),
    ],
)
def test_generated_labels_retrieve_source_without_becoming_evidence(tmp_path, label, current_text):
    db = trajectory.connect(tmp_path / "journal.sqlite3")
    original, result = accept(
        db,
        snapshot("2026-05-01", "Brugvergunning verleend."),
        title=label,
        run_id="old",
    )
    current = snapshot("2026-05-20", current_text, article_id="two")
    payload, diagnostics = trajectory.retrieve(db, current)
    assert diagnostics["queries"][0]["hits"][0]["capture_id"] == original["capture_id"]
    assert len(payload["stories"]) == 1
    prior = payload["prior_sources"][0]
    assert prior["title"] == prior["text"] == "Brugvergunning verleend."
    assert prior["capture_id"] == original["capture_id"]
    story_id = result["stories"][0]["id"]
    forged = {
        "stories": [
            {
                "story_id": story_id,
                "title": "Bridge work",
                "events": [
                    {
                        "event_id": None,
                        "title": "Construction",
                        "identity_uncertain": False,
                        "continuity_evidence": [
                            {
                                "capture_id": original["capture_id"],
                                "quote": label,
                            }
                        ],
                        "observations": [
                            {
                                "article_ids": ["two"],
                                "summary": "Construction begins.",
                                "change": "new_development",
                                "unresolved": None,
                                "evidence": [
                                    {
                                        "capture_id": payload["articles"][0]["capture_id"],
                                        "quote": current_text,
                                    }
                                ],
                                "comparison_evidence": [],
                            }
                        ],
                    }
                ],
            }
        ]
    }
    with pytest.raises(ValueError, match="exact span"):
        trajectory.validate(payload, forged)
    # Exact source quotes are still not a semantic connection check: with the
    # misleading Jupiter label, this structurally valid connection is wrong.
    forged["stories"][0]["events"][0]["continuity_evidence"][0]["quote"] = original["text"]
    trajectory.validate(payload, forged)
    db.close()


def test_future_generated_labels_do_not_leak_into_earlier_search(tmp_path):
    db = trajectory.connect(tmp_path / "journal.sqlite3")
    _, result = accept(
        db,
        snapshot("2026-05-01", "Brugvergunning verleend."),
        title="Bridge permit approved",
        run_id="old",
    )
    accept(
        db,
        snapshot("2026-05-20", "Bridge tunnelplan toegevoegd.", article_id="two"),
        title="Tunnel replaces bridge",
        run_id="future",
        story_id=result["stories"][0]["id"],
    )
    current = snapshot("2026-05-10", "Tunnel review.", article_id="three")
    payload, diagnostics = trajectory.retrieve(db, current)
    assert diagnostics["archive_captures"] == 1
    assert "tunnel" not in diagnostics["queries"][0]["terms"]
    assert payload["stories"] == []
    db.close()
