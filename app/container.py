"""Application dependency container and lifecycle."""

from __future__ import annotations

from dataclasses import dataclass

from agents.manager import ManagerAgent
from app.bootstrap import bootstrap_runtime
from app.services.eval_service import EvalService
from app.services.execution_service import ExecutionService
from app.services.graph_service import GraphService
from app.services.health_service import HealthService
from app.services.plan_service import PlanService
from config.settings import Settings, get_settings
from core.logging import setup_logging
from eval.bootstrap import EvalBundle
from graph.runtime.runner import GraphRuntimeRunner
from memory.composite import CompositeMemory
from observability.bootstrap import ObservabilityBundle
from persistence.bootstrap import PersistenceBundle
from plan.orchestrator import PlanOrchestrator
from tools.executor import ToolExecutor
from tools.mcp.bootstrap import shutdown_mcp_client
from tools.registry import ToolRegistry
from tools.router import ToolSelectionRouter


@dataclass
class ApplicationContainer:
    settings: Settings
    tool_registry: ToolRegistry
    memory_store: CompositeMemory
    manager_agent: ManagerAgent
    tool_executor: ToolExecutor
    plan_orchestrator: PlanOrchestrator
    tool_router: ToolSelectionRouter
    graph_runner: GraphRuntimeRunner
    persistence: PersistenceBundle
    observability: ObservabilityBundle
    eval_bundle: EvalBundle
    graph_service: GraphService
    plan_service: PlanService
    execution_service: ExecutionService
    eval_service: EvalService
    health_service: HealthService

    @classmethod
    def create(cls, settings: Settings | None = None) -> ApplicationContainer:
        cfg = settings or get_settings()
        (
            tool_registry,
            memory_store,
            manager,
            tool_executor,
            plan_orchestrator,
            tool_router,
            graph_runner,
            persistence,
            observability,
            eval_bundle,
        ) = bootstrap_runtime(cfg)

        return cls(
            settings=cfg,
            tool_registry=tool_registry,
            memory_store=memory_store,
            manager_agent=manager,
            tool_executor=tool_executor,
            plan_orchestrator=plan_orchestrator,
            tool_router=tool_router,
            graph_runner=graph_runner,
            persistence=persistence,
            observability=observability,
            eval_bundle=eval_bundle,
            graph_service=GraphService(graph_runner),
            plan_service=PlanService(plan_orchestrator),
            execution_service=ExecutionService(
                replay_service=persistence.replay_service,
                profile_service=observability.profile_service,
                persistence_enabled=persistence.enabled,
                metrics_enabled=observability.enabled,
            ),
            eval_service=EvalService(eval_bundle),
            health_service=HealthService(
                cfg,
                persistence=persistence,
                observability=observability,
                eval_bundle=eval_bundle,
                graph_runner=graph_runner,
                tool_registry=tool_registry,
                plan_orchestrator=plan_orchestrator,
            ),
        )

    async def startup(self) -> None:
        setup_logging(
            "DEBUG" if self.settings.debug else "INFO",
            json_format=(
                self.settings.enable_json_log
                or self.settings.log_json
                or self.settings.metrics_enabled
            ),
        )
        if self.persistence.writer is not None:
            await self.persistence.writer.start()
        if self.observability.collector is not None:
            await self.observability.collector.start()

    async def shutdown(self) -> None:
        await shutdown_mcp_client()
        if self.observability.collector is not None:
            await self.observability.collector.stop()
        if self.persistence.writer is not None:
            await self.persistence.writer.stop()

    def bind_app_state(self, app) -> None:
        app.state.container = self
        app.state.tool_registry = self.tool_registry
        app.state.memory_store = self.memory_store
        app.state.manager_agent = self.manager_agent
        app.state.tool_executor = self.tool_executor
        app.state.tool_router = self.tool_router
        app.state.plan_orchestrator = self.plan_orchestrator
        app.state.graph_runner = self.graph_runner
        app.state.execution_recorder = self.persistence.recorder
        app.state.replay_service = self.persistence.replay_service
        app.state.persistence = self.persistence
        app.state.observability = self.observability
        app.state.profile_service = self.observability.profile_service
        app.state.eval_bundle = self.eval_bundle
        app.state.graph_service = self.graph_service
        app.state.plan_service = self.plan_service
        app.state.execution_service = self.execution_service
        app.state.eval_service = self.eval_service
        app.state.health_service = self.health_service
