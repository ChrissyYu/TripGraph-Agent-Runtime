"""Tool routing policy engine (Phase 9C)."""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING

from tools.policy.reliability import (
    ReliabilityScore,
    compare_providers_for_family,
    format_reliability_reason,
    load_reliability_stats,
)
from tools.policy.models import (
    ToolFamily,
    ToolPolicyDecision,
    ToolPolicyStrategy,
    ToolProvider,
    builtin_tool_for_family,
    mcp_tool_for_family,
    tool_family,
    tool_provider,
)

if TYPE_CHECKING:
    from config.settings import Settings
    from tools.registry import ToolRegistry


_MCP_QUERY_PATTERN = re.compile(r"\bmcp\b", re.IGNORECASE)
_BUILTIN_QUERY_PATTERN = re.compile(r"本地|builtin|内置", re.IGNORECASE)


class ToolPolicyEngine:
    """Selects builtin vs MCP tools according to configured strategy."""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        strategy: ToolPolicyStrategy | str = ToolPolicyStrategy.PLANNER_HINT_FIRST,
        mcp_enabled: bool = False,
        mcp_tool_prefix: str = "mcp_",
        settings: Settings | None = None,
    ) -> None:
        from config.settings import get_settings

        cfg = settings or get_settings()
        self._registry = registry
        self._settings = cfg
        self._mcp_enabled = mcp_enabled if mcp_enabled is not None else cfg.mcp_enabled
        self._mcp_prefix = mcp_tool_prefix or cfg.mcp_tool_prefix
        self._strategy = (
            ToolPolicyStrategy(strategy)
            if isinstance(strategy, str)
            else strategy
        )
        self._reliability_stats = load_reliability_stats(cfg.tool_policy_reliability_stats_path)

    @property
    def strategy(self) -> ToolPolicyStrategy:
        return self._strategy

    def decide(
        self,
        *,
        tool_hint: str | None,
        task: str = "",
        query: str = "",
        policy_override: ToolPolicyStrategy | str | None = None,
    ) -> ToolPolicyDecision:
        started = time.perf_counter()
        strategy = self._resolve_strategy(policy_override)
        family = tool_family(tool_hint)
        if family == ToolFamily.UNKNOWN and task:
            family = self._infer_family_from_text(task, query)

        preferred, fallbacks, reason, confidence = self._apply_strategy(
            strategy=strategy,
            tool_hint=tool_hint,
            family=family,
            task=task,
            query=query,
        )

        selected = self._pick_available(preferred, fallbacks)
        if selected is None and tool_hint and self._registry.has(tool_hint):
            selected = tool_hint
            reason = f"{reason}; using original hint {tool_hint} (only available)"
            confidence = max(confidence, 0.5)

        if selected is None:
            latency_ms = (time.perf_counter() - started) * 1000
            return ToolPolicyDecision(
                original_tool_hint=tool_hint,
                selected_tool=None,
                selected_provider=ToolProvider.UNKNOWN,
                tool_family=family,
                policy_name=strategy.value,
                confidence=0.0,
                fallback_candidates=fallbacks,
                reason=reason or "no tool available",
                latency_ms=latency_ms,
            )

        final_fallbacks = [name for name in fallbacks if name != selected and self._registry.has(name)]
        latency_ms = (time.perf_counter() - started) * 1000
        return ToolPolicyDecision(
            original_tool_hint=tool_hint,
            selected_tool=selected,
            selected_provider=tool_provider(selected),
            tool_family=tool_family(selected),
            policy_name=strategy.value,
            confidence=confidence,
            fallback_candidates=final_fallbacks,
            reason=reason,
            latency_ms=latency_ms,
        )

    def _resolve_strategy(
        self,
        policy_override: ToolPolicyStrategy | str | None,
    ) -> ToolPolicyStrategy:
        if policy_override is not None:
            return (
                ToolPolicyStrategy(policy_override)
                if isinstance(policy_override, str)
                else policy_override
            )
        if self._strategy in (ToolPolicyStrategy.COST_AWARE,):
            return ToolPolicyStrategy.BUILTIN_FIRST
        if self._strategy == ToolPolicyStrategy.DETERMINISTIC:
            return ToolPolicyStrategy.BUILTIN_FIRST
        return self._strategy

    def _apply_strategy(
        self,
        *,
        strategy: ToolPolicyStrategy,
        tool_hint: str | None,
        family: ToolFamily,
        task: str,
        query: str,
    ) -> tuple[str | None, list[str], str, float]:
        builtin = builtin_tool_for_family(family) if family != ToolFamily.UNKNOWN else None
        mcp = mcp_tool_for_family(family, prefix=self._mcp_prefix) if family != ToolFamily.UNKNOWN else None

        if strategy == ToolPolicyStrategy.PLANNER_HINT_FIRST:
            return self._planner_hint_first(tool_hint, family, builtin, mcp, task, query)
        if strategy == ToolPolicyStrategy.BUILTIN_FIRST:
            return self._provider_first(builtin, mcp, "builtin_first prefers builtin")
        if strategy == ToolPolicyStrategy.MCP_FIRST:
            return self._provider_first(mcp, builtin, "mcp_first prefers MCP")
        if strategy == ToolPolicyStrategy.RELIABILITY_AWARE:
            return self._reliability_aware(family, builtin, mcp)
        return self._planner_hint_first(tool_hint, family, builtin, mcp, task, query)

    def _planner_hint_first(
        self,
        tool_hint: str | None,
        family: ToolFamily,
        builtin: str | None,
        mcp: str | None,
        task: str,
        query: str,
    ) -> tuple[str | None, list[str], str, float]:
        if tool_hint and self._registry.has(tool_hint):
            alt = mcp if tool_provider(tool_hint) == ToolProvider.BUILTIN else builtin
            fallbacks = [alt] if alt else []
            return (
                tool_hint,
                [name for name in fallbacks if name],
                f"planner_hint_first respects hint={tool_hint}",
                0.9,
            )

        if _MCP_QUERY_PATTERN.search(query or task):
            preferred, fallback = mcp, builtin
            reason = "query/task mentions MCP; prefer MCP family tool"
            confidence = 0.75
        elif _BUILTIN_QUERY_PATTERN.search(query or task):
            preferred, fallback = builtin, mcp
            reason = "query/task mentions local/builtin; prefer builtin"
            confidence = 0.75
        elif family != ToolFamily.UNKNOWN:
            preferred, fallback = builtin, mcp
            reason = f"no hint; family={family.value} rule-based builtin default"
            confidence = 0.6
        else:
            preferred, fallback = tool_hint, None
            reason = "no hint and unknown family"
            confidence = 0.3

        fallbacks = [name for name in (fallback,) if name]
        return preferred, fallbacks, reason, confidence

    def _provider_first(
        self,
        preferred: str | None,
        fallback: str | None,
        reason: str,
    ) -> tuple[str | None, list[str], str, float]:
        if preferred and preferred.startswith(self._mcp_prefix) and not self._mcp_enabled:
            if fallback:
                return (
                    fallback,
                    [],
                    f"{reason}; MCP disabled → fallback to {fallback}",
                    0.7,
                )
            return None, [], f"{reason}; MCP disabled and no builtin fallback", 0.0

        fallbacks = [fallback] if fallback else []
        return preferred, fallbacks, reason, 0.85

    def _reliability_aware(
        self,
        family: ToolFamily,
        builtin: str | None,
        mcp: str | None,
    ) -> tuple[str | None, list[str], str, float]:
        if family == ToolFamily.UNKNOWN or not self._reliability_stats.has_family(family.value):
            return self._provider_first(
                builtin,
                mcp,
                "reliability_aware stats_missing; fallback builtin_first",
            )

        builtin_score, mcp_score = compare_providers_for_family(
            family.value,
            self._reliability_stats,
            builtin_tool=builtin,
            mcp_tool=mcp,
            success_weight=self._settings.tool_policy_success_weight,
            latency_weight=self._settings.tool_policy_latency_weight,
            fallback_weight=self._settings.tool_policy_fallback_weight,
        )

        candidates: list[tuple[ReliabilityScore, str | None]] = []
        if builtin_score and builtin:
            candidates.append((builtin_score, builtin))
        if mcp_score and mcp:
            candidates.append((mcp_score, mcp))

        if not candidates:
            return self._provider_first(
                builtin,
                mcp,
                "reliability_aware no scored providers; fallback builtin_first",
            )

        candidates.sort(key=lambda item: item[0].score, reverse=True)
        chosen_score, chosen_tool = candidates[0]
        fallback_tool = candidates[1][1] if len(candidates) > 1 else None
        other_score = candidates[1][0] if len(candidates) > 1 else None
        reason = format_reliability_reason(family.value, chosen_score, other_score)
        fallbacks = [name for name in (fallback_tool,) if name]
        return chosen_tool, fallbacks, reason, min(0.95, 0.6 + chosen_score.score * 0.3)

    def _pick_available(
        self,
        preferred: str | None,
        fallbacks: list[str],
    ) -> str | None:
        if preferred and self._registry.has(preferred):
            if preferred.startswith(self._mcp_prefix) and not self._mcp_enabled:
                pass
            else:
                return preferred

        for candidate in fallbacks:
            if not candidate:
                continue
            if candidate.startswith(self._mcp_prefix) and not self._mcp_enabled:
                continue
            if self._registry.has(candidate):
                return candidate
        return None

    @staticmethod
    def _infer_family_from_text(task: str, query: str) -> ToolFamily:
        text = f"{task} {query}".lower()
        if any(k in text for k in ("天气", "weather", "气温")):
            return ToolFamily.WEATHER
        if any(k in text for k in ("路线", "地图", "map", "导航", "景点")):
            return ToolFamily.MAP
        if any(k in text for k in ("预算", "budget", "费用", "花费")):
            return ToolFamily.BUDGET
        if "echo" in text:
            return ToolFamily.ECHO
        return ToolFamily.UNKNOWN

    def recovery_action_for_fallback(
        self,
        failed_tool: str,
        fallback_tool: str,
    ) -> str:
        failed_provider = tool_provider(failed_tool)
        fallback_provider = tool_provider(fallback_tool)
        if failed_provider == ToolProvider.MCP and fallback_provider == ToolProvider.BUILTIN:
            return "mcp_to_builtin_fallback"
        if failed_provider == ToolProvider.BUILTIN and fallback_provider == ToolProvider.MCP:
            return "builtin_to_mcp_fallback"
        return "tool_policy_fallback"
