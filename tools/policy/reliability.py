"""Reliability-aware tool provider scoring (Phase 9D)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ToolProviderReliability(BaseModel):
    success_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    avg_latency_ms: float = Field(default=0.0, ge=0.0)
    fallback_rate: float = Field(default=0.0, ge=0.0, le=1.0)


class ToolReliabilityStats(BaseModel):
    """Per-family builtin/MCP reliability stats."""

    families: dict[str, dict[str, ToolProviderReliability]] = Field(default_factory=dict)

    @classmethod
    def from_file(cls, path: Path | str) -> ToolReliabilityStats:
        file_path = Path(path)
        if not file_path.exists():
            return cls()
        raw = json.loads(file_path.read_text(encoding="utf-8"))
        families: dict[str, dict[str, ToolProviderReliability]] = {}
        for family, providers in raw.items():
            if not isinstance(providers, dict):
                continue
            families[family] = {
                provider: ToolProviderReliability.model_validate(stats)
                for provider, stats in providers.items()
            }
        return cls(families=families)

    def get_provider(self, family: str, provider: str) -> ToolProviderReliability | None:
        return self.families.get(family, {}).get(provider)

    def has_family(self, family: str) -> bool:
        return family in self.families and bool(self.families[family])


class ReliabilityScore(BaseModel):
    provider: str
    tool_name: str | None = None
    score: float
    success_rate: float
    normalized_latency: float
    fallback_rate: float


def load_reliability_stats(path: Path | str | None) -> ToolReliabilityStats:
    if path is None:
        return ToolReliabilityStats()
    return ToolReliabilityStats.from_file(path)


def normalize_latency(avg_latency_ms: float) -> float:
    return min(max(avg_latency_ms / 1000.0, 0.0), 1.0)


def score_tool_provider(
    family: str,
    provider: str,
    stats: ToolReliabilityStats,
    *,
    success_weight: float = 0.7,
    latency_weight: float = 0.2,
    fallback_weight: float = 0.1,
) -> ReliabilityScore | None:
    entry = stats.get_provider(family, provider)
    if entry is None:
        return None
    norm_latency = normalize_latency(entry.avg_latency_ms)
    score = (
        entry.success_rate * success_weight
        - norm_latency * latency_weight
        - entry.fallback_rate * fallback_weight
    )
    return ReliabilityScore(
        provider=provider,
        score=round(score, 4),
        success_rate=entry.success_rate,
        normalized_latency=round(norm_latency, 4),
        fallback_rate=entry.fallback_rate,
    )


def compare_providers_for_family(
    family: str,
    stats: ToolReliabilityStats,
    *,
    builtin_tool: str | None,
    mcp_tool: str | None,
    success_weight: float = 0.7,
    latency_weight: float = 0.2,
    fallback_weight: float = 0.1,
) -> tuple[ReliabilityScore | None, ReliabilityScore | None]:
    builtin_score = score_tool_provider(
        family,
        "builtin",
        stats,
        success_weight=success_weight,
        latency_weight=latency_weight,
        fallback_weight=fallback_weight,
    )
    mcp_score = score_tool_provider(
        family,
        "mcp",
        stats,
        success_weight=success_weight,
        latency_weight=latency_weight,
        fallback_weight=fallback_weight,
    )
    if builtin_score and builtin_tool:
        builtin_score = builtin_score.model_copy(update={"tool_name": builtin_tool})
    if mcp_score and mcp_tool:
        mcp_score = mcp_score.model_copy(update={"tool_name": mcp_tool})
    return builtin_score, mcp_score


def format_reliability_reason(
    family: str,
    chosen: ReliabilityScore,
    other: ReliabilityScore | None,
) -> str:
    parts = [
        f"reliability_aware family={family}",
        f"chosen={chosen.provider}(score={chosen.score:.3f},"
        f" success={chosen.success_rate:.2f},"
        f" latency_norm={chosen.normalized_latency:.2f},"
        f" fallback={chosen.fallback_rate:.2f})",
    ]
    if other is not None:
        parts.append(
            f"alt={other.provider}(score={other.score:.3f})",
        )
    return "; ".join(parts)
