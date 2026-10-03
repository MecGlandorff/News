import json
from copy import deepcopy

import pytest

from news import cli, trajectory


def source(
    key, text, *, day="2026-01-01", title="Dock permit dispute", publisher="Local Wire", url=None
):
    return {
        "id": key,
        "source": publisher,
        "url": url or f"https://example.test/{key}",
        "published_at": day + "T08:00:00Z",
        "title": title,
        "text": text,
    }


def snapshot(day, *articles):
    return {"day": day, "articles": list(articles)}


def ref(article, quote=None):
    return {
        "capture_id": article["capture_id"],
        "quote": article["text"] if quote is None else quote,
    }


def observation(article, *, change="new_development", comparison=(), quote=None, unresolved=None):
    return {
        "change": change,
        "summary": quote or article["text"],
        "unresolved": unresolved,
        "article_ids": [article["id"]],
        "evidence": [ref(article, quote)],
        "comparison_evidence": list(comparison),
    }


def event(*observations, event_id=None, continuity=(), title="Dock permit issued", uncertain=False):
    return {
        "event_id": event_id,
        "title": title,
        "identity_uncertain": uncertain,
        "continuity_evidence": list(continuity),
        "observations": list(observations),
    }


def decision(*events, story_id=None, title="Dock permit dispute"):
    return {"stories": [{"story_id": story_id, "title": title, "events": list(events)}]}


def fresh(payload):
    return {
        "stories": [
            decision(event(observation(article)))["stories"][0] for article in payload["articles"]
        ]
    }


def continuing(
    payload, *, change="additional_reporting", new_event=False, title="Dock permit issued"
):
    old_story = payload["stories"][0]
    old_event = old_story["events"][0]
    old = next(item for item in payload["prior_sources"] if item["event_id"] == old_event["id"])
    return decision(
        event(
            observation(
                payload["articles"][0], change=change, comparison=[] if new_event else [ref(old)]
            ),
            event_id=None if new_event else old_event["id"],
            continuity=[ref(old)],
            title=title,
        ),
        story_id=old_story["id"],
    )


@pytest.fixture
def model(monkeypatch):
    calls = []
    replies = []

    def run(task, payload, directory, **options):
        assert task == "trajectory"
        calls.append(deepcopy(payload))
        reply = replies.pop(0) if replies else fresh
        if isinstance(reply, BaseException):
            raise reply
        return reply(payload)

    monkeypatch.setattr(trajectory, "run_task", run)
    return calls, replies


def count_runs(state):
    with trajectory.connect(state / "journal.sqlite3") as db:
        return db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]


def test_distinct_development_stays_in_story_while_repeat_keeps_event(model, tmp_path):
    calls, replies = model
    first = snapshot("2026-01-01", source("permit", "The dock permit was issued."))
    result1, _ = trajectory.run(first, tmp_path)
    replies.append(continuing)
    result2, _ = trajectory.run(
        snapshot(
            "2026-01-02",
            source("report", "The dock permit was issued, the agency confirmed.", day="2026-01-02"),
        ),
        tmp_path,
    )
    replies.append(
        lambda payload: continuing(
            payload, new_event=True, change="new_development", title="Dock permit appealed"
        )
    )
    last = snapshot(
        "2026-02-20", source("appeal", "The dock permit was appealed.", day="2026-02-20")
    )
    result3, _ = trajectory.run(last, tmp_path)
    s1, s2, s3 = (item["stories"][0] for item in (result1, result2, result3))
    assert s1["id"] == s2["id"] == s3["id"]
    assert s1["events"][0]["id"] == s2["events"][0]["id"] != s3["events"][0]["id"]
    assert len(calls) == 3
    repeated, reused = trajectory.run(last, tmp_path)
    assert reused and repeated == result3 and len(calls) == 3
    text = trajectory.story(tmp_path, s1["id"])
    assert all("Observed on " + day in text for day in ("2026-01-01", "2026-01-02", "2026-02-20"))
    assert "Additional reporting" in text and "Dock permit appealed" in text
    assert "quotes differ" not in text and "new_quote_count" not in json.dumps(result3)
    saved = tmp_path / "runs" / result3["run_id"]
    assert text == (saved / "stories" / f"{s1['id']}.md").read_text()
    assert f"stories/{s1['id']}.md" in (saved / "briefing.md").read_text()


