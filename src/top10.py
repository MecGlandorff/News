import json
from collections import defaultdict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from src.config import BRIEFING_MODEL
from src.llm import get_openai_client, parse_json_object
from src.tracker import save_observation_memory

BRIEFINGS_DIR = Path("briefings")
THEME_ORDER = ["Geopolitics & War", "USA Politics", "Dutch Politics", "Economy", "Tech", "Climate", "Science", "Sports", "Other"]
POLITICS_THEMES = {"Geopolitics & War", "USA Politics", "Dutch Politics"}
SECTION_EXCLUDED_THEMES = {"Sports", "Tech", "Science"}
LEAD_EXCLUDED_THEMES = {"Sports"}
LOW_INTEREST_LEAD_THEMES = {"Tech", "Science"}
LOW_INTEREST_KEYWORDS = {
    "celebrity",
    "entertainment",
    "film",
    "ice spice",
    "mcdonald",
    "music",
    "showbiz",
    "tv",
    "video",
}

TREND_SCORE = {"up": 2, "new": 1, "steady": 0, "down": -1}
TREND_ICON  = {"new": "NEW STORY", "up": "COVERAGE INCREASING", "steady": "COVERAGE STEADY", "down": "COVERAGE DECREASING"}

BRIEFING_PROMPT = """You are writing a daily news briefing for an informed reader who wants real depth.

For each story, write 2-3 solid paragraphs in English (150-250 words) that:
- Open with what happened and the immediate significance
- Explain the broader context — why this story matters, what led to it, who is affected
- Close with what to watch next — unresolved tensions, upcoming decisions, or likely consequences
- Synthesize across all sources provided, surfacing different angles where they exist
- Are factual, neutral, and written for an intelligent adult — no fluff, no filler
- Use the supplied reported_at timestamps to keep chronology clear where timing matters
- If previous_context is supplied, use it only for background and continuity. Today's articles are the authority for what is new today; do not present previous context as fresh reporting
- Do not invent source URLs; URLs are supplied separately in the output
- If structured claims are supplied, use them as the primary factual grounding for the briefing and delta_summary. Do not assert factual details that are unsupported by either supplied claims or today's article metadata

For each story, also write one delta_summary sentence that answers: what is materially new in today's reporting compared with previous_context?
- If previous_context is supplied, compare today's articles against it and mention only the new turn, escalation, clarification, or lack of major change
- If previous_context is not supplied, write exactly: First detected today.
- Do not summarize the whole story in delta_summary

Return a JSON object with key "briefings": array of {canonical_label, delta_summary, briefing}.
Base current developments on today's article titles and descriptions. Use previous_context, when supplied, only for background."""


def _score(story):
    # Importance leads, but broad pickup should beat one-source opinion pieces.
    return story["importance_avg"] * 100 + story["source_count"] * 12 + TREND_SCORE.get(story["trend"], 0)


def _parse_reported_at(value):
    try:
        parsed = parsedate_to_datetime(value)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_reported_at(value):
    parsed = _parse_reported_at(value)
    if parsed:
        return parsed.strftime("%Y-%m-%d %H:%M UTC")
    return value or "unknown time"


def _latest_reported_at(articles):
    parsed = [_parse_reported_at(a.get("published_at")) for a in articles]
    parsed = [p for p in parsed if p]
    if not parsed:
        return "unknown time"
    return max(parsed).strftime("%Y-%m-%d %H:%M UTC")


def _source_lines(articles):
    def sort_key(article):
        return _parse_reported_at(article.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc)

    lines = ["Sources:"]
    for a in sorted(articles, key=sort_key, reverse=True):
        reported = _format_reported_at(a.get("published_at"))
        title = a.get("title", "Untitled")
        url = a.get("url")
        if url:
            lines.append(f"- {a['source']} — reported {reported} — [{title}]({url})")
        else:
            lines.append(f"- {a['source']} — reported {reported} — {title}")
    return lines


def _evidence_lines(story_id):
    """Return formatted evidence lines for a story, or [] if none."""
    if story_id is None:
        return []
    from src.claims import get_claims_for_story
    claims = [
        claim for claim in get_claims_for_story(story_id)
        if claim.get("evidence_span")
    ]
    if not claims:
        return []
    lines = ["", "### Evidence"]
    for c in claims[:8]:
        span = c["evidence_span"]
        pct  = int((c["confidence"] or 0.5) * 100)
        source = c.get("source") or "Unknown source"
        url = c.get("url")
        if url:
            source_ref = f"[{source}]({url})"
        else:
            source_ref = source
        lines.append(f'- `{c["claim_type"]}` — {source_ref} — "{span}" _({pct}%)_')
    return lines


