import json
import sqlite3
from copy import deepcopy

import pytest

from news import trajectory
from news.codex import CodexError


def article(key, text, *, title="Harbor permit case", day="2026-01-01"):
    return {
        "id": key,
        "source": "Local Wire",
        "url": f"https://example.test/{key}",
        "published_at": day + "T08:00:00Z",
        "title": title,
        "text": text,
    }


def snapshot(day, *articles):
    return {"day": day, "articles": list(articles)}


def reference(source):
    return {
        "capture_id": source["capture_id"],
        "field": "text",
        "quote": source["text"].split("\n", 1)[0],
    }


def proposal(payload):
    return {
        "stories": [
            {
                "story_id": None,
                "title": source["title"],
                "events": [
                    {
                        "event_id": None,
                        "title": source["title"],
                        "identity_uncertain": False,
                        "continuity_evidence": [],
                        "observations": [
                            {
                                "change": "new_development",
                                "summary": source["text"].split("\n", 1)[0],
                                "unresolved": None,
                                "article_ids": [source["id"]],
                                "evidence": [reference(source)],
                                "comparison_evidence": [],
                            }
                        ],
                    }
                ],
            }
            for source in payload["articles"]
        ]
    }


def continue_story(payload):
    value = proposal(payload)
    existing = payload["stories"][0]
    value["stories"][0]["story_id"] = existing["id"]
    value["stories"][0]["events"][0]["continuity_evidence"] = [
        reference(payload["prior_sources"][0])
    ]
    return value


def review(decision, *, verdict="supported", reason="The reports concern this permit case."):
    return {
        "stories": [
            {"story_index": index, "verdict": verdict, "reason": reason}
            for index, _ in enumerate(decision["stories"])
        ]
    }


@pytest.fixture
def model(monkeypatch):
    state = {"calls": [], "trajectory": [], "coherence": []}

    def fake(task, payload, directory, **options):
        assert task in {"trajectory", "coherence"}
        state["calls"].append(
            {"task": task, "payload": deepcopy(payload), "directory": directory, **options}
        )
        if state[task]:
            response = state[task].pop(0)
            if isinstance(response, BaseException):
                raise response
            return response(payload) if callable(response) else deepcopy(response)
        return proposal(payload) if task == "trajectory" else review(payload["decision"])

    monkeypatch.setattr(trajectory, "run_task", fake)
    return state


def journal_rows(state):
    with sqlite3.connect(state / "journal.sqlite3") as db:
        return db.execute("SELECT * FROM runs ORDER BY rowid").fetchall()


def files(directory):
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in directory.rglob("*")
        if path.is_file()
    }


def failed_run(state):
    failures = list((state / "runs").glob("*/failure.json"))
    assert len(failures) == 1
    return failures[0].parent


def read_json(path):
    return json.loads(path.read_text())


@pytest.mark.parametrize("verdict", ["unsupported", "uncertain"])
def test_reviewer_rejection_preserves_journal_outputs_and_audit(model, tmp_path, verdict):
    first, _ = trajectory.run(
        snapshot("2026-01-01", article("permit", "The harbor dock permit was issued.")), tmp_path
    )
    old_directory = tmp_path / "runs" / first["run_id"]
    old_rows, old_files = journal_rows(tmp_path), files(old_directory)
    old_story = trajectory.story(tmp_path, first["stories"][0]["id"])
    reason = "The painting recovery and dock permit have no supported connection."
    model["trajectory"].append(continue_story)
    model["coherence"].append(
        lambda payload: review(payload["decision"], verdict=verdict, reason=reason)
    )
    with pytest.raises(ValueError, match="story coherence review rejected the batch"):
        trajectory.run(
            snapshot(
                "2026-01-02",
                article("painting", "A stolen painting was found in the harbor.", day="2026-01-02"),
            ),
            tmp_path,
        )
    assert journal_rows(tmp_path) == old_rows
    assert files(old_directory) == old_files
    assert trajectory.story(tmp_path, first["stories"][0]["id"]) == old_story
    rejected = failed_run(tmp_path)
    stored_decision = read_json(rejected / "decision.json")
    assert stored_decision == model["calls"][-1]["payload"]["decision"]
    assert read_json(rejected / "review-input.json") == model["calls"][-1]["payload"]
    assert read_json(rejected / "review.json") == review(
        stored_decision, verdict=verdict, reason=reason
    )
    failure = read_json(rejected / "failure.json")
    assert failure["type"] == "ValueError" and verdict in failure["error"]
    assert reason in failure["error"]
    assert read_json(rejected / "input.json")["articles"][0]["id"] == "painting"
    assert not (rejected / "result.json").exists()
    assert not (rejected / "briefing.md").exists()
    assert not (rejected / "stories").exists()


