"""Experimental durable stories: one accepted journal, one rebuildable full-text index."""

import contextlib
import json
import re
import sqlite3
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from news.codex import run_task
from news.domain import (
    TASKS,
    _markdown,
    _text,
    canonical,
    digest,
    valid_day,
    validate_input,
    validate_schema,
)
from news.pipeline import state_lock

APP_ID = 0x4E54524A
DEFAULT_CONTEXT_CHARS = 180_000
MAX_QUERY_TERMS = 64
CHANGES = {
    "new_development": "New development",
    "additional_reporting": "Additional reporting",
    "correction": "Reported correction",
    "disagreement": "Unresolved disagreement",
    "unclear": "Change unclear",
}
NOTICE = (
    "Story links, summaries and change judgments are model interpretations. "
    "Quotes are checked against captured text, not verified as true. "
    "Observed on dates record capture, not when an event happened."
)


def capture(article: dict, day: str) -> dict:
    """Identify a captured version, never an article ID or URL in isolation."""
    return dict(
        article, capture_id="c-" + digest({"day": day, "article": article})[:24], observed_on=day
    )


def connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path, timeout=5)
    try:
        identity = db.execute("PRAGMA application_id").fetchone()[0]
        tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if identity != APP_ID and (identity or tables):
            raise ValueError("not a story trajectory database; choose a fresh state")
        if db.execute("PRAGMA user_version").fetchone()[0] not in {0, 1}:
            raise ValueError("unsupported story trajectory database version")
        db.execute(f"PRAGMA application_id = {APP_ID}")
        db.execute("PRAGMA user_version = 1")
        db.execute("""CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
            day TEXT NOT NULL, created_at TEXT NOT NULL,
            input_json TEXT NOT NULL, result_json TEXT NOT NULL
        )""")
        db.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS source_search USING fts5(
            capture_id UNINDEXED, story_id UNINDEXED, event_id UNINDEXED,
            observed_on UNINDEXED, title, text, tokenize='unicode61 remove_diacritics 2'
        )""")
        db.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS source_terms USING fts5vocab(source_search, row)"
        )
        db.commit()
        return db
    except BaseException:
        db.close()
        raise


def project(db: sqlite3.Connection, *, as_of: str | None = None, through_run: str | None = None):
    """Rebuild the complete accepted view. No model-generated summary replaces its sources."""
    limit = db.execute("SELECT rowid FROM runs WHERE id = ?", (through_run,)).fetchone()
    if through_run is not None and limit is None:
        raise ValueError("unknown run ID")
    rows = db.execute(
        "SELECT input_json, result_json FROM runs WHERE day <= ? AND rowid <= ? ORDER BY rowid",
        (as_of or "9999-12-31", limit[0] if limit else 2**63 - 1),
    )
    sources, stories = {}, {}
    order = 0
    for raw_input, raw_result in rows:
        payload, result = json.loads(raw_input), json.loads(raw_result)
        articles = {article["id"]: article for article in payload["articles"]}
        for item in result["stories"]:
            current = stories.setdefault(
                item["id"],
                {"id": item["id"], "first_seen": result["day"], "events": {}},
            )
            current.update(title=item["title"], last_seen=result["day"])
            for event in item["events"]:
                previous = current["events"].setdefault(
                    event["id"],
                    {
                        "id": event["id"],
                        "first_seen": result["day"],
                        "observations": [],
                        "continuity_evidence": [],
                    },
                )
                previous.update(
                    title=event["title"],
                    last_seen=result["day"],
                    identity_uncertain=event["identity_uncertain"],
                )
                for reference in event["continuity_evidence"]:
                    if reference not in previous["continuity_evidence"]:
                        previous["continuity_evidence"].append(reference)
                for observation in event["observations"]:
                    previous["observations"].append(dict(observation, order=order))
                    order += 1
                    for article_id in observation["article_ids"]:
                        source = articles[article_id]
                        sources[source["capture_id"]] = dict(
                            source, story_id=item["id"], event_id=event["id"]
                        )
    return sources, stories


def _terms(text: str) -> set[str]:
    normalized = "".join(
        char
        for char in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.combining(char)
    )
    return {word for word in re.findall(r"[^\W_]+", normalized) if len(word) >= 2 or word.isdigit()}


def retrieve(db: sqlite3.Connection, snapshot: dict, *, hits_per_article: int = 3):
    """Lexical recall over all captured text; explicit, bounded selection, no age cutoff."""
    sources, stories = project(db, as_of=snapshot["day"])
    # This derived index is disposable. Rebuilding also guarantees as-of isolation.
    with db:
        db.execute("DELETE FROM source_search")
        db.executemany(
            "INSERT INTO source_search VALUES (?, ?, ?, ?, ?, ?)",
            (
                (
                    key,
                    source["story_id"],
                    source["event_id"],
                    source["observed_on"],
                    source["title"],
                    source["text"],
                )
                for key, source in sources.items()
            ),
        )
        # Merge replacement segments before querying this rebuilt snapshot.
        db.execute("INSERT INTO source_search(source_search) VALUES ('optimize')")
    frequencies = dict(db.execute("SELECT term, doc FROM source_terms"))
    articles = [capture(article, snapshot["day"]) for article in snapshot["articles"]]
    diagnostics = {"archive_captures": len(sources), "queries": [], "selection": []}
    hits = set()
    for article in articles:
        title_terms = _terms(article["title"])
        terms = (_terms(article["text"]) | title_terms) & frequencies.keys()
        ordered = sorted(
            terms, key=lambda term: (term not in title_terms, frequencies[term], -len(term), term)
        )
        selected = ordered[:MAX_QUERY_TERMS]
        query = " OR ".join('"' + term + '"' for term in selected)
        matches = (
            db.execute(
                "SELECT capture_id, bm25(source_search, 0, 0, 0, 0, 3, 1) FROM source_search "
                "WHERE source_search MATCH ? ORDER BY 2, capture_id LIMIT ?",
                (query, hits_per_article),
            ).fetchall()
            if query
            else []
        )
        # Revisions get context even when their wording changed entirely. A shared
        # URL supplies a candidate, never an automatic identity decision.
        revisions = [key for key, source in sources.items() if source["url"] == article["url"]]
        pinned = revisions[-hits_per_article:]
        if article["capture_id"] in sources:
            pinned.append(article["capture_id"])
        hits.update(key for key, _ in matches)
        hits.update(pinned)
        diagnostics["queries"].append(
            {
                "article_id": article["id"],
                "terms": selected,
                "omitted_query_terms": len(ordered) - len(selected),
                "hits": [{"capture_id": key, "score": score} for key, score in matches],
                "pinned_capture_ids": sorted(set(pinned)),
                "omitted_url_revisions": max(0, len(revisions) - hits_per_article),
            }
        )
    selected_stories = sorted({sources[key]["story_id"] for key in hits})
    context, included_sources = [], set()
    for story_id in selected_stories:
        existing = stories[story_id]
        events = list(existing["events"].values())
        origin = min(events, key=lambda event: event["observations"][0]["order"])
        latest = max(events, key=lambda event: event["observations"][-1]["order"])
        selected_events = {
            sources[key]["event_id"] for key in hits if sources[key]["story_id"] == story_id
        }
        selected_events.update([origin["id"], latest["id"]])
        chosen, story_sources, kept = [], set(), 0
        for event in events:
            history = []
            for index, observation in enumerate(event["observations"]):
                captures = {ref["capture_id"] for ref in observation["evidence"]}
                retained = (
                    (
                        event["id"] in selected_events
                        and index in {0, len(event["observations"]) - 1}
                    )
                    or bool(captures & hits)
                    or observation["change"] in {"correction", "disagreement"}
                    or observation["unresolved"] is not None
                )
                if retained:
                    history.append(
                        {key: value for key, value in observation.items() if key != "order"}
                    )
                    story_sources.update(
                        ref["capture_id"]
                        for field in ("evidence", "comparison_evidence")
                        for ref in observation[field]
                    )
            if history:
                kept += len(history)
                story_sources.update(ref["capture_id"] for ref in event["continuity_evidence"])
                chosen.append(
                    dict(
                        {key: value for key, value in event.items() if key != "observations"},
                        history=history,
                    )
                )
        # Any quoted anchor's event identity remains available, even when none of
        # its observation summaries were selected. Its full source is supplied.
        represented = {event["id"] for event in chosen}
        anchored = {sources[key]["event_id"] for key in story_sources} - represented
        for event in events:
            if event["id"] in anchored:
                chosen.append(
                    {
                        key: value
                        for key, value in event.items()
                        if key not in {"observations", "continuity_evidence"}
                    }
                    | {"history": [], "continuity_evidence": []}
                )
        context.append(
            {key: value for key, value in existing.items() if key != "events"} | {"events": chosen}
        )
        included_sources.update(story_sources)
        diagnostics["selection"].append(
            {
                "story_id": story_id,
                "origin_event_id": origin["id"],
                "latest_event_id": latest["id"],
                "event_ids": [event["id"] for event in chosen],
                "capture_ids": sorted(story_sources),
                "retained_observations": kept,
                "omitted_observations": sum(len(event["observations"]) for event in events) - kept,
            }
        )
    payload = {
        "day": snapshot["day"],
        "articles": articles,
        "stories": context,
        "prior_sources": [sources[key] for key in sorted(included_sources)],
    }
    diagnostics["request_chars"] = len(canonical(payload))
    return payload, diagnostics


def _references(items: list[dict], allowed: dict) -> set[str]:
    seen, captures = set(), set()
    for item in items:
        key, span = item["capture_id"], item["quote"]
        _text(span, "evidence quote", 2000)
        if key not in allowed or span not in allowed[key]["text"]:
            raise ValueError("evidence must quote an exact span of a supplied allowed capture")
        if (key, span) in seen:
            raise ValueError("duplicate evidence reference")
        seen.add((key, span))
        captures.add(key)
    return captures


def validate(payload: dict, decision: dict) -> None:
    """Check identity structure and provenance, not semantic truth or entailment."""
    validate_schema("trajectory", decision)
    articles = {article["id"]: article for article in payload["articles"]}
    prior = {source["capture_id"]: source for source in payload["prior_sources"]}
    stories = {story["id"]: story for story in payload["stories"]}
    events = {
        event["id"]: (story["id"], event) for story in stories.values() for event in story["events"]
    }
    assigned, reused_stories, reused_events = set(), set(), set()
    for story in decision["stories"]:
        story_id = story["story_id"]
        _text(story["title"], "story title", 160)
        if story_id is not None:
            if story_id not in stories or story_id in reused_stories:
                raise ValueError("unknown or repeated story identity")
            reused_stories.add(story_id)
        for event in story["events"]:
            event_id = event["event_id"]
            _text(event["title"], "event title", 160)
            if event_id is not None:
                if (
                    event_id not in events
                    or events[event_id][0] != story_id
                    or event_id in reused_events
                ):
                    raise ValueError(
                        "event identity must belong to its supplied story and appear once"
                    )
                if event["identity_uncertain"]:
                    raise ValueError("uncertain event identity must receive a new identity")
                reused_events.add(event_id)
            continuity = _references(event["continuity_evidence"], prior)
            if story_id is None and continuity:
                raise ValueError("a new story cannot claim prior continuity evidence")
            if story_id is not None and not continuity:
                raise ValueError("a continuing story requires prior continuity evidence")
            if any(prior[key]["story_id"] != story_id for key in continuity):
                raise ValueError("continuity evidence must belong to this story")
            if event_id is not None and any(
                prior[key]["event_id"] != event_id for key in continuity
            ):
                raise ValueError("continuity evidence must belong to this event")
            members = [
                article_id for obs in event["observations"] for article_id in obs["article_ids"]
            ]
            if (
                len(members) != len(set(members))
                or not set(members) <= articles.keys()
                or assigned.intersection(members)
            ):
                raise ValueError("articles must be known and assigned exactly once")
            assigned.update(members)
            event_current = {articles[key]["capture_id"]: articles[key] for key in members}
            comparison_sources = {
                key: source
                for key, source in prior.items()
                if event_id is not None and source["event_id"] == event_id
            } | event_current
            for key in event_current.keys() & prior.keys():
                if (prior[key]["story_id"], prior[key]["event_id"]) != (story_id, event_id):
                    raise ValueError("an accepted capture cannot be reassigned to another identity")
            for observation in event["observations"]:
                _text(observation["summary"], "observation summary", 800)
                if observation["unresolved"] is not None:
                    _text(observation["unresolved"], "unresolved question", 400)
                allowed = {
                    articles[key]["capture_id"]: articles[key] for key in observation["article_ids"]
                }
                if _references(observation["evidence"], allowed) != allowed.keys():
                    raise ValueError("every assigned article requires exact evidence")
                comparisons = _references(observation["comparison_evidence"], comparison_sources)
                evidence_pairs = {
                    (item["capture_id"], item["quote"]) for item in observation["evidence"]
                }
                if any(
                    (item["capture_id"], item["quote"]) in evidence_pairs
                    for item in observation["comparison_evidence"]
                ):
                    raise ValueError("an assertion cannot be compared with itself")
                change = observation["change"]
                if change == "new_development" and (event_id is not None or comparisons):
                    raise ValueError(
                        "a new development requires a new event and no same-event comparison"
                    )
                if (
                    change in {"additional_reporting", "correction", "disagreement"}
                    and not comparisons
                ):
                    raise ValueError("this change judgment requires same-event comparison evidence")
    if assigned != articles.keys():
        raise ValueError("every input article must be assigned exactly once")


def _materialize(payload: dict, decision: dict, run_id: str) -> dict:
    sources = {
        source["capture_id"]: source for source in payload["prior_sources"] + payload["articles"]
    }

    def evidence(items):
        return [
            dict(
                item,
                article_id=sources[item["capture_id"]]["id"],
                **{
                    key: sources[item["capture_id"]][key]
                    for key in ("source", "url", "published_at", "observed_on")
                },
            )
            for item in items
        ]

    result = {"run_id": run_id, "day": payload["day"], "stories": []}
    for story_index, story in enumerate(decision["stories"]):
        story_id = story["story_id"] or "s-" + digest([run_id, story_index])[:20]
        saved = {
            "id": story_id,
            "title": story["title"],
            "new_story": story["story_id"] is None,
            "events": [],
        }
        for event_index, event in enumerate(story["events"]):
            event_id = event["event_id"] or "e-" + digest([run_id, story_index, event_index])[:20]
            saved_event = {
                "id": event_id,
                "title": event["title"],
                "new_event": event["event_id"] is None,
                "identity_uncertain": event["identity_uncertain"],
                "continuity_evidence": evidence(event["continuity_evidence"]),
                "observations": [],
            }
            for observation_index, observation in enumerate(event["observations"]):
                saved_event["observations"].append(
                    dict(
                        observation,
                        observed_on=payload["day"],
                        run_id=run_id,
                        event_title=event["title"],
                        identity_uncertain=event["identity_uncertain"],
                        continuity_evidence=evidence(event["continuity_evidence"])
                        if observation_index == 0
                        else [],
                        evidence=evidence(observation["evidence"]),
                        comparison_evidence=evidence(observation["comparison_evidence"]),
                    )
                )
            saved["events"].append(saved_event)
        result["stories"].append(saved)
    return result


def _quoted(items: list[dict]) -> list[str]:
    lines = []
    for item in items:
        source = _markdown(" ".join(item["source"].split()))
        url = quote(item["url"], safe=":/?=&%#@+;,-._~")
        lines.extend(
            [
                f"[{source}](<{url}>) · published {item['published_at']} · observed on {item['observed_on']}",
                f"Capture `{item['capture_id']}`",
                "",
            ]
        )
        lines.extend("> " + _markdown(line) for line in item["quote"].splitlines())
        lines.append("")
    return lines


def _observation(observation: dict) -> list[str]:
    lines = [f"### {_markdown(' '.join(observation['event_title'].split()))}", ""]
    if observation["identity_uncertain"]:
        lines.extend(["**Event identity uncertain; kept separate.**", ""])
    lines.extend(
        [
            f"**{CHANGES[observation['change']]}** — {_markdown(' '.join(observation['summary'].split()))}",
            "",
        ]
    )
    if observation["unresolved"]:
        lines.extend(
            [
                f"**Unresolved in this reporting:** {_markdown(' '.join(observation['unresolved'].split()))}",
                "",
            ]
        )
    lines.extend(_quoted(observation["evidence"]))
    if observation["comparison_evidence"]:
        lines.extend(["Compared assertion (preserved with its attribution):", ""])
        lines.extend(_quoted(observation["comparison_evidence"]))
    shown = {
        (item["capture_id"], item["quote"])
        for field in ("evidence", "comparison_evidence")
        for item in observation[field]
    }
    anchors = [
        item
        for item in observation["continuity_evidence"]
        if (item["capture_id"], item["quote"]) not in shown
    ]
    if anchors:
        lines.extend(["Earlier source supporting this story/event link:", ""])
        lines.extend(_quoted(anchors))
    return lines


def render_daily(result: dict) -> str:
    lines = [f"# News — observed on {result['day']}", "", NOTICE, ""]
    for story_item in result["stories"]:
        title = _markdown(" ".join(story_item["title"].split()))
        lines.extend([f"## [{title}](stories/{story_item['id']}.md)", ""])
        for event in story_item["events"]:
            for observation in event["observations"]:
                lines.extend(_observation(observation))
    return "\n".join(lines).rstrip() + "\n"


def render_story(value: dict) -> str:
    lines = [
        f"# {_markdown(' '.join(value['title'].split()))}",
        "",
        NOTICE,
        "",
        f"First observed {value['first_seen']} · latest observation {value['last_seen']}",
        "",
    ]
    ordered = sorted(
        (
            observation
            for event in value["events"].values()
            for observation in event["observations"]
        ),
        key=lambda item: item["order"],
    )
    day = None
    for observation in ordered:
        if observation["observed_on"] != day:
            day = observation["observed_on"]
            lines.extend([f"## Observed on {day}", ""])
        lines.extend(_observation(observation))
    return "\n".join(lines).rstrip() + "\n"


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _outputs(directory: Path, result: dict, stories: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "stories").mkdir(exist_ok=True)
    _write_json(directory / "result.json", result)
    (directory / "briefing.md").write_text(render_daily(result), encoding="utf-8")
    for item in result["stories"]:
        (directory / "stories" / f"{item['id']}.md").write_text(
            render_story(stories[item["id"]]), encoding="utf-8"
        )


def run(
    snapshot: dict,
    state: Path,
    *,
    timeout: float = 180,
    executable: str = "codex",
    max_context_chars: int = DEFAULT_CONTEXT_CHARS,
    hits_per_article: int = 3,
) -> tuple[dict, bool]:
    snapshot = validate_input(snapshot)
    state = Path(state)
    if not 1 <= timeout <= 1800:
        raise ValueError("timeout must be between 1 and 1800 seconds")
    if type(max_context_chars) is not int or not 1 <= max_context_chars <= 240_000:
        raise ValueError("max_context_chars must be between 1 and 240000")
    if type(hits_per_article) is not int or not 1 <= hits_per_article <= 10:
        raise ValueError("hits_per_article must be between 1 and 10")
    files = [
        TASKS / "trajectory.md",
        TASKS / "trajectory.schema.json",
        Path(__file__),
        Path(__file__).with_name("domain.py"),
        Path(__file__).with_name("codex.py"),
    ]
    fingerprint = digest(
        {
            "snapshot": snapshot,
            "files": {path.name: path.read_text() for path in files},
            "model": "gpt-6-astra",
            "reasoning": "medium",
            "max_context_chars": max_context_chars,
            "hits_per_article": hits_per_article,
        }
    )
    with state_lock(state), contextlib.closing(connect(state / "journal.sqlite3")) as db:
        saved = db.execute(
            "SELECT result_json FROM runs WHERE fingerprint = ?", (fingerprint,)
        ).fetchone()
        if saved:
            result = json.loads(saved[0])
            _, stories = project(db, through_run=result["run_id"])
            _outputs(state / "runs" / result["run_id"], result, stories)
            return result, True
        latest = db.execute("SELECT MAX(day) FROM runs").fetchone()[0]
        if latest and snapshot["day"] < latest:
            raise ValueError("new runs must be chronological; use separate state for backtests")
        run_id = uuid.uuid4().hex
        directory = state / "runs" / run_id
        directory.mkdir(parents=True)
        try:
            payload, diagnostics = retrieve(db, snapshot, hits_per_article=hits_per_article)
            diagnostics["max_context_chars"] = max_context_chars
            diagnostics["within_budget"] = diagnostics["request_chars"] <= max_context_chars
            _write_json(directory / "input.json", payload)
            _write_json(directory / "retrieval.json", diagnostics)
            if not diagnostics["within_budget"]:
                raise ValueError(
                    "retrieved context exceeds request budget; use a smaller input batch"
                )
            decision = run_task(
                "trajectory", payload, directory / "model", timeout=timeout, executable=executable
            )
            _write_json(directory / "decision.json", decision)
            validate(payload, decision)
            result = _materialize(payload, decision, run_id)
            # Insert and render inside one transaction. No accepted observation
            # survives a model, validation, artifact or commit failure.
            with db:
                db.execute(
                    "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        fingerprint,
                        snapshot["day"],
                        datetime.now(timezone.utc).isoformat(),
                        canonical(payload),
                        canonical(result),
                    ),
                )
                _, stories = project(db, through_run=run_id)
                _outputs(directory, result, stories)
        except BaseException as exc:
            try:
                _write_json(
                    directory / "failure.json", {"error": str(exc), "type": type(exc).__name__}
                )
            except OSError:
                pass
            exc.add_note(f"Run artifacts: {directory}")
            raise
        return result, False


def story(state: Path, story_id: str, *, as_of: str | None = None) -> str:
    """Render all accepted dated observations, optionally as known on a capture day."""
    if as_of is not None:
        valid_day(as_of)
    path = Path(state) / "journal.sqlite3"
    if not path.is_file():
        raise ValueError("no story trajectory state exists here")
    with contextlib.closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA application_id").fetchone()[0] != APP_ID:
            raise ValueError("not a story trajectory database")
        _, stories = project(db, as_of=as_of)
        if story_id not in stories:
            raise ValueError("unknown story ID at this observation date")
        return render_story(stories[story_id])
