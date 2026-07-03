"""Graph-level demo evaluator (Phase 10A)."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from typing import Any

from dataclasses import dataclass

from app.bootstrap import bootstrap_runtime
from config.settings import Settings
from eval.graph_eval.diagnostics import build_low_recall_diagnostics
from eval.graph_eval.models import GraphDemoEvalCase, GraphDemoEvalReport, GraphDemoEvalResult
from eval.graph_eval.scorer import GraphDemoScorer
from graph.runtime.runner import GraphRuntimeRunner
from plan.validator import PlanValidator
from schemas.graph_runtime import GraphExecuteResponse
from tools.adapters.mcp import MCPToolProvider
from tools.policy.engine import ToolPolicyEngine
from tools.policy.models import tool_family, tool_provider
from tools.registry import ToolRegistry


class FakeMCPClient:
    """In-process mock MCP server for graph demo eval."""

    async def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "mcp_weather",
                "description": "MCP weather",
                "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}},
            },
            {
                "name": "mcp_map",
                "description": "MCP map",
                "input_schema": {
                    "type": "object",
                    "properties": {"destination": {"type": "string"}},
                },
            },
            {
                "name": "mcp_budget",
                "description": "MCP budget",
                "input_schema": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}, "days": {"type": "integer"}},
                },
            },
        ]

    async def call_tool(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "mcp_weather":
            return {
                "city": args.get("city", "上海"),
                "date": "2026-06-29",
                "condition": "晴",
                "temp_c": 28,
            }
        if tool_name == "mcp_map":
            return {
                "origin": args.get("origin", "酒店"),
                "destination": args.get("destination", "景点"),
                "duration_min": 25,
                "mode": "transit",
            }
        if tool_name == "mcp_budget":
            return {
                "total": 3200,
                "currency": "CNY",
                "days": args.get("days", 3),
                "breakdown": {"hotel": 1200, "food": 800, "transport": 600, "tickets": 600},
            }
        return {"tool": tool_name, "args": args, "source": "graph_demo_mock_mcp"}


POLICY_STRATEGIES_NEEDING_REAL_EVAL_MODE = frozenset(
    {"mcp_first", "cost_aware", "reliability_aware"},
)


@dataclass(frozen=True)
class _ExtractedExecution:
    tools: list[str]
    providers: list[str]
    source: str


class GraphDemoEvaluator:
    """Run labeled graph demo cases through GraphRuntimeRunner."""

    def __init__(
        self,
        *,
        default_mcp_enabled: bool | None = None,
        default_policy_strategy: str | None = None,
        eval_mode: str = "deterministic_eval",
        llm_provider: str = "rule_based",
    ) -> None:
        self._default_mcp_enabled = default_mcp_enabled
        self._default_policy_strategy = default_policy_strategy
        self._eval_mode = eval_mode
        self._llm_provider = llm_provider
        self._scorer = GraphDemoScorer()

    async def evaluate_cases(
        self,
        cases: list[GraphDemoEvalCase],
        *,
        dataset_hash: str = "",
        dataset_path: str = "",
    ) -> GraphDemoEvalReport:
        results: list[GraphDemoEvalResult] = []
        for case in cases:
            results.append(await self.run_case(case))

        aggregate = self._scorer.aggregate(results)
        low_tool, low_provider = build_low_recall_diagnostics(cases, results)
        return GraphDemoEvalReport(
            created_at=datetime.now(UTC),
            dataset_path=dataset_path,
            dataset_hash=dataset_hash,
            eval_mode=self._eval_mode,
            llm_provider=self._llm_provider,
            total_cases=len(results),
            aggregate_metrics=aggregate,
            per_case_results=results,
            failed_cases=aggregate.failed_cases,
            low_tool_selection_recall_cases=low_tool,
            low_provider_recall_cases=low_provider,
            notes=[
                "Graph demo eval validates agent infra behavior, not real travel quality.",
                "Default path uses RuleBased LLM and mock MCP tools.",
                "Recall = |expected ∩ actual| / |expected|; extra tools lower precision, not recall.",
            ],
        )

    async def run_case(self, case: GraphDemoEvalCase) -> GraphDemoEvalResult:
        started = time.perf_counter()
        try:
            settings = self._build_settings(case)
            registry = await self._build_registry(case, settings)
            graph_runner = self._build_graph_runner(settings, registry, case)
            response = await graph_runner.invoke(
                case.query,
                session_id=f"graph-demo-{case.id}",
            )
            latency_ms = (time.perf_counter() - started) * 1000
            return self._score_response(case, response, registry=registry, latency_ms=latency_ms)
        except Exception as exc:
            latency_ms = (time.perf_counter() - started) * 1000
            return self._scorer.score_case(
                case,
                execution_success=False,
                plan_validity=False,
                final_result="",
                actual_tools=[],
                actual_tool_families=[],
                actual_providers=[],
                fallback_used=False,
                replan_count=0,
                latency_ms=latency_ms,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

    def _build_settings(self, case: GraphDemoEvalCase) -> Settings:
        mcp_enabled = (
            self._default_mcp_enabled
            if self._default_mcp_enabled is not None
            else case.mcp_enabled
        )
        policy_strategy = (
            self._default_policy_strategy
            or case.policy_strategy
            or "planner_hint_first"
        )
        eval_mode = self._eval_mode
        if (
            eval_mode == "deterministic_eval"
            and policy_strategy in POLICY_STRATEGIES_NEEDING_REAL_EVAL_MODE
        ):
            # Allow mcp_first / reliability strategies in graph eval without changing core settings.
            eval_mode = "real_llm_eval"

        return Settings(
            llm_provider=self._llm_provider,  # type: ignore[arg-type]
            eval_mode=eval_mode,  # type: ignore[arg-type]
            mcp_enabled=mcp_enabled,
            tool_policy_strategy=policy_strategy,  # type: ignore[arg-type]
            tool_policy_enabled=True,
            persistence_enabled=False,
            metrics_enabled=False,
            plan_critic_replan_enabled=case.allow_replan,
            plan_execution_critic_enabled=case.allow_replan,
        )

    async def _build_registry(
        self,
        case: GraphDemoEvalCase,
        settings: Settings,
    ) -> ToolRegistry:
        registry = ToolRegistry.default()
        mcp_enabled = settings.mcp_enabled
        if mcp_enabled:
            provider = MCPToolProvider(FakeMCPClient(), tool_prefix=settings.mcp_tool_prefix)
            await provider.register_all(registry)
        return registry

    def _build_graph_runner(
        self,
        settings: Settings,
        registry: ToolRegistry,
        case: GraphDemoEvalCase,
    ) -> GraphRuntimeRunner:
        _registry, _memory, _manager, _executor, _orchestrator, _router, graph_runner, *_rest = (
            bootstrap_runtime(settings, tool_registry=registry, mcp_wire=False)
        )
        policy_strategy = (
            self._default_policy_strategy
            or case.policy_strategy
            or settings.tool_policy_strategy
        )
        if policy_strategy in POLICY_STRATEGIES_NEEDING_REAL_EVAL_MODE:
            engine = ToolPolicyEngine(
                registry,
                strategy=policy_strategy,
                mcp_enabled=settings.mcp_enabled,
                mcp_tool_prefix=settings.mcp_tool_prefix,
                settings=settings,
            )
            graph_runner._deps.plan_executor._tool_policy_engine = engine
        return graph_runner

    def _score_response(
        self,
        case: GraphDemoEvalCase,
        response: GraphExecuteResponse,
        *,
        registry: ToolRegistry,
        latency_ms: float,
    ) -> GraphDemoEvalResult:
        extracted = self._extract_execution(response)
        actual_tools = extracted.tools
        actual_families = sorted(
            {tool_family(name).value for name in actual_tools if tool_family(name).value != "unknown"},
        )
        actual_providers = extracted.providers
        fallback_used = self._detect_fallback(response)
        replan_count = max(
            len(response.replan_history),
            int(response.state_summary.get("replan_attempts") or 0),
        )
        plan_validity = self._check_plan_validity(response, registry, actual_tools)
        execution_success = self._check_execution_success(response, actual_tools)
        return self._scorer.score_case(
            case,
            execution_success=execution_success,
            plan_validity=plan_validity,
            final_result=response.final_result,
            actual_tools=actual_tools,
            actual_tool_families=actual_families,
            actual_providers=actual_providers,
            fallback_used=fallback_used,
            replan_count=replan_count,
            latency_ms=latency_ms,
            execution_id=response.execution_id,
            tool_extraction_source=extracted.source,
        )

    @staticmethod
    def _policy_trace_entries(response: GraphExecuteResponse) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        summary_trace = response.state_summary.get("tool_policy_trace") or []
        if isinstance(summary_trace, list):
            entries.extend(entry for entry in summary_trace if isinstance(entry, dict))

        observations = response.state_summary.get("observations") or {}
        if isinstance(observations, dict):
            obs_trace = observations.get("tool_policy_trace") or []
            if isinstance(obs_trace, list):
                entries.extend(entry for entry in obs_trace if isinstance(entry, dict))
        return entries

    @staticmethod
    def _normalize_provider(value: Any, tool_name: str) -> str:
        if isinstance(value, str) and value:
            return value.lower()
        return tool_provider(tool_name).value

    @classmethod
    def _extract_execution(cls, response: GraphExecuteResponse) -> _ExtractedExecution:
        trace_tools: list[str] = []
        trace_providers: list[str] = []
        for entry in response.execution_trace:
            if entry.tool_name and entry.success:
                trace_tools.append(entry.tool_name)
                trace_providers.append(tool_provider(entry.tool_name).value)
        if trace_tools:
            return _ExtractedExecution(trace_tools, trace_providers, "execution_trace")

        policy_tools: list[str] = []
        policy_providers: list[str] = []
        for entry in cls._policy_trace_entries(response):
            selected = entry.get("selected_tool")
            if not selected:
                continue
            tool_name = str(selected)
            policy_tools.append(tool_name)
            policy_providers.append(
                cls._normalize_provider(entry.get("selected_provider"), tool_name),
            )
        if policy_tools:
            return _ExtractedExecution(policy_tools, policy_providers, "tool_policy_trace")

        ctx = response.state_summary.get("global_context") or {}
        tool_outputs = ctx.get("tool_outputs") or {}
        if isinstance(tool_outputs, dict) and tool_outputs:
            output_tools = list(tool_outputs.keys())
            output_providers = [tool_provider(name).value for name in output_tools]
            return _ExtractedExecution(output_tools, output_providers, "global_context.tool_outputs")

        if response.plan is not None:
            plan_tools = [step.tool_hint for step in response.plan.steps if step.tool_hint]
            plan_providers = [tool_provider(name).value for name in plan_tools]
            if plan_tools:
                return _ExtractedExecution(plan_tools, plan_providers, "plan.tool_hint")

        return _ExtractedExecution([], [], "none")

    @staticmethod
    def _extract_actual_tools(response: GraphExecuteResponse) -> list[str]:
        return GraphDemoEvaluator._extract_execution(response).tools

    @staticmethod
    def _detect_fallback(response: GraphExecuteResponse) -> bool:
        for entry in response.execution_trace:
            recovery = entry.recovery_action or ""
            if "fallback" in recovery.lower():
                return True
        trace = response.state_summary.get("tool_policy_trace") or []
        for entry in trace:
            if isinstance(entry, dict) and entry.get("fallback_used"):
                return True
        return False

    @staticmethod
    def _check_plan_validity(
        response: GraphExecuteResponse,
        registry: ToolRegistry,
        actual_tools: list[str],
    ) -> bool:
        if response.plan is None or not response.plan.steps:
            return not actual_tools
        report = PlanValidator(registry).validate(response.plan)
        return report.success

    @staticmethod
    def _check_execution_success(
        response: GraphExecuteResponse,
        actual_tools: list[str],
    ) -> bool:
        if not response.final_result.strip():
            return False
        tool_entries = [entry for entry in response.execution_trace if entry.tool_name]
        if tool_entries and not all(entry.success for entry in tool_entries):
            return False
        if response.plan is None and actual_tools:
            return False
        if not actual_tools and not tool_entries:
            ctx = response.state_summary.get("global_context") or {}
            tool_outputs = ctx.get("tool_outputs") or {}
            if not tool_outputs and response.plan and any(step.tool_hint for step in response.plan.steps):
                return False
        return True


def apply_deterministic_eval_env() -> None:
    """Force deterministic eval environment variables."""
    os.environ["EVAL_MODE"] = "deterministic_eval"
    os.environ["LLM_PROVIDER"] = "rule_based"
    from config.settings import get_settings

    get_settings.cache_clear()
