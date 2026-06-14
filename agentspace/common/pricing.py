"""Rough per-model token pricing, for showing an estimated $ cost after each run.

Rates are USD per 1M tokens (input, output) and are ESTIMATES — adjust to your plan.
Matched by substring so model aliases and dated IDs both resolve. Cache and tool (e.g.
web_search) costs are not counted, so the figure is a lower-bound approximation.
"""

from __future__ import annotations

# $/1M tokens: (input, output)
PRICING = {
    "opus": (15.0, 75.0),
    "sonnet": (3.0, 15.0),
    "haiku": (1.0, 5.0),
}
_DEFAULT = (3.0, 15.0)


def rates(model: str) -> tuple[float, float]:
    m = (model or "").lower()
    for key, rate in PRICING.items():
        if key in m:
            return rate
    return _DEFAULT


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    in_rate, out_rate = rates(model)
    return (input_tokens or 0) / 1_000_000 * in_rate + (output_tokens or 0) / 1_000_000 * out_rate


def fmt(cost: float) -> str:
    return f"${cost:.4f}" if cost < 1 else f"${cost:.2f}"
