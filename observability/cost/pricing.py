"""Token cost estimation."""

from __future__ import annotations

from core.llm.usage import LLMUsage


def estimate_cost_usd(
    usage: LLMUsage,
    *,
    prompt_usd_per_1k: float,
    completion_usd_per_1k: float,
) -> float:
    prompt_cost = (usage.prompt_tokens / 1000.0) * prompt_usd_per_1k
    completion_cost = (usage.completion_tokens / 1000.0) * completion_usd_per_1k
    return round(prompt_cost + completion_cost, 6)
