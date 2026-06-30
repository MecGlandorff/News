from src.source_agreement import (
    claim_source_agreement,
    source_agreement_label,
    source_identity,
    source_support,
)


def test_source_identity_prefers_source_id():
    article = {"source_id": 7, "source": "Reuters"}

    assert source_identity(article) == "id:7"


def test_source_identity_falls_back_to_normalized_source_name():
    article = {"source": "  Reuters  News "}

    assert source_identity(article) == "name:reuters news"


def test_source_identity_treats_blank_source_id_as_missing():
    article = {"source_id": " ", "source": "Reuters"}

    support = source_support([article])

    assert source_identity(article) == "name:reuters"
    assert support["missing_source_id_count"] == 1


def test_source_support_deduplicates_by_source_id_before_name():
    articles = [
        {"source_id": 1, "source": "Reuters"},
        {"source_id": 1, "source": "Reuters Wire"},
        {"source": "Reuters"},
    ]

    support = source_support(articles)

    assert support["distinct_source_count"] == 2
    assert support["missing_source_id_count"] == 1


def test_source_agreement_label_uses_distinct_source_identity():
    assert source_agreement_label([{"source_id": 1}, {"source_id": 1}]) == "single-source"
    assert source_agreement_label([{"source_id": 1}, {"source_id": 2}]) == "partial"
    assert source_agreement_label([
        {"source_id": 1},
        {"source_id": 2},
        {"source_id": 3},
        {"source_id": 4},
    ]) == "broad"
    assert source_agreement_label([{"source_id": 1}, {"source_id": 2}], has_dispute=True) == "mixed"


def test_claim_source_agreement_uses_repeated_claims_for_partial_support():
    claims = [
        {"claim_text": "The government approved the budget.", "claim_type": "fact", "source_id": 1},
        {"claim_text": "the government approved the budget", "claim_type": "fact", "source_id": 2},
    ]

    agreement = claim_source_agreement(claims)

    assert agreement["label"] == "partial"
    assert agreement["basis"] == "repeated-claim-partial"
    assert agreement["repeated_claim_groups"][0]["distinct_source_count"] == 2


def test_claim_source_agreement_uses_repeated_claims_for_broad_support():
    claims = [
        {"claim_text": "The government approved the budget.", "claim_type": "fact", "source_id": 1},
        {"claim_text": "The government approved the budget.", "claim_type": "fact", "source_id": 2},
        {"claim_text": "The government approved the budget.", "claim_type": "fact", "source_id": 3},
        {"claim_text": "The government approved the budget.", "claim_type": "fact", "source_id": 4},
    ]

    agreement = claim_source_agreement(claims)

    assert agreement["label"] == "broad"
    assert agreement["basis"] == "repeated-claim-broad"


def test_claim_source_agreement_skips_background_claims():
    claims = [
        {"claim_text": "The government approved the budget.", "claim_type": "background", "source_id": 1},
        {"claim_text": "The government approved the budget.", "claim_type": "background", "source_id": 2},
    ]

    agreement = claim_source_agreement(claims)

    assert agreement["label"] is None
    assert agreement["basis"] == "no-claims"
    assert agreement["repeated_claim_groups"] == []


def test_claim_source_agreement_flags_numeric_divergence():
    claims = [
        {
            "claim_text": "Police said 10 people were killed in the blast.",
            "claim_type": "number",
            "source_id": 1,
            "source": "Source A",
        },
        {
            "claim_text": "Officials said 12 people were killed in the blast.",
            "claim_type": "number",
            "source_id": 2,
            "source": "Source B",
        },
    ]

    agreement = claim_source_agreement(claims)

    assert agreement["label"] == "mixed"
    assert agreement["basis"] == "claim-number-divergence"
    assert agreement["source_divergence_notes"] == [{
        "type": "number",
        "numbers": [["10"], ["12"]],
        "sources": ["Source A", "Source B"],
    }]


def test_claim_source_agreement_normalizes_number_formatting():
    claims = [
        {
            "claim_text": "Officials said 1,000 people were evacuated from the city.",
            "claim_type": "number",
            "source_id": 1,
        },
        {
            "claim_text": "Authorities said 1000 people were evacuated from the city.",
            "claim_type": "number",
            "source_id": 2,
        },
    ]

    agreement = claim_source_agreement(claims)

    assert agreement["label"] == "partial"
    assert agreement["source_divergence_notes"] == []


def test_claim_source_agreement_flags_decimal_comma_integer_divergence():
    claims = [
        {
            "claim_text": "Central bank said inflation rose to 1,5 percent in May.",
            "claim_type": "number",
            "source_id": 1,
            "source": "Source A",
        },
        {
            "claim_text": "Central bank said inflation rose to 15 percent in May.",
            "claim_type": "number",
            "source_id": 2,
            "source": "Source B",
        },
    ]

    agreement = claim_source_agreement(claims)

    assert agreement["label"] == "mixed"
    assert agreement["basis"] == "claim-number-divergence"
    assert agreement["source_divergence_notes"] == [{
        "type": "number",
        "numbers": [["1.5"], ["15"]],
        "sources": ["Source A", "Source B"],
    }]


def test_claim_source_agreement_prefers_article_source_id():
    claims = [
        {
            "article_id": 10,
            "claim_text": "The government approved the budget.",
            "claim_type": "fact",
            "source": "Wire Copy A",
        },
        {
            "article_id": 11,
            "claim_text": "The government approved the budget.",
            "claim_type": "fact",
            "source": "Wire Copy B",
        },
    ]
    articles = [
        {"id": 10, "source_id": 1, "source": "Wire A"},
        {"id": 11, "source_id": 1, "source": "Wire B"},
    ]

    agreement = claim_source_agreement(claims, articles)

    assert agreement["label"] == "single-source"
    assert agreement["distinct_claim_source_count"] == 1
    assert agreement["repeated_claim_groups"] == []