@pytest.mark.parametrize(
    "violation",
    [
        "missing_index",
        "string_index",
        "boolean_index",
        "missing_story",
        "duplicate_index",
        "extra_index",
        "invalid_verdict",
        "blank_reason",
    ],
)
def test_malformed_or_incomplete_review_cannot_accept_a_batch(model, tmp_path, violation):
    def malformed(payload):
        value = review(payload["decision"])
        first = value["stories"][0]
        if violation == "missing_index":
            del first["story_index"]
        elif violation == "string_index":
            first["story_index"] = "0"
        elif violation == "boolean_index":
            first["story_index"] = False
        elif violation == "missing_story":
            value["stories"].pop()
        elif violation == "duplicate_index":
            value["stories"][1]["story_index"] = 0
        elif violation == "extra_index":
            value["stories"].append(dict(first, story_index=2))
        elif violation == "invalid_verdict":
            first["verdict"] = "approved"
        else:
            first["reason"] = " \n\t"
        return value

    model["coherence"].append(malformed)
    with pytest.raises(ValueError):
        trajectory.run(
            snapshot(
                "2026-01-01",
                article("permit", "The harbor dock permit was issued."),
                article("market", "A market opened in the city."),
            ),
            tmp_path,
        )
    assert journal_rows(tmp_path) == []
    directory = failed_run(tmp_path)
    assert (directory / "decision.json").is_file()
    assert read_json(directory / "review.json") == malformed(model["calls"][-1]["payload"])
    assert read_json(directory / "failure.json")["type"] == "ValueError"
    assert [call["task"] for call in model["calls"]] == ["trajectory", "coherence"]


def test_coherence_coverage_accepts_every_story_in_any_order():
    decision = {"stories": [{}, {}]}
    value = review(decision)
    value["stories"].reverse()
    trajectory.validate_coherence(decision, value)


@pytest.mark.parametrize("violation", ["missing_article", "invented_quote"])
def test_invalid_proposal_fails_before_reviewer_is_called(model, tmp_path, violation):
    def invalid(payload):
        value = proposal(payload)
        if violation == "missing_article":
            value["stories"] = []
        else:
            value["stories"][0]["events"][0]["observations"][0]["evidence"][0]["quote"] = (
                "A claim absent from the captured source."
            )
        return value

    model["trajectory"].append(invalid)
    with pytest.raises(ValueError):
        trajectory.run(
            snapshot("2026-01-01", article("permit", "The harbor dock permit was issued.")),
            tmp_path,
        )
    assert [call["task"] for call in model["calls"]] == ["trajectory"]
    assert journal_rows(tmp_path) == []
    directory = failed_run(tmp_path)
    assert (directory / "decision.json").exists()
    assert not (directory / "review-input.json").exists()
    assert not (directory / "review.json").exists()