def _aggregate(tracked):
    """Group tracked articles by canonical story, compute scores and theme metadata."""
    stories = defaultdict(lambda: {
        "articles": [],
        "sources": set(),
        "importance_sum": 0,
        "theme_counts": defaultdict(int),
        "previous_context": None,
        "observation_ids": set(),
    })

    for a in tracked:
        label = a.get("canonical_label", a["story_label"])
        theme = a["theme"]
        stories[label]["articles"].append(a)
        stories[label]["sources"].add(a["source"])
        stories[label]["importance_sum"] += a["importance"]
        stories[label]["theme_counts"][theme] += 1
        if a.get("previous_context") and not stories[label]["previous_context"]:
            stories[label]["previous_context"] = a["previous_context"]
        if a.get("observation_id"):
            stories[label]["observation_ids"].add(a["observation_id"])

    result = []
    for label, data in stories.items():
        articles = data["articles"]
        themes = set(data["theme_counts"])
        primary_theme = max(
            themes,
            key=lambda theme: (
                data["theme_counts"][theme],
                sum(a["importance"] for a in articles if a["theme"] == theme),
            ),
        )
        result.append({
            "canonical_label": label,
            "theme":           primary_theme,
            "themes":          themes,
            "trend":           articles[0].get("trend", "steady"),
            "source_count":    len(data["sources"]),
            "importance_avg":  data["importance_sum"] / len(articles),
            "previous_context": data["previous_context"] or {},
            "observation_ids": sorted(data["observation_ids"]),
            "story_id":        articles[0].get("story_id"),
            "articles":        articles,
        })
    return result


def _theme_summary(story):
    themes = [theme for theme in THEME_ORDER if theme in story["themes"]]
    return " / ".join(themes)


def _is_lead_candidate(story):
    if story["themes"] & LEAD_EXCLUDED_THEMES:
        return False
    if _has_low_interest_keywords(story):
        return False
    if story["themes"] & LOW_INTEREST_LEAD_THEMES:
        return story["importance_avg"] >= 4.5 and story["source_count"] >= 3
    return True


def _has_low_interest_keywords(story):
    text = " ".join(
        [story["canonical_label"]]
        + [a.get("title", "") for a in story["articles"]]
        + [a.get("description", "") for a in story["articles"]]
    ).lower()
    return any(keyword in text for keyword in LOW_INTEREST_KEYWORDS)


def _is_other_important(story):
    if "Other" not in story["themes"] or _has_low_interest_keywords(story):
        return False
    return story["importance_avg"] >= 2.5 or story["source_count"] >= 2


def _section_candidates(stories, predicate, used_labels, limit):
    candidates = [
        story for story in stories
        if story["canonical_label"] not in used_labels
        and not (story["themes"] & SECTION_EXCLUDED_THEMES)
        and predicate(story)
    ]
    return sorted(candidates, key=_score, reverse=True)[:limit]


def _claims_for_prompt(story):
    from src.claims import get_claims_for_story
    article_by_id = {str(article.get("id")): article for article in story.get("articles", [])}
    claims = []
    for claim in get_claims_for_story(story.get("story_id"))[:12]:
        article = article_by_id.get(str(claim.get("article_id")), {})
        claims.append({
            "claim_text": claim.get("claim_text", ""),
            "claim_type": claim.get("claim_type", ""),
            "evidence_span": claim.get("evidence_span", ""),
            "confidence": claim.get("confidence"),
            "source": claim.get("source") or article.get("source", ""),
            "article_title": claim.get("article_title") or article.get("title", ""),
            "url": claim.get("url") or article.get("url", ""),
        })
    return claims


