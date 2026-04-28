import re


GLOBAL_LOCATION = {
    "scope": "global",
    "label": "Global",
    "confidence": "medium",
    "points": [],
}

UNKNOWN_LOCATION = {
    "scope": "unknown",
    "label": "Unknown",
    "confidence": "low",
    "points": [],
}

GLOBAL_KEYWORDS = {
    "global economy",
    "global markets",
    "markets",
    "oil prices",
    "worldwide",
    "supply chain",
    "climate change",
}

GAZETTEER = [
    ("White House", 38.8977, -77.0365, "local", ["white house", "washington"]),
    ("United States", 39.8283, -98.5795, "national", ["united states", "u.s.", "us politics", "america", "american", "trump"]),
    ("United Kingdom", 55.3781, -3.4360, "national", ["united kingdom", "britain", "british", "uk", "london", "king charles"]),
    ("Netherlands", 52.1326, 5.2913, "national", ["netherlands", "dutch", "nederland", "den haag", "amsterdam"]),
    ("European Union", 50.8503, 4.3517, "regional", ["european union", "eu", "brussels"]),
    ("Europe", 54.5260, 15.2551, "regional", ["europe", "nato"]),
    ("Ukraine", 48.3794, 31.1656, "national", ["ukraine", "ukrainian", "kyiv", "odesa", "chernobyl"]),
    ("Russia", 61.5240, 105.3188, "national", ["russia", "russian", "moscow", "putin"]),
    ("Iran", 32.4279, 53.6880, "national", ["iran", "iranian", "tehran", "hormuz", "isfahan"]),
    ("Strait of Hormuz", 26.5667, 56.2500, "local", ["strait of hormuz", "hormuz"]),
    ("Israel", 31.0461, 34.8516, "national", ["israel", "israeli"]),
    ("Gaza", 31.5017, 34.4668, "local", ["gaza"]),
    ("Lebanon", 33.8547, 35.8623, "national", ["lebanon", "lebanese", "hezbollah", "beirut"]),
    ("Syria", 34.8021, 38.9968, "national", ["syria", "syrian"]),
    ("Saudi Arabia", 23.8859, 45.0792, "national", ["saudi arabia", "saudi"]),
    ("Yemen", 15.5527, 48.5164, "national", ["yemen", "houthi"]),
    ("Mali", 17.5707, -3.9962, "national", ["mali", "malian", "bamako", "kati", "jnim", "azawad"]),
    ("Chad", 15.4542, 18.7322, "national", ["chad", "chadian", "guereda"]),
    ("Sudan", 12.8628, 30.2176, "national", ["sudan", "sudanese"]),
    ("North Korea", 40.3399, 127.5101, "national", ["north korea", "pyongyang", "kim jong-un"]),
    ("South Korea", 35.9078, 127.7669, "national", ["south korea", "seoul"]),
    ("China", 35.8617, 104.1954, "national", ["china", "chinese", "beijing"]),
    ("Taiwan", 23.6978, 120.9605, "national", ["taiwan", "taipei"]),
    ("Japan", 36.2048, 138.2529, "national", ["japan", "japanese", "tokyo"]),
    ("India", 20.5937, 78.9629, "national", ["india", "indian", "new delhi"]),
    ("Pakistan", 30.3753, 69.3451, "national", ["pakistan", "pakistani", "islamabad"]),
    ("Afghanistan", 33.9391, 67.7100, "national", ["afghanistan", "afghan", "kabul"]),
    ("Thailand", 15.8700, 100.9925, "national", ["thailand", "thai", "bangkok"]),
    ("Northern Ireland", 54.7877, -6.4923, "local", ["northern ireland", "belfast"]),
    ("Colombia", 4.5709, -74.2973, "national", ["colombia", "colombian", "bogota"]),
    ("Germany", 51.1657, 10.4515, "national", ["germany", "german", "merz", "berlin"]),
    ("France", 46.2276, 2.2137, "national", ["france", "french", "paris"]),
]


def infer_story_location(story):
    """Infer coarse story-level geography without an extra model call."""
    label_text = _normalize(story.get("canonical_label") or story.get("story_label") or "")
    article_text = _normalize(" ".join(
        [a.get("title", "") + " " + a.get("description", "") for a in story.get("articles", [])]
    ))
    full_text = f"{label_text} {article_text}".strip()
    if not full_text:
        return dict(UNKNOWN_LOCATION)

    hits = []
    for name, lat, lon, scope, aliases in GAZETTEER:
        score = 0
        for alias in aliases:
            alias = _normalize(alias)
            if _contains_alias(label_text, alias):
                score += 3
            if _contains_alias(article_text, alias):
                score += 1
        if score:
            hits.append({
                "label": name,
                "lat": lat,
                "lon": lon,
                "scope": scope,
                "score": score,
            })

    if not hits:
        if _looks_global(full_text, story.get("themes", set())):
            return dict(GLOBAL_LOCATION)
        return dict(UNKNOWN_LOCATION)

    hits.sort(key=lambda hit: hit["score"], reverse=True)
    deduped = []
    seen = set()
    for hit in hits:
        if hit["label"] in seen:
            continue
        seen.add(hit["label"])
        deduped.append(hit)

    top = deduped[0]
    if len(deduped) == 1 or top["score"] >= deduped[1]["score"] * 2:
        return {
            "scope": top["scope"],
            "label": top["label"],
            "confidence": "high" if top["score"] >= 3 else "medium",
            "points": [_point(top)],
        }

    points = [_point(hit) for hit in deduped[:3]]
    labels = [point["label"] for point in points]
    suffix = "" if len(deduped) <= 3 else f" +{len(deduped) - 3}"
    return {
        "scope": "multi-region",
        "label": " / ".join(labels) + suffix,
        "confidence": "medium",
        "points": points,
    }


def _point(hit):
    return {
        "label": hit["label"],
        "lat": hit["lat"],
        "lon": hit["lon"],
    }


def _normalize(value):
    return re.sub(r"\s+", " ", str(value or "").lower()).strip()


def _contains_alias(text, alias):
    if not text or not alias:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", text) is not None


def _looks_global(text, themes):
    if any(keyword in text for keyword in GLOBAL_KEYWORDS):
        return True
    return "Economy" in set(themes or []) and not any(
        _contains_alias(text, _normalize(alias))
        for _, _, _, _, aliases in GAZETTEER
        for alias in aliases
    )