def test_full_unquoted_source_text_is_retrievable_after_quiet_gap(model, tmp_path):
    calls, replies = model
    replies.append(
        lambda payload: decision(
            event(observation(payload["articles"][0], quote="A permit was issued."))
        )
    )
    trajectory.run(
        snapshot(
            "2026-01-01",
            source(
                "origin",
                "A permit was issued. The filing identifies Project Nightjar at the waterfront.",
                title="Planning notice",
            ),
        ),
        tmp_path,
    )
    replies.append(continuing)
    trajectory.run(
        snapshot(
            "2026-03-01",
            source(
                "later",
                "Project Nightjar remains under review.",
                title="Nightjar review",
                day="2026-03-01",
            ),
        ),
        tmp_path,
    )
    prior = calls[-1]["prior_sources"]
    assert len(prior) == 1 and "Nightjar" in prior[0]["text"]
    history = calls[-1]["stories"][0]["events"][0]["history"]
    assert history[0]["evidence"][0]["quote"] == "A permit was issued."
    assert history[0]["observed_on"] == "2026-01-01"


def test_as_of_retrieval_rebuilds_index_without_future_source_leakage(model, tmp_path):
    trajectory.run(
        snapshot("2026-01-01", source("old", "Juniper permit issued.", title="Juniper")), tmp_path
    )
    trajectory.run(
        snapshot(
            "2026-03-01",
            source("future", "Orchid export was prohibited.", title="Orchid", day="2026-03-01"),
        ),
        tmp_path,
    )
    with trajectory.connect(tmp_path / "journal.sqlite3") as db:
        payload, diagnostics = trajectory.retrieve(
            db,
            snapshot(
                "2026-02-01",
                source(
                    "query",
                    "Juniper and Orchid are discussed.",
                    title="Juniper Orchid",
                    day="2026-02-01",
                ),
            ),
        )
        assert diagnostics["archive_captures"] == 1
        assert "orchid" not in diagnostics["queries"][0]["terms"]
        assert {item["id"] for item in payload["prior_sources"]} == {"old"}
        assert db.execute("SELECT COUNT(*) FROM source_search").fetchone()[0] == 1


def test_first_batch_disagreement_preserves_two_attributed_assertions(model, tmp_path):
    _, replies = model

    def conflicting(payload):
        a, b = payload["articles"]
        return decision(
            event(
                observation(a),
                observation(
                    b,
                    change="disagreement",
                    comparison=[ref(a)],
                    unresolved="How many people were injured?",
                ),
                title="Dock accident",
            )
        )

    replies.append(conflicting)
    result, _ = trajectory.run(
        snapshot(
            "2026-01-01",
            source("a", "Agency A reported ten injuries.", publisher="Agency A"),
            source(
                "b", "Agency B reported two injuries; the toll is disputed.", publisher="Agency B"
            ),
        ),
        tmp_path,
    )
    observations = result["stories"][0]["events"][0]["observations"]
    assert [item["change"] for item in observations] == ["new_development", "disagreement"]
    assert observations[1]["comparison_evidence"][0]["source"] == "Agency A"
    text = trajectory.story(tmp_path, result["stories"][0]["id"])
    assert "Unresolved disagreement" in text and "Agency A" in text and "Agency B" in text
    assert "How many people were injured?" in text


def test_correction_and_continued_disagreement_share_existing_event(model, tmp_path):
    _, replies = model
    first, _ = trajectory.run(
        snapshot(
            "2026-01-01", source("a", "Agency A reported ten injuries.", publisher="Agency A")
        ),
        tmp_path,
    )

    def updates(payload):
        a, b = payload["articles"]
        prior = payload["prior_sources"][0]
        return decision(
            event(
                observation(a, change="correction", comparison=[ref(prior)]),
                observation(b, change="disagreement", comparison=[ref(a)]),
                event_id=first["stories"][0]["events"][0]["id"],
                continuity=[ref(prior)],
                title="Dock accident",
            ),
            story_id=first["stories"][0]["id"],
        )

    replies.append(updates)
    result, _ = trajectory.run(
        snapshot(
            "2026-01-02",
            source(
                "revision",
                "Agency A corrects its toll from ten to two injuries.",
                day="2026-01-02",
                publisher="Agency A",
            ),
            source(
                "still",
                "Agency B continues to report ten injuries.",
                day="2026-01-02",
                publisher="Agency B",
            ),
        ),
        tmp_path,
    )
    value = result["stories"][0]["events"][0]
    assert value["id"] == first["stories"][0]["events"][0]["id"]
    assert [item["change"] for item in value["observations"]] == ["correction", "disagreement"]
    text = trajectory.story(tmp_path, result["stories"][0]["id"])
    assert "Reported correction" in text and "Unresolved disagreement" in text
    assert "ten to two" in text and "continues to report ten" in text


