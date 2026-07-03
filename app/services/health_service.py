"""Health and readiness checks."""

from __future__ import annotations

import time
from typing import Any

from config.settings import Settings
from core.llm.base import LLMMessage
from eval.bootstrap import EvalBundle
from graph.runtime.runner import GraphRuntimeRunner
from observability.bootstrap import ObservabilityBundle
from persistence.bootstrap import PersistenceBundle
from plan.orchestrator import PlanOrchestrator
from tools.registry import ToolRegistry


class HealthService:
    def __init__(
        self,
        settings: Settings,
        *,
        persistence: PersistenceBundle,
        observability: ObservabilityBundle,
        eval_bundle: EvalBundle,
        graph_runner: GraphRuntimeRunner,
        tool_registry: ToolRegistry,
        plan_orchestrator: PlanOrchestrator,
    ) -> None:
        self._settings = settings
        self._persistence = persistence
        self._observability = observability
        self._eval_bundle = eval_bundle
        self._graph_runner = graph_runner
        self._tool_registry = tool_registry
        self._plan_orchestrator = plan_orchestrator

    def health(self) -> dict:
        return {
            "status": "ok",
            "app": self._settings.app_name,
            "version": self._settings.app_version,
            "environment": self._settings.environment,
        }

    def readiness(self) -> dict:
        return {
            **self.health(),
            "ready": True,
            "features": {
                "graph_runtime": self._settings.graph_runtime_enabled,
                "persistence": self._persistence.enabled,
                "metrics": self._observability.enabled,
                "eval": self._eval_bundle.enabled,
            },
        }

    async def detailed(self) -> dict[str, Any]:
        components = {
            "llm": await self._check_llm(),
            "graph_runtime": self._check_graph_runtime(),
            "tool_registry": self._check_tool_registry(),
            "persistence": await self._check_persistence(),
            "observability": self._check_observability(),
        }
        return {
            "status": _aggregate_status(components),
            "components": components,
            "version": self._settings.app_version,
            "environment": self._settings.environment,
        }

    async def _check_llm(self) -> dict[str, Any]:
        llm = self._plan_orchestrator.planner.llm
        provider = "openai" if self._settings.openai_api_key else "rule_based"
        started = time.perf_counter()
        try:
            await llm.complete(
                [LLMMessage(role="user", content="health ping")],
                response_json=False,
            )
            latency_ms = round((time.perf_counter() - started) * 1000, 3)
            return {
                "status": "healthy",
                "provider": provider,
                "model": self._settings.openai_model,
                "latency_ms": latency_ms,
            }
        except Exception as exc:
            return {
                "status": "unhealthy",
                "provider": provider,
                "model": self._settings.openai_model,
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "error": str(exc),
            }

    def _check_graph_runtime(self) -> dict[str, Any]:
        if not self._settings.graph_runtime_enabled:
            return {"status": "disabled", "enabled": False}

        try:
            graph = self._graph_runner.workflow
            return {
                "status": "healthy",
                "enabled": True,
                "graph_id": graph.graph_id,
                "max_iterations": self._settings.graph_max_iterations,
            }
        except Exception as exc:
            return {
                "status": "unhealthy",
                "enabled": True,
                "error": str(exc),
            }

    def _check_tool_registry(self) -> dict[str, Any]:
        tools = self._tool_registry.list_names()
        return {
            "status": "healthy" if tools else "degraded",
            "tool_count": len(tools),
            "tools": tools,
        }

    async def _check_persistence(self) -> dict[str, Any]:
        if not self._persistence.enabled:
            return {"status": "disabled", "enabled": False}

        client = self._persistence.client
        if client is None:
            return {"status": "unhealthy", "enabled": True, "error": "client not initialized"}

        try:
            row = await client.fetchone("SELECT 1 AS ok")
            connected = row is not None and row["ok"] == 1
            return {
                "status": "healthy" if connected else "unhealthy",
                "enabled": True,
                "db_path": str(client.path),
                "writer_active": self._persistence.writer is not None,
            }
        except Exception as exc:
            return {
                "status": "unhealthy",
                "enabled": True,
                "db_path": str(client.path),
                "error": str(exc),
            }

    def _check_observability(self) -> dict[str, Any]:
        if not self._observability.enabled:
            return {"status": "disabled", "enabled": False}

        collector = self._observability.collector
        store = self._observability.store
        return {
            "status": "healthy",
            "enabled": True,
            "metrics_collector_active": collector is not None and collector._worker is not None,
            "tracked_executions": len(store.list_execution_ids()) if store else 0,
            "profile_service": self._observability.profile_service is not None,
        }


def _aggregate_status(components: dict[str, dict[str, Any]]) -> str:
    statuses = [component.get("status", "unknown") for component in components.values()]
    if any(status == "unhealthy" for status in statuses):
        return "unhealthy"
    if any(status == "degraded" for status in statuses):
        return "degraded"
    if all(status in {"healthy", "disabled"} for status in statuses):
        return "healthy"
    return "degraded"
