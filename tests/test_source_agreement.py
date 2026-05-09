from src.source_agreement import source_agreement_label, source_identity, source_support


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
