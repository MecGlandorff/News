from __future__ import annotations

from src.config import MODEL_PRICING_USD_PER_1M_TOKENS, USD_TO_EUR_RATE


def model_pricing(model: str) -> dict[str, float] | None:
    exact = MODEL_PRICING_USD_PER_1M_TOKENS.get(model)
    if exact is not None:
        return exact
    for family in sorted(
        MODEL_PRICING_USD_PER_1M_TOKENS,
        key=len,
        reverse=True,
    ):
        if model.startswith(f"{family}-20"):
            return MODEL_PRICING_USD_PER_1M_TOKENS[family]
    return None


def estimate_llm_cost_eur(
    model: str,
    prompt_tokens: int | None = 0,
    completion_tokens: int | None = 0,
) -> float | None:
    """Estimate call cost in EUR; None when the model has no explicit pricing.

    Token counts may be None: they come from SQL SUM() aggregates, which are
    NULL for runs with no recorded usage.
    """
    pricing = model_pricing(model)
    if pricing is None:
        return None
    input_usd = (prompt_tokens or 0) * pricing["input"] / 1_000_000
    output_usd = (completion_tokens or 0) * pricing["output"] / 1_000_000
    return (input_usd + output_usd) * USD_TO_EUR_RATE


def format_eur(value: float | None) -> str:
    if value is None:
        return "unavailable"
    if value < 0.01:
        return f"EUR {value:.4f}"
    return f"EUR {value:.2f}"