def test_reviewer_timeout_preserves_prior_acceptance_and_partial_review_artifacts(model, tmp_path):
    first, _ = trajectory.run(
        snapshot("2026-01-01", article("permit", "The harbor dock permit was issued.")), tmp_path
    )
    old_directory = tmp_path / "runs" / first["run_id"]
    before_rows, before_files = journal_rows(tmp_path), files(old_directory)

    def timeout(payload):
        directory = model["calls"][-1]["directory"]
        directory.mkdir()
        (directory / "events.jsonl").write_text('{"type":"thread.started"}\n')
        raise CodexError("Codex timed out during coherence review")

    model["coherence"].append(timeout)
    with pytest.raises(CodexError, match="timed out"):
        trajectory.run(
            snapshot(
                "2026-01-02", article("appeal", "The dock permit was appealed.", day="2026-01-02")
            ),
            tmp_path,
        )
    assert journal_rows(tmp_path) == before_rows and files(old_directory) == before_files
    directory = failed_run(tmp_path)
    assert (directory / "decision.json").is_file()
    assert (directory / "review-input.json").is_file()
    assert (directory / "review" / "events.jsonl").read_text() == '{"type":"thread.started"}\n'
    assert not (directory / "review.json").exists()
    assert read_json(directory / "failure.json")["type"] == "CodexError"


def test_reviewer_gets_only_remaining_shared_batch_timeout(model, monkeypatch, tmp_path):
    clock = {"now": 100.0}
    monkeypatch.setattr(trajectory.time, "monotonic", lambda: clock["now"])

    def author(payload):
        clock["now"] += 7.25
        return proposal(payload)

    def reviewer(payload):
        clock["now"] += 1.5
        return review(payload["decision"])

    model["trajectory"].append(author)
    model["coherence"].append(reviewer)
    _, reused = trajectory.run(
        snapshot("2026-01-01", article("permit", "The harbor dock permit was issued.")),
        tmp_path,
        timeout=10,
    )
    assert reused is False and len(journal_rows(tmp_path)) == 1
    assert [call["timeout"] for call in model["calls"]] == [10, 2.75]


@pytest.mark.parametrize("elapsed", [10.0, 10.5])
def test_exhausted_shared_deadline_prevents_reviewer_and_acceptance(
    model, monkeypatch, tmp_path, elapsed
):
    clock = {"now": 100.0}
    monkeypatch.setattr(trajectory.time, "monotonic", lambda: clock["now"])

    def author(payload):
        clock["now"] += elapsed
        return proposal(payload)

    model["trajectory"].append(author)
    with pytest.raises(ValueError, match="deadline exhausted before story coherence review"):
        trajectory.run(
            snapshot("2026-01-01", article("permit", "The harbor dock permit was issued.")),
            tmp_path,
            timeout=10,
        )
    assert journal_rows(tmp_path) == []
    assert [call["task"] for call in model["calls"]] == ["trajectory"]
    directory = failed_run(tmp_path)
    assert (directory / "decision.json").is_file()
    assert (directory / "review-input.json").is_file()
    assert not (directory / "review.json").exists()


def test_late_supported_review_is_retained_but_cannot_accept(model, monkeypatch, tmp_path):
    clock = {"now": 100.0}
    monkeypatch.setattr(trajectory.time, "monotonic", lambda: clock["now"])

    def reviewer(payload):
        clock["now"] += 10.1
        return review(payload["decision"])

    model["coherence"].append(reviewer)
    with pytest.raises(ValueError, match="deadline exhausted during story coherence review"):
        trajectory.run(
            snapshot("2026-01-01", article("permit", "The harbor dock permit was issued.")),
            tmp_path,
            timeout=10,
        )
    assert journal_rows(tmp_path) == []
    directory = failed_run(tmp_path)
    assert read_json(directory / "review.json")["stories"][0]["verdict"] == "supported"
    assert read_json(directory / "failure.json")["type"] == "ValueError"


