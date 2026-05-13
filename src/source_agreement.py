import re


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
NUMBER_RE = re.compile(r"\b\d+(?:[,.]\d+)*(?:\.\d+)?%?\b")
TOKEN_RE = re.compile(r"[a-z0-9]+")


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
    return str(value).replace(",", "")


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


def claim_source_agreement(claims, articles=None):
    """Return a conservative source-agreement summary backed by saved claims.

    This is intentionally deterministic and narrow. It only treats exact
    normalized claim repeats as corroboration, and only flags numeric divergence
    when otherwise-similar numeric claims from distinct sources disagree.
    """
    article_lookup = _article_by_id(articles)
    considered = []
    for claim in claims or []:
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
            "source_divergence_notes": [],
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

    divergence_notes = []
    number_groups = {}
    for item in considered:
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

    if divergence_notes:
        label = "mixed"
        basis = "claim-number-divergence"
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
        else:
            label = "partial"
            basis = "multiple-claim-sources-no-repeat"

    return {
        "label": label,
        "basis": basis,
        "claim_count": len(considered),
        "distinct_claim_source_count": len(source_identities),
        "repeated_claim_groups": repeated_groups[:5],
        "source_divergence_notes": divergence_notes[:5],
    }
