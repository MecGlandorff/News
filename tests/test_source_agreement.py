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


def test_historical_claims_do_not_strengthen_current_agreement():
    claims = [
        {
            "claim_text": "The government approved the budget.",
            "claim_type": "fact",
            "source_id": 1,
            "is_current": True,
        },
        {
            "claim_text": "The government approved the budget.",
            "claim_type": "fact",
            "source_id": 2,
            "is_current": False,
            "evidence_role": "historical_context",
        },
    ]

    agreement = claim_source_agreement(claims)

    assert agreement["label"] == "single-source"
    assert agreement["distinct_claim_source_count"] == 1
    assert agreement["repeated_claim_groups"] == []


def test_similar_claim_wording_is_multi_source_support_not_independence():
    claims = [
        {
            "claim_text": "Government approved the emergency budget after a parliamentary vote.",
            "claim_type": "fact",
            "source_id": 1,
        },
        {
            "claim_text": "After a parliamentary vote, the government approved the emergency budget.",
            "claim_type": "fact",
            "source_id": 2,
        },
    ]

    agreement = claim_source_agreement(claims)

    assert agreement["basis"] == "similar-claim-multi-source-support"
    assert agreement["similar_claim_groups"][0]["distinct_source_count"] == 2
    assert agreement["independent_corroboration_assessed"] is False


def test_claim_source_agreement_flags_date_divergence():
    claims = [
        {
            "claim_text": "The agency said the Brussels summit will begin on June 5, 2026.",
            "claim_type": "fact",
            "source_id": 1,
            "source": "Source A",
        },
        {
            "claim_text": "The agency said the Brussels summit will begin on June 6, 2026.",
            "claim_type": "fact",
            "source_id": 2,
            "source": "Source B",
        },
    ]

    agreement = claim_source_agreement(claims)

    assert agreement["label"] == "mixed"
    assert agreement["basis"] == "claim-date-divergence"
    assert agreement["source_divergence_notes"][0]["type"] == "date"


def test_claim_source_agreement_compares_dates_with_different_month_names():
    claims = [
        {
            "claim_text": "The agency said the Brussels summit will begin on June 30, 2026.",
            "claim_type": "fact",
            "source_id": 1,
        },
        {
            "claim_text": "The agency said the Brussels summit will begin on July 1, 2026.",
            "claim_type": "fact",
            "source_id": 2,
        },
    ]

    agreement = claim_source_agreement(claims)

    assert agreement["basis"] == "claim-date-divergence"


def test_claim_source_agreement_flags_explicit_status_divergence():
    claims = [
        {
            "claim_text": "The council approved the central river bridge construction permit.",
            "claim_type": "fact",
            "source_id": 1,
            "source": "Source A",
        },
        {
            "claim_text": "The council rejected the central river bridge construction permit.",
            "claim_type": "fact",
            "source_id": 2,
            "source": "Source B",
        },
    ]

    agreement = claim_source_agreement(claims)

    assert agreement["basis"] == "claim-status-divergence"
    assert agreement["source_divergence_notes"][0]["statuses"] == ["approved", "rejected"]


def test_claim_source_agreement_flags_same_statement_with_different_attribution():
    claims = [
        {
            "claim_text": "Minister Alice Brown said the border crossing will reopen after inspections.",
            "claim_type": "quote",
            "source_id": 1,
            "source": "Source A",
        },
        {
            "claim_text": "General Bob Stone said the border crossing will reopen after inspections.",
            "claim_type": "quote",
            "source_id": 2,
            "source": "Source B",
        },
    ]

    agreement = claim_source_agreement(claims)

    assert agreement["basis"] == "claim-attribution-divergence"
    note = agreement["source_divergence_notes"][0]
    assert note["actors"] == ["general bob stone", "minister alice brown"]
