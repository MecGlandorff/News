import re

from src.number_normalization import NUMBER_PATTERN, normalize_number_token


CLAIM_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "by",
    "for",
    "from",
    "has",
    "have",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "to",
    "was",
    "were",
    "will",
    "with",
}
ATTRIBUTION_TOKENS = {
    "according",
    "authorities",
    "official",
    "officials",
    "police",
    "report",
    "reported",
    "reports",
    "said",
    "say",
    "says",
    "source",
    "sources",
}
NUMBER_RE = NUMBER_PATTERN
TOKEN_RE = re.compile(r"[a-z0-9]+")
DATE_RE = re.compile(
    r"\b(?:20\d{2}-\d{1,2}-\d{1,2}|"
    r"(?:january|february|march|april|may|june|july|august|september|october|november|december)"
    r"\s+\d{1,2}(?:,?\s+20\d{2})?)\b",
    re.IGNORECASE,
)
STATUS_GROUPS = {
    "approval": {"approved", "rejected"},
    "availability": {"open", "closed"},
    "custody": {"detained", "released"},
    "life": {"alive", "dead"},
    "operation": {"active", "ended"},
    "outcome": {"won", "lost"},
}
ATTRIBUTION_RE = re.compile(
    r"^\s*(?P<actor>[A-Z][A-Za-z0-9 .'-]{1,60}?)\s+"
    r"(?:said|says|told|announced|reported|claimed)\s+(?P<statement>.+)$"
)


def normalize_source_name(value):
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def normalized_source_id(article):
    source_id = article.get("source_id")
    if source_id is None:
        return None
    value = str(source_id).strip()
    return value or None


def has_source_id(article):
    return normalized_source_id(article) is not None


def source_identity(article):
    source_id = normalized_source_id(article)
    if source_id is not None:
        return f"id:{source_id}"
    source_name = normalize_source_name(article.get("source"))
    if source_name:
        return f"name:{source_name}"
    return "unknown"


def source_support(articles):
    identities = {}
    missing_source_id_count = 0
    for article in articles or []:
        identity = source_identity(article)
        identities.setdefault(identity, {
            "identity": identity,
            "source_id": normalized_source_id(article),
            "source": article.get("source") or "Unknown source",
            "article_count": 0,
        })
        identities[identity]["article_count"] += 1
        if not has_source_id(article):
            missing_source_id_count += 1

    sources = sorted(
        identities.values(),
        key=lambda item: (str(item["source"]).casefold(), str(item["identity"])),
    )
    return {
        "distinct_source_count": len(sources),
        "sources": sources,
        "missing_source_id_count": missing_source_id_count,
    }


def source_agreement_label(articles, has_dispute=False):
    if has_dispute:
        return "mixed"
    count = source_support(articles)["distinct_source_count"]
    if count <= 1:
        return "single-source"
    if count >= 4:
        return "broad"
    return "partial"


