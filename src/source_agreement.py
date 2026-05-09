import re


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