def _get_briefings(stories, include_evidence=False):
    """One GPT call for all stories across all sections."""
    if not stories:
        return {}

    client = get_openai_client()

    items = []
    for s in stories:
        item = {
            "canonical_label": s["canonical_label"],
            "articles": [
                {
                    "source": a["source"],
                    "title": a["title"],
                    "description": a["description"],
                    "reported_at": a.get("published_at", ""),
                    "url": a.get("url", ""),
                }
                for a in s["articles"]
            ],
        }
        if s.get("previous_context"):
            item["previous_context"] = s["previous_context"]
        if include_evidence:
            item["claims"] = _claims_for_prompt(s)
        items.append(item)

    response = client.chat.completions.create(
        model=BRIEFING_MODEL,
        messages=[
            {"role": "system", "content": BRIEFING_PROMPT},
            {"role": "user",   "content": json.dumps(items, ensure_ascii=False)},
        ],
        response_format={"type": "json_object"},
    )

    payload = parse_json_object(response)
    briefings = payload.get("briefings")
    if not isinstance(briefings, list):
        raise ValueError('Model response must contain a "briefings" list')
    return _normalize_briefing_payloads({
        b["canonical_label"]: {
            "briefing": str(b.get("briefing", "")).strip(),
            "delta_summary": str(b.get("delta_summary") or b.get("delta") or "").strip(),
        }
        for b in briefings
        if isinstance(b, dict) and "canonical_label" in b
    })


def _normalize_briefing_payloads(payloads):
    """Accept new structured payloads and legacy label->text test doubles."""
    normalized = {}
    for label, payload in (payloads or {}).items():
        if isinstance(payload, dict):
            briefing = str(payload.get("briefing", "")).strip()
            delta_summary = str(payload.get("delta_summary") or payload.get("delta") or "").strip()
        else:
            briefing = str(payload or "").strip()
            delta_summary = ""
        normalized[label] = {
            "briefing": briefing,
            "delta_summary": delta_summary,
        }
    return normalized


def _merge_briefing_payloads(existing, updates):
    for label, update in _normalize_briefing_payloads(updates).items():
        current = existing.setdefault(label, {"briefing": "", "delta_summary": ""})
        for key in ("briefing", "delta_summary"):
            if update.get(key):
                current[key] = update[key]
    return existing


def _payload_briefing(payloads, label):
    payload = payloads.get(label, {})
    if isinstance(payload, dict):
        return str(payload.get("briefing", "")).strip()
    return str(payload or "").strip()


def _fallback_delta_summary(story):
    previous_context = story.get("previous_context") or {}
    if not previous_context:
        return "First detected today."

    trend = story.get("trend", "steady")
    if trend == "up":
        return "Coverage increased today, but the available reporting did not isolate a distinct new turn."
    if trend == "down":
        return "Coverage cooled today, with reporting shifting toward follow-up coverage rather than a new turn."
    return "Today's reporting continued the story without a distinct new turn."


def _remember_story_briefings(stories, briefings, deltas):
    memories = []
    for story in stories:
        label = story["canonical_label"]
        briefing = str(briefings.get(label, "")).strip()
        if not briefing:
            continue
        delta_summary = str(deltas.get(label, "")).strip() or _fallback_delta_summary(story)
        for observation_id in story.get("observation_ids", []):
            memories.append({
                "observation_id": observation_id,
                "summary": briefing,
                "delta_summary": delta_summary,
            })
    save_observation_memory(memories)


def _missing_briefing_stories(stories, briefing_payloads):
    return [
        story for story in stories
        if not _payload_briefing(briefing_payloads, story["canonical_label"])
    ]