def normalize_claim_text(value):
    text = str(value or "").casefold()
    text = re.sub(r"[^\w%]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def claim_signature(claim):
    claim_type = str(claim.get("claim_type") or "").casefold()
    return f"{claim_type}:{normalize_claim_text(claim.get('claim_text'))}"


def _article_by_id(articles):
    return {
        str(article.get("id")): article
        for article in articles or []
        if article.get("id") is not None
    }


def _claim_source_identity(claim, article_lookup):
    article = article_lookup.get(str(claim.get("article_id")))
    if article:
        return source_identity(article)
    source_id = normalized_source_id(claim)
    if source_id is not None:
        return f"id:{source_id}"
    source_name = normalize_source_name(claim.get("source"))
    if source_name:
        return f"name:{source_name}"
    return "unknown"


def _claim_source_display(claim, article_lookup):
    article = article_lookup.get(str(claim.get("article_id")))
    if article:
        return article.get("source") or "Unknown source"
    return claim.get("source") or "Unknown source"


def _claim_numbers(claim):
    text = " ".join([
        str(claim.get("claim_text") or ""),
        str(claim.get("evidence_span") or ""),
    ])
    return sorted({_normalize_number(value) for value in NUMBER_RE.findall(text)})


def _normalize_number(value):
    return normalize_number_token(value)


def _claim_context_tokens(claim):
    text = normalize_claim_text(" ".join([
        str(claim.get("claim_text") or ""),
        str(claim.get("evidence_span") or ""),
    ]))
    text = NUMBER_RE.sub(" ", text)
    tokens = []
    for token in TOKEN_RE.findall(text):
        if token in CLAIM_STOPWORDS or token in ATTRIBUTION_TOKENS:
            continue
        if len(token) < 3:
            continue
        tokens.append(token)
    return sorted(set(tokens))


def _number_divergence_key(claim):
    tokens = _claim_context_tokens(claim)
    if len(tokens) < 3:
        return None
    return " ".join(tokens)


def _claim_summary(group):
    first = group[0]
    source_identities = sorted({item["source_identity"] for item in group})
    sources = sorted({item["source"] for item in group})
    return {
        "claim_text": first["claim"].get("claim_text", ""),
        "claim_type": first["claim"].get("claim_type", ""),
        "distinct_source_count": len(source_identities),
        "sources": sources,
    }


def _similar_claim_groups(considered):
    clusters = []
    for item in considered:
        tokens = set(_claim_context_tokens(item["claim"]))
        if len(tokens) < 5:
            continue
        placed = False
        for cluster in clusters:
            reference = cluster[0]["tokens"]
            union = tokens | reference
            if union and len(tokens & reference) / len(union) >= 0.8:
                cluster.append({**item, "tokens": tokens})
                placed = True
                break
        if not placed:
            clusters.append([{**item, "tokens": tokens}])
    summaries = []
    for cluster in clusters:
        source_count = len({item["source_identity"] for item in cluster})
        signatures = {claim_signature(item["claim"]) for item in cluster}
        if source_count < 2 or len(signatures) < 2:
            continue
        summaries.append(_claim_summary(cluster))
    return summaries


def _claim_dates(claim):
    text = " ".join([
        str(claim.get("claim_text") or ""),
        str(claim.get("evidence_span") or ""),
    ])
    return sorted({normalize_claim_text(value) for value in DATE_RE.findall(text)})


def _date_divergence_key(claim):
    text = " ".join([
        str(claim.get("claim_text") or ""),
        str(claim.get("evidence_span") or ""),
    ])
    without_dates = DATE_RE.sub(" ", text)
    synthetic = {"claim_text": without_dates, "evidence_span": ""}
    return _number_divergence_key(synthetic)


def _claim_status(claim):
    tokens = set(TOKEN_RE.findall(normalize_claim_text(claim.get("claim_text"))))
    matches = []
    for group_name, values in STATUS_GROUPS.items():
        present = sorted(tokens & values)
        if len(present) == 1:
            matches.append((group_name, present[0]))
    return matches[0] if len(matches) == 1 else None


def _status_context_key(claim, status_value):
    tokens = [
        token
        for token in _claim_context_tokens(claim)
        if token != status_value
    ]
    return " ".join(tokens) if len(tokens) >= 3 else None


def _claim_attribution(claim):
    match = ATTRIBUTION_RE.match(str(claim.get("claim_text") or ""))
    if not match:
        return None
    statement = normalize_claim_text(match.group("statement"))
    if len(statement.split()) < 5:
        return None
    return normalize_claim_text(match.group("actor")), statement


def claim_source_agreement(claims, articles=None):
    """Return a conservative source-agreement summary backed by saved claims.

    This is intentionally deterministic and narrow. Exact repeats and highly
    similar claims can show multi-source support, but never prove independent
    corroboration. Divergence is limited to precise number, date, status, and
    attribution patterns across distinct source identities.
    """
    article_lookup = _article_by_id(articles)
    considered = []
    for claim in claims or []:
        if claim.get("is_current") is False or claim.get("evidence_role") == "historical_context":
            continue
        if not claim.get("claim_text"):
            continue
        if str(claim.get("claim_type") or "").casefold() == "background":
            continue
        considered.append({
            "claim": claim,
            "source_identity": _claim_source_identity(claim, article_lookup),
            "source": _claim_source_display(claim, article_lookup),
        })

    if not considered:
        return {
            "label": None,
            "basis": "no-claims",
            "claim_count": 0,
            "distinct_claim_source_count": 0,
            "repeated_claim_groups": [],
            "similar_claim_groups": [],
            "source_divergence_notes": [],
            "independent_corroboration_assessed": False,
        }

    source_identities = sorted({item["source_identity"] for item in considered})
    groups = {}
    for item in considered:
        groups.setdefault(claim_signature(item["claim"]), []).append(item)

    repeated_groups = [
        _claim_summary(group)
        for group in groups.values()
        if len({item["source_identity"] for item in group}) >= 2
    ]
    repeated_groups.sort(
        key=lambda group: (-group["distinct_source_count"], group["claim_text"].casefold())
    )
    similar_groups = _similar_claim_groups(considered)
    similar_groups.sort(
        key=lambda group: (-group["distinct_source_count"], group["claim_text"].casefold())
    )

    divergence_notes = []
    number_groups = {}
    for item in considered:
        if _claim_dates(item["claim"]):
            continue
        numbers = _claim_numbers(item["claim"])
        if not numbers:
            continue
        key = _number_divergence_key(item["claim"])
        if not key:
            continue
        number_groups.setdefault(key, []).append((item, tuple(numbers)))
    for group in number_groups.values():
        source_count = len({item["source_identity"] for item, _numbers in group})
        number_sets = sorted({numbers for _item, numbers in group})
        if source_count < 2 or len(number_sets) < 2:
            continue
        sources = sorted({item["source"] for item, _numbers in group})
        divergence_notes.append({
            "type": "number",
            "numbers": [list(numbers) for numbers in number_sets],
            "sources": sources,
        })

    date_groups = {}
    for item in considered:
        dates = _claim_dates(item["claim"])
        if not dates:
            continue
        key = _date_divergence_key(item["claim"])
        if key:
            date_groups.setdefault(key, []).append((item, tuple(dates)))
    for group in date_groups.values():
        source_count = len({item["source_identity"] for item, _dates in group})
        date_sets = sorted({dates for _item, dates in group})
        if source_count >= 2 and len(date_sets) >= 2:
            divergence_notes.append({
                "type": "date",
                "dates": [list(dates) for dates in date_sets],
                "sources": sorted({item["source"] for item, _dates in group}),
            })

    status_groups = {}
    for item in considered:
        status = _claim_status(item["claim"])
        if status is None:
            continue
        group_name, status_value = status
        context_key = _status_context_key(item["claim"], status_value)
        if context_key:
            status_groups.setdefault((group_name, context_key), []).append(
                (item, status_value)
            )
    for group in status_groups.values():
        source_count = len({item["source_identity"] for item, _status in group})
        statuses = sorted({status for _item, status in group})
        if source_count >= 2 and len(statuses) >= 2:
            divergence_notes.append({
                "type": "status",
                "statuses": statuses,
                "sources": sorted({item["source"] for item, _status in group}),
            })

    attribution_groups = {}
    for item in considered:
        attribution = _claim_attribution(item["claim"])
        if attribution is None:
            continue
        actor, statement = attribution
        attribution_groups.setdefault(statement, []).append((item, actor))
    for statement, group in attribution_groups.items():
        source_count = len({item["source_identity"] for item, _actor in group})
        actors = sorted({actor for _item, actor in group})
        if source_count >= 2 and len(actors) >= 2:
            divergence_notes.append({
                "type": "attribution",
                "statement": statement,
                "actors": actors,
                "sources": sorted({item["source"] for item, _actor in group}),
            })

    if divergence_notes:
        label = "mixed"
        divergence_types = {note["type"] for note in divergence_notes}
        basis = (
            f"claim-{next(iter(divergence_types))}-divergence"
            if len(divergence_types) == 1
            else "claim-source-divergence"
        )
    elif len(source_identities) <= 1:
        label = "single-source"
        basis = "single-claim-source"
    else:
        max_repeated_sources = max(
            [group["distinct_source_count"] for group in repeated_groups],
            default=0,
        )
        if max_repeated_sources >= 4:
            label = "broad"
            basis = "repeated-claim-broad"
        elif max_repeated_sources >= 2:
            label = "partial"
            basis = "repeated-claim-partial"
        elif similar_groups:
            label = "partial"
            basis = "similar-claim-multi-source-support"
        else:
            label = "partial"
            basis = "multiple-claim-sources-no-repeat"

    return {
        "label": label,
        "basis": basis,
        "claim_count": len(considered),
        "distinct_claim_source_count": len(source_identities),
        "repeated_claim_groups": repeated_groups[:5],
        "similar_claim_groups": similar_groups[:5],
        "source_divergence_notes": divergence_notes[:5],
        "independent_corroboration_assessed": False,
    }