def test_retrospective_correction_compares_distinct_spans_in_one_current_capture(model, tmp_path):
    _, replies = model
    replies.append(
        lambda payload: decision(
            event(
                observation(
                    payload["articles"][0],
                    change="correction",
                    quote="We correct the toll to two.",
                    comparison=[
                        ref(payload["articles"][0], "We previously reported ten injuries.")
                    ],
                )
            )
        )
    )
    result, _ = trajectory.run(
        snapshot(
            "2026-01-01",
            source("a", "We previously reported ten injuries. We correct the toll to two."),
        ),
        tmp_path,
    )
    assert result["stories"][0]["events"][0]["observations"][0]["change"] == "correction"


def test_reused_ids_urls_and_revision_dates_keep_distinct_capture_provenance(model, tmp_path):
    calls, replies = model
    first, _ = trajectory.run(
        snapshot("2026-01-01", source("same", "Ten injuries were reported.")), tmp_path
    )
    replies.append(lambda payload: continuing(payload, change="correction"))
    later, _ = trajectory.run(
        snapshot(
            "2026-01-20",
            source("same", "Correction: two injuries were reported.", day="2026-01-20"),
        ),
        tmp_path,
    )
    old, new = calls[-1]["prior_sources"][0], calls[-1]["articles"][0]
    assert old["id"] == new["id"] and old["url"] == new["url"]
    assert old["capture_id"] != new["capture_id"]
    current = later["stories"][0]["events"][0]["observations"][0]
    assert current["evidence"][0]["published_at"].startswith("2026-01-20")
    assert current["comparison_evidence"][0]["published_at"].startswith("2026-01-01")
    assert first["stories"][0]["events"][0]["id"] == later["stories"][0]["events"][0]["id"]
    changed = deepcopy(new)
    changed["published_at"] = "2026-01-19T08:00:00Z"
    original_article = {
        key: changed[key] for key in ("id", "source", "url", "published_at", "title", "text")
    }
    assert trajectory.capture(original_article, "2026-01-20")["capture_id"] != new["capture_id"]
    invalid = continuing(calls[-1], change="correction")
    invalid["stories"][0]["events"][0]["observations"][0]["evidence"] = [ref(new, old["text"])]
    with pytest.raises(ValueError, match="exact span"):
        trajectory.validate(calls[-1], invalid)


def test_origin_latest_and_old_correction_survive_relevant_context_selection(model, tmp_path):
    calls, replies = model
    trajectory.run(
        snapshot("2026-01-01", source("a", "Dock permit covers ten buildings.")), tmp_path
    )
    replies.append(lambda payload: continuing(payload, change="correction"))
    trajectory.run(
        snapshot(
            "2026-01-02",
            source("b", "Correction: dock permit covers two buildings.", day="2026-01-02"),
        ),
        tmp_path,
    )
    replies.append(continuing)
    trajectory.run(
        snapshot("2026-01-03", source("c", "The dock permit remains in force.", day="2026-01-03")),
        tmp_path,
    )
    with trajectory.connect(tmp_path / "journal.sqlite3") as db:
        payload, diagnostics = trajectory.retrieve(
            db,
            snapshot(
                "2026-03-01", source("query", "Dock permit remains in force.", day="2026-03-01")
            ),
            hits_per_article=1,
        )
    assert {item["id"] for item in payload["prior_sources"]} == {"a", "b", "c"}
    assert {
        obs["change"] for event in payload["stories"][0]["events"] for obs in event["history"]
    } >= {"correction"}
    assert diagnostics["selection"][0]["retained_observations"] == 3
    assert len(calls) == 3


def test_prior_dated_heading_and_uncertainty_do_not_inherit_later_status(model, tmp_path):
    _, replies = model
    replies.append(
        lambda payload: decision(
            event(
                observation(payload["articles"][0], change="unclear"),
                title="Unidentified dock incident",
                uncertain=True,
            )
        )
    )
    first, _ = trajectory.run(
        snapshot("2026-01-01", source("a", "The cause of the dock incident is unknown.")), tmp_path
    )
    replies.append(
        lambda payload: continuing(payload, title="Dock incident identified as a crane collision")
    )
    trajectory.run(
        snapshot(
            "2026-01-02",
            source(
                "b",
                "Investigators identify the dock incident as a crane collision.",
                day="2026-01-02",
            ),
        ),
        tmp_path,
    )
    text = trajectory.story(tmp_path, first["stories"][0]["id"])
    earlier, later = text.split("## Observed on 2026-01-02")
    assert "### Unidentified dock incident" in earlier
    assert "Event identity uncertain" in earlier
    assert "crane collision" not in earlier
    assert "crane collision" in later and "Event identity uncertain" not in later


