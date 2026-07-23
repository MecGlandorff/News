from src.pricing import model_pricing


def test_snapshot_model_uses_family_pricing():
    assert model_pricing("gpt-5.4-mini-2026-03-17") == {
        "input": 0.75,
        "output": 4.50,
    }
