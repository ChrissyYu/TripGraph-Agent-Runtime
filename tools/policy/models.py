"""Tool routing policy domain models (Phase 9C)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolFamily(StrEnum):
    WEATHER = "weather"
    MAP = "map"
    BUDGET = "budget"
    ECHO = "echo"
    UNKNOWN = "unknown"


class ToolProvider(StrEnum):
    BUILTIN = "builtin"
    MCP = "mcp"
    UNKNOWN = "unknown"


class ToolPolicyStrategy(StrEnum):
    PLANNER_HINT_FIRST = "planner_hint_first"
    BUILTIN_FIRST = "builtin_first"
    MCP_FIRST = "mcp_first"
    DETERMINISTIC = "deterministic"
    COST_AWARE = "cost_aware"
    RELIABILITY_AWARE = "reliability_aware"


BUILTIN_BY_FAMILY: dict[ToolFamily, str] = {
    ToolFamily.WEATHER: "weather",
    ToolFamily.MAP: "map",
    ToolFamily.BUDGET: "budget",
    ToolFamily.ECHO: "echo",
}

MCP_BY_FAMILY: dict[ToolFamily, str] = {
    ToolFamily.WEATHER: "mcp_weather",
    ToolFamily.MAP: "mcp_map",
    ToolFamily.BUDGET: "mcp_budget",
}

FAMILY_BY_TOOL: dict[str, ToolFamily] = {
    "weather": ToolFamily.WEATHER,
    "map": ToolFamily.MAP,
    "budget": ToolFamily.BUDGET,
    "echo": ToolFamily.ECHO,
    "mcp_weather": ToolFamily.WEATHER,
    "mcp_map": ToolFamily.MAP,
    "mcp_budget": ToolFamily.BUDGET,
}


def tool_family(tool_name: str | None) -> ToolFamily:
    if not tool_name:
        return ToolFamily.UNKNOWN
    return FAMILY_BY_TOOL.get(tool_name.lower(), ToolFamily.UNKNOWN)


def tool_provider(tool_name: str | None) -> ToolProvider:
    if not tool_name:
        return ToolProvider.UNKNOWN
    name = tool_name.lower()
    if name.startswith("mcp_"):
        return ToolProvider.MCP
    if name in {"weather", "map", "budget", "echo"}:
        return ToolProvider.BUILTIN
    return ToolProvider.UNKNOWN


def builtin_tool_for_family(family: ToolFamily) -> str | None:
    return BUILTIN_BY_FAMILY.get(family)


def mcp_tool_for_family(family: ToolFamily, *, prefix: str = "mcp_") -> str | None:
    if family in MCP_BY_FAMILY:
        return MCP_BY_FAMILY[family]
    return None


class ToolPolicyDecision(BaseModel):
    """Result of a single tool routing policy evaluation."""

    original_tool_hint: str | None = None
    selected_tool: str | None = None
    selected_provider: ToolProvider = ToolProvider.UNKNOWN
    tool_family: ToolFamily = ToolFamily.UNKNOWN
    policy_name: str = "planner_hint_first"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    fallback_candidates: list[str] = Field(default_factory=list)
    reason: str = ""
    fallback_used: bool = False
    fallback_tool: str | None = None
    failure_reason: str | None = None
    latency_ms: float | None = None

    def model_dump_json_safe(self) -> dict[str, Any]:
        data = self.model_dump()
        data["selected_provider"] = self.selected_provider.value
        data["tool_family"] = self.tool_family.value
        return data


class ToolPolicyTraceEntry(ToolPolicyDecision):
    """Policy decision enriched with execution context."""

    execution_id: str | None = None
    trace_id: str | None = None
    session_id: str | None = None
    step_id: int | None = None
    task: str | None = None
    query: str | None = None


PolicyStrategyLiteral = Literal[
    "planner_hint_first",
    "builtin_first",
    "mcp_first",
    "deterministic",
    "cost_aware",
    "reliability_aware",
]