def test_same_day_replay_and_as_of_view_do_not_add_later_observations(model, tmp_path):
    _, replies = model
    first_input = snapshot("2026-01-01", source("a", "Dock permit issued."))
    first, _ = trajectory.run(first_input, tmp_path)
    original = (
        tmp_path / "runs" / first["run_id"] / "stories" / f"{first['stories'][0]['id']}.md"
    ).read_text()
    replies.append(continuing)
    trajectory.run(snapshot("2026-01-01", source("b", "Dock permit was issued at noon.")), tmp_path)
    trajectory.run(first_input, tmp_path)
    restored = (
        tmp_path / "runs" / first["run_id"] / "stories" / f"{first['stories'][0]['id']}.md"
    ).read_text()
    assert restored == original and "noon" not in restored
    assert "noon" in trajectory.story(tmp_path, first["stories"][0]["id"], as_of="2026-01-01")
    with pytest.raises(ValueError, match="unknown story"):
        trajectory.story(tmp_path, first["stories"][0]["id"], as_of="2025-12-31")


@pytest.mark.parametrize(
    "violation",
    [
        "missing",
        "duplicate",
        "nonexact",
        "self_comparison",
        "unknown_capture",
        "wrong_event_comparison",
    ],
)
def test_invalid_coverage_or_quote_references_leave_no_accepted_run(model, tmp_path, violation):
    _, replies = model

    def broken(payload):
        value = fresh(payload)
        obs = value["stories"][0]["events"][0]["observations"][0]
        if violation == "missing":
            value["stories"].pop()
        elif violation == "duplicate":
            value["stories"].append(deepcopy(value["stories"][0]))
        elif violation == "nonexact":
            obs["evidence"][0]["quote"] = "Invented statement"
        elif violation == "unknown_capture":
            obs["evidence"][0]["capture_id"] = "unknown"
        elif violation == "self_comparison":
            obs.update(change="correction", comparison_evidence=deepcopy(obs["evidence"]))
        else:
            obs.update(change="disagreement", comparison_evidence=[ref(payload["articles"][1])])
        return value

    replies.append(broken)
    with pytest.raises(ValueError):
        trajectory.run(
            snapshot(
                "2026-01-01", source("a", "Dock permit issued."), source("b", "A train departed.")
            ),
            tmp_path,
        )
    assert count_runs(tmp_path) == 0
    failure = list((tmp_path / "runs").glob("*/failure.json"))
    assert len(failure) == 1 and (failure[0].parent / "decision.json").exists()


@pytest.mark.parametrize(
    "violation",
    [
        "new_development",
        "missing_continuity",
        "unknown_story",
        "wrong_story",
        "uncertain_existing",
        "missing_comparison",
    ],
)
def test_invalid_identity_or_change_relationship_is_rejected(model, tmp_path, violation):
    _, replies = model
    trajectory.run(snapshot("2026-01-01", source("a", "Dock permit issued.")), tmp_path)

    def broken(payload):
        value = continuing(payload)
        story = value["stories"][0]
        item = story["events"][0]
        if violation == "new_development":
            item["observations"][0].update(change="new_development", comparison_evidence=[])
        elif violation == "missing_continuity":
            item["continuity_evidence"] = []
        elif violation == "unknown_story":
            story["story_id"] = "unknown"
        elif violation == "wrong_story":
            story["story_id"] = None
        elif violation == "uncertain_existing":
            item["identity_uncertain"] = True
        else:
            item["observations"][0]["comparison_evidence"] = []
        return value

    replies.append(broken)
    with pytest.raises(ValueError):
        trajectory.run(
            snapshot("2026-01-02", source("b", "Dock permit confirmed.", day="2026-01-02")),
            tmp_path,
        )
    assert count_runs(tmp_path) == 1


def test_exact_accepted_capture_cannot_be_reassigned_in_later_same_day_batch(model, tmp_path):
    article = source("a", "Dock permit issued.")
    trajectory.run(snapshot("2026-01-01", article), tmp_path)
    with pytest.raises(ValueError, match="cannot be reassigned"):
        trajectory.run(
            snapshot("2026-01-01", article, source("b", "Dock permit appealed.")), tmp_path
        )
    assert count_runs(tmp_path) == 1


