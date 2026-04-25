import json
from src.article_cache import get_cached_classifications, save_classifications
from src.config import CLASSIFIER_MODEL
from src.llm import get_openai_client, parse_json_object

THEMES = ["Geopolitics & War", "USA Politics", "Dutch Politics", "Economy", "Tech", "Climate", "Science", "Sports", "Other"]
CLASSIFIER_PROMPT_VERSION = "2026-04-25-v1"

SYSTEM_PROMPT = """You are a news classifier. Given a list of articles, classify each article into exactly one theme.

Themes and what belongs in each:
- Geopolitics & War: international conflicts, wars, diplomacy, treaties, foreign policy between nations, military operations, sanctions, international crises
- USA Politics: US domestic politics, Trump administration, US Congress, US elections, US government policy, US Supreme Court
- Dutch Politics: Dutch domestic politics, Dutch government, Dutch parliament (Tweede Kamer), Dutch elections, Dutch national policy — classify based on content only, not language
- Economy: markets, trade, inflation, business, corporate news with broad impact, economic policy
- Tech: technology, AI, cybersecurity, big tech companies, innovation
- Climate: climate change, energy transition, environment, sustainability policy
- Science: scientific research, health, medicine, space
- Sports: sports results, athletes — only if no broader societal impact
- Other: anything that does not fit the above

For each article return:
- id: the article id (string, unchanged)
- theme: one of the themes above (exact string)
- story_label: short 2-5 word label in English that groups similar articles into the same ongoing story
- importance: int 1-5 (5 = major breaking news, 1 = minor/niche)

Return a JSON object with key "results" containing an array of these objects.
Classify based on title and description only.

CRITICAL — story_label consistency: multiple articles covering the same ongoing event MUST use the exact same story_label string. Before finalizing, scan all your labels and merge any that refer to the same story. "Iran nuclear talks", "Iran uranium deal", "Iran enrichment negotiations" → all become "Iran Nuclear Talks".

Importance rules — apply strictly:
- 5: Major geopolitical events, wars, economic crises, natural disasters, landmark policy decisions affecting millions
- 4: Significant national policy, international diplomacy, major corporate decisions with broad impact
- 3: Notable but contained events — regional politics, industry developments, scientific breakthroughs
- 2: Minor developments, follow-up stories, niche topics
- 1: Entertainment, sports results, celebrity news, human interest — anything that does not affect how the world works

When in doubt: score 1. A sports result is 1. A doping case is 1. A celebrity story is 1. Ukraine, Gaza, trade wars, elections are 4-5."""


def classify_articles(articles):
    if not articles:
        return []

    cached = get_cached_classifications(
        articles,
        classifier_model=CLASSIFIER_MODEL,
        prompt_version=CLASSIFIER_PROMPT_VERSION,
    )
    missing = [a for a in articles if str(a["id"]) not in cached]
    classification = dict(cached)

    if missing:
        client = get_openai_client()

        items = [
            {"id": str(a["id"]), "title": a["title"], "description": a["description"]}
            for a in missing
        ]

        response = client.chat.completions.create(
            model=CLASSIFIER_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(items, ensure_ascii=False)},
            ],
            response_format={"type": "json_object"},
        )

        payload = parse_json_object(response)
        results = payload.get("results")
        if not isinstance(results, list):
            raise ValueError('Model response must contain a "results" list')

        valid_ids = {str(a["id"]) for a in missing}
        new_classifications = {}
        for r in results:
            if not isinstance(r, dict):
                continue
            result_id = str(r.get("id"))
            if result_id not in valid_ids:
                continue
            theme = r.get("theme") if r.get("theme") in THEMES else "Other"
            try:
                importance = int(r.get("importance", 1))
            except (TypeError, ValueError):
                importance = 1
            new_classifications[result_id] = {
                "theme": theme,
                "story_label": str(r.get("story_label") or "Uncategorized").strip() or "Uncategorized",
                "importance": min(max(importance, 1), 5),
            }
        save_classifications(
            missing,
            new_classifications,
            classifier_model=CLASSIFIER_MODEL,
            prompt_version=CLASSIFIER_PROMPT_VERSION,
        )
        classification.update(new_classifications)

    enriched = []
    for a in articles:
        c = classification.get(str(a["id"]), {})
        enriched.append({
            **a,
            "theme":       c.get("theme", "Other"),
            "story_label": c.get("story_label", "Uncategorized"),
            "importance":  c.get("importance", 1),
        })

    return enriched