def _fallback_briefing(story):
    articles = sorted(
        story["articles"],
        key=lambda article: _parse_reported_at(article.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    first = articles[0]
    latest = _latest_reported_at(articles)
    title = first.get("title") or story["canonical_label"]
    source = first.get("source", "A source")
    source_count = story["source_count"]
    source_word = "sources" if source_count > 1 else "source"
    return (
        f"{story['canonical_label']} is included based on {source_count} {source_word}, "
        f"with the latest report at {latest}. The lead item is from {source}: {title}."
    )


def build_briefing_package(tracked, n=3, global_n=10, include_evidence=False):
    if not tracked:
        return {
            "generated_at": datetime.now(),
            "stories": [],
            "sections": [],
            "display_stories": [],
            "briefings": {},
            "deltas": {},
        }

    stories = sorted(_aggregate(tracked), key=_score, reverse=True)

    lead_count = min(max(n, 3), 8)
    lead_stories = [story for story in stories if _is_lead_candidate(story)][:lead_count]
    used_labels = {story["canonical_label"] for story in lead_stories}

    politics = _section_candidates(
        stories,
        lambda story: bool(story["themes"] & POLITICS_THEMES),
        used_labels,
        global_n,
    )
    used_labels.update(story["canonical_label"] for story in politics)

    economy = _section_candidates(
        stories,
        lambda story: "Economy" in story["themes"],
        used_labels,
        max(3, min(global_n, 6)),
    )
    used_labels.update(story["canonical_label"] for story in economy)

    other = _section_candidates(
        stories,
        _is_other_important,
        used_labels,
        max(3, min(global_n, 6)),
    )

    sections = [
        ("Top Developments", lead_stories),
        ("Politics", politics),
        ("Economy", economy),
        ("Other Important Stories", other),
    ]

    # One GPT call for all displayed stories, deduplicated.
    seen   = set()
    to_brief = []
    for s in [s for _, section_stories in sections for s in section_stories]:
        if s["canonical_label"] not in seen:
            seen.add(s["canonical_label"])
            to_brief.append(s)
    if include_evidence:
        briefing_payloads = _normalize_briefing_payloads(_get_briefings(to_brief, include_evidence=True))
    else:
        briefing_payloads = _normalize_briefing_payloads(_get_briefings(to_brief))
    missing = _missing_briefing_stories(to_brief, briefing_payloads)
    if missing:
        if include_evidence:
            _merge_briefing_payloads(briefing_payloads, _get_briefings(missing, include_evidence=True))
        else:
            _merge_briefing_payloads(briefing_payloads, _get_briefings(missing))
    for story in to_brief:
        label = story["canonical_label"]
        payload = briefing_payloads.setdefault(label, {"briefing": "", "delta_summary": ""})
        if not payload.get("briefing"):
            payload["briefing"] = _fallback_briefing(story)
        if not payload.get("delta_summary"):
            payload["delta_summary"] = _fallback_delta_summary(story)

    briefings = {
        story["canonical_label"]: briefing_payloads[story["canonical_label"]]["briefing"]
        for story in to_brief
    }
    deltas = {
        story["canonical_label"]: briefing_payloads[story["canonical_label"]]["delta_summary"]
        for story in to_brief
    }
    _remember_story_briefings(to_brief, briefings, deltas)

    return {
        "generated_at": datetime.now(),
        "stories": stories,
        "sections": sections,
        "display_stories": to_brief,
        "briefings": briefings,
        "deltas": deltas,
    }


def build_briefing_markdown(tracked, n=3, global_n=10, package=None, show_evidence=False):
    package = package or build_briefing_package(tracked, n=n, global_n=global_n, include_evidence=show_evidence)

    if not package["stories"]:
        ts = package["generated_at"].strftime("%Y-%m-%d %H:%M")
        return "\n".join([
            "# Top Developments",
            f"_{ts}_",
            "",
            "No tracked stories found.",
        ])

    sections = package["sections"]
    briefings = package["briefings"]
    deltas = package.get("deltas", {})
    ts = package["generated_at"].strftime("%Y-%m-%d %H:%M")
    lines = [
        "# Top Developments",
        f"_{ts}_",
        "",
    ]

    for section_title, section_stories in sections:
        if not section_stories:
            continue
        if section_title != "Top Developments":
            lines += ["---", "", f"# {section_title}", ""]
        for i, s in enumerate(section_stories, 1):
            label      = s["canonical_label"]
            icon       = TREND_ICON.get(s["trend"], "")
            importance = round(s["importance_avg"], 1)
            sources    = s["source_count"]
            reported   = _latest_reported_at(s["articles"])
            delta      = str(deltas.get(label, "")).strip() or _fallback_delta_summary(s)
            story_lines = [
                f"## {i}. {icon} {label}",
                f"_{_theme_summary(s)} — importance {importance} — {sources} {'sources' if sources > 1 else 'source'} — latest reported {reported}_",
                "",
                f"**What changed today:** {delta}",
                "",
                briefings.get(label, ""),
                "",
                *_source_lines(s["articles"]),
            ]
            if show_evidence:
                story_lines += _evidence_lines(s.get("story_id"))
            story_lines.append("")
            lines += story_lines

    return "\n".join(lines)


def write_top10(tracked, n=3, package=None, show_evidence=False):
    BRIEFINGS_DIR.mkdir(exist_ok=True)
    md  = build_briefing_markdown(tracked, n, package=package, show_evidence=show_evidence)
    out = BRIEFINGS_DIR / f"briefing_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    out.write_text(md, encoding="utf-8")
    print(f"Written: {out}")
    return out