def seed_history(model, state, *, middle_tail=""):
    def grouped(payload):
        value = proposal(payload)
        related, unrelated = value["stories"][:3], value["stories"][3:]
        related[0]["title"] = "Alder permit case"
        related[0]["events"] = [item["events"][0] for item in related]
        value["stories"] = [related[0], *unrelated]
        return value

    sources = [
        article(
            "a-origin",
            "Case Alder began with an application for dock permits.",
            title="Alder dock permit application",
        ),
        article(
            "b-middle",
            "Proceeding Alder included a site survey at the marsh.\n" + middle_tail,
            title="Alder marsh site survey",
        ),
        article(
            "c-latest",
            "The Zephyr appeal in the Alder case reached the tribunal.",
            title="Zephyr appeal tribunal",
        ),
        article(
            "z-unrelated",
            "Mallow county announced a cycling festival.",
            title="Mountain cycling festival",
        ),
    ]
    model["trajectory"].append(grouped)
    result, _ = trajectory.run(snapshot("2026-01-01", *sources), state)
    return result, sources


def ruling():
    return snapshot(
        "2026-01-02",
        article(
            "d-ruling",
            "The tribunal issued its ruling on the Zephyr appeal.",
            title="Zephyr appeal tribunal ruling",
            day="2026-01-02",
        ),
    )


def test_reviewer_gets_all_reused_story_history_and_original_sources_beyond_retrieval(
    model, tmp_path
):
    first, original = seed_history(model, tmp_path, middle_tail="An unquoted survey detail.")
    model["trajectory"].append(continue_story)
    trajectory.run(ruling(), tmp_path, hits_per_article=1)
    author_input, review_input = [call["payload"] for call in model["calls"][-2:]]
    assert {item["id"] for item in author_input["prior_sources"]} == {"a-origin", "c-latest"}
    assert len(author_input["stories"][0]["events"]) == 2
    reviewed = review_input["input"]
    assert reviewed["day"] == author_input["day"]
    assert reviewed["articles"] == author_input["articles"]
    assert {item["id"] for item in reviewed["prior_sources"]} == {
        "a-origin",
        "b-middle",
        "c-latest",
    }
    assert len(reviewed["stories"]) == 1
    events = reviewed["stories"][0]["events"]
    assert {item["id"] for item in events} == {item["id"] for item in first["stories"][0]["events"]}
    assert all(item["observations"] for item in events)
    for source in reviewed["prior_sources"]:
        captured = next(item for item in original if item["id"] == source["id"])
        assert {key: source[key] for key in captured} == captured
    assert any("An unquoted survey detail." in item["text"] for item in reviewed["prior_sources"])
    assert review_input["decision"]["stories"][0]["story_id"] == first["stories"][0]["id"]


def test_full_history_review_budget_failure_preserves_prior_journal_and_inputs(model, tmp_path):
    first, _ = seed_history(model, tmp_path, middle_tail="archived survey detail " * 650)
    old_directory = tmp_path / "runs" / first["run_id"]
    old_rows, old_files = journal_rows(tmp_path), files(old_directory)
    model["trajectory"].append(continue_story)
    with pytest.raises(ValueError, match="story coherence review exceeds request budget"):
        trajectory.run(ruling(), tmp_path, hits_per_article=1, max_context_chars=12_000)
    assert journal_rows(tmp_path) == old_rows and files(old_directory) == old_files
    assert [call["task"] for call in model["calls"]] == ["trajectory", "coherence", "trajectory"]
    directory = failed_run(tmp_path)
    retrieved = read_json(directory / "input.json")
    complete = read_json(directory / "review-input.json")
    assert len(trajectory.canonical(retrieved)) <= 12_000
    assert len(trajectory.canonical(complete)) > 12_000
    assert {item["id"] for item in retrieved["prior_sources"]} == {"a-origin", "c-latest"}
    assert "b-middle" in {item["id"] for item in complete["input"]["prior_sources"]}
    assert (directory / "decision.json").is_file()
    assert not (directory / "review.json").exists()
    assert not (directory / "result.json").exists()
