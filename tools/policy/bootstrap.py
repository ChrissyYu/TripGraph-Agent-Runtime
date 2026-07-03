"""Bootstrap tool policy engine from settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tools.policy.engine import ToolPolicyEngine
from tools.policy.models import ToolPolicyStrategy
from tools.policy.trace import ToolPolicyTracer

if TYPE_CHECKING:
    from config.settings import Settings
    from tools.registry import ToolRegistry


def build_tool_policy_engine(
    registry: ToolRegistry,
    settings: Settings,
) -> ToolPolicyEngine | None:
    if not settings.tool_policy_enabled:
        return None
    strategy = settings.resolve_tool_policy_strategy()
    return ToolPolicyEngine(
        registry,
        strategy=strategy,
        mcp_enabled=settings.mcp_enabled,
        mcp_tool_prefix=settings.mcp_tool_prefix,
        settings=settings,
    )


def build_tool_policy_tracer(settings: Settings) -> ToolPolicyTracer:
    return ToolPolicyTracer(trace_enabled=settings.tool_policy_trace_enabled)


def resolve_effective_strategy(settings: Settings) -> ToolPolicyStrategy:
    return settings.resolve_tool_policy_strategy()
