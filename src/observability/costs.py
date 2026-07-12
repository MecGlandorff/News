from src import pricing
from src.observability.database import get_db as _get_db


def llm_cost_summary(run_id):
    conn = _get_db()
    try:
        rows = conn.execute(
            """
            SELECT purpose, model,
                   COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                   COUNT(*) AS calls,
                   COALESCE(SUM(latency_ms), 0) AS latency_ms
            FROM llm_calls
            WHERE run_id = ?
            GROUP BY purpose, model
            ORDER BY purpose, model
            """,
            (run_id,),
        ).fetchall()
    finally:
        conn.close()

    by_purpose = {}
    unpriced_models = set()
    total = 0.0
    for row in rows:
        cost = pricing.estimate_llm_cost_eur(
            row["model"],
            row["prompt_tokens"],
            row["completion_tokens"],
        )
        if cost is None:
            unpriced_models.add(row["model"])
        else:
            total += cost
        purpose = by_purpose.setdefault(row["purpose"], {
            "purpose": row["purpose"],
            "calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "latency_ms": 0,
            "cost_eur": 0.0,
            "unpriced_models": set(),
        })
        purpose["calls"] += row["calls"]
        purpose["prompt_tokens"] += row["prompt_tokens"]
        purpose["completion_tokens"] += row["completion_tokens"]
        purpose["latency_ms"] += row["latency_ms"]
        if cost is None:
            purpose["unpriced_models"].add(row["model"])
        else:
            purpose["cost_eur"] += cost

    return {
        "total_cost_eur": total if not unpriced_models else None,
        "priced_cost_eur": total,
        "unpriced_models": sorted(unpriced_models),
        "by_purpose": [
            {
                **value,
                "unpriced_models": sorted(value["unpriced_models"]),
            }
            for value in by_purpose.values()
        ],
    }
