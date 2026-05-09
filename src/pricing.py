from src.config import MODEL_PRICING_USD_PER_1M_TOKENS, USD_TO_EUR_RATE


def model_pricing(model):
    return MODEL_PRICING_USD_PER_1M_TOKENS.get(model)


def estimate_llm_cost_eur(model, prompt_tokens=0, completion_tokens=0):
    pricing = model_pricing(model)
    if pricing is None:
        return None
    input_usd = (prompt_tokens or 0) * pricing["input"] / 1_000_000
    output_usd = (completion_tokens or 0) * pricing["output"] / 1_000_000
    return (input_usd + output_usd) * USD_TO_EUR_RATE


def format_eur(value):
    if value is None:
        return "unavailable"
    if value < 0.01:
        return f"EUR {value:.4f}"
    return f"EUR {value:.2f}"