def test_context_budget_fails_before_call_with_diagnostics_and_journal_intact(model, tmp_path):
    calls, _ = model
    trajectory.run(snapshot("2026-01-01", source("a", "Dock permit issued.")), tmp_path)
    with pytest.raises(ValueError, match="request budget"):
        trajectory.run(
            snapshot("2026-02-01", source("b", "Dock permit appealed.", day="2026-02-01")),
            tmp_path,
            max_context_chars=500,
        )
    assert len(calls) == 1 and count_runs(tmp_path) == 1
    failure = next((tmp_path / "runs").glob("*/failure.json"))
    diagnostic = json.loads((failure.parent / "retrieval.json").read_text())
    payload = json.loads((failure.parent / "input.json").read_text())
    assert diagnostic["request_chars"] == len(trajectory.canonical(payload)) > 500
    assert diagnostic["within_budget"] is False and diagnostic["selection"]


@pytest.mark.parametrize("failure", ["model", "write", "validation"])
def test_failed_run_never_changes_accepted_timeline(model, monkeypatch, tmp_path, failure):
    _, replies = model
    first, _ = trajectory.run(snapshot("2026-01-01", source("a", "Dock permit issued.")), tmp_path)
    before = trajectory.story(tmp_path, first["stories"][0]["id"])
    if failure == "model":
        replies.append(RuntimeError("deadline expired"))
    elif failure == "validation":
        replies.append(lambda payload: {"stories": []})
    else:
        original = trajectory._write_json

        def broken(path, value):
            if path.name == "result.json":
                raise OSError("disk full")
            original(path, value)

        monkeypatch.setattr(trajectory, "_write_json", broken)
    with pytest.raises((ValueError, OSError, RuntimeError)):
        trajectory.run(
            snapshot("2026-01-02", source("b", "Dock permit appealed.", day="2026-01-02")), tmp_path
        )
    assert (
        count_runs(tmp_path) == 1
        and trajectory.story(tmp_path, first["stories"][0]["id"]) == before
    )
    assert len(list((tmp_path / "runs").glob("*/failure.json"))) == 1


def test_render_escapes_untrusted_text_and_marks_capture_dates_not_event_dates(model, tmp_path):
    _, replies = model
    replies.append(
        lambda payload: decision(
            event(observation(payload["articles"][0]), title="<script> **Notice**"),
            title="[malicious](bad)",
        )
    )
    result, _ = trajectory.run(
        snapshot(
            "2026-01-20",
            source(
                "a",
                "The incident occurred on January 2. <script>alert(1)</script>",
                day="2026-01-19",
                publisher="[Fake](javascript:bad)",
            ),
        ),
        tmp_path,
    )
    text = trajectory.story(tmp_path, result["stories"][0]["id"])
    assert "## Observed on 2026-01-20" in text
    assert "occurred on January 2" in text and "published 2026-01-19" in text
    assert "<script>" not in text and "&lt;script&gt;" in text
    assert "\\[malicious\\]" in text and "\\*\\*Notice\\*\\*" in text


def test_cli_story_run_and_offline_story_view(model, tmp_path, capsys):
    path = tmp_path / "input.json"
    path.write_text(json.dumps(snapshot("2026-01-01", source("a", "Dock permit issued."))))
    state = tmp_path / "state"
    assert cli.main(["story-run", "--input", str(path), "--state", str(state)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert cli.main(["story", report["stories"][0], "--state", str(state)]) == 0
    assert "Dock permit issued" in capsys.readouterr().out
    assert len(model[0]) == 1


def test_missing_story_state_does_not_create_files(tmp_path):
    with pytest.raises(ValueError, match="no story"):
        trajectory.story(tmp_path, "unknown")
    assert list(tmp_path.iterdir()) == []


def test_chronology_and_lock_are_checked_before_model(model, tmp_path):
    calls, _ = model
    trajectory.run(snapshot("2026-02-01", source("a", "Dock permit issued.")), tmp_path)
    with pytest.raises(ValueError, match="chronological"):
        trajectory.run(snapshot("2026-01-01", source("b", "Dock permit appealed.")), tmp_path)
    with trajectory.state_lock(tmp_path), pytest.raises(ValueError, match="another run"):
        trajectory.run(snapshot("2026-03-01", source("c", "Dock permit appealed.")), tmp_path)
    assert len(calls) == 1
