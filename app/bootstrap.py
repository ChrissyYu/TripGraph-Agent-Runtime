"""Application bootstrap and dependency wiring."""

from __future__ import annotations

from agents.manager import ManagerAgent
from agents.planner import PlannerAgent
from agents.specialists.example_specialist import ExampleSpecialistAgent
from config.settings import Settings
from eval.bootstrap import EvalBundle, build_eval_system
from graph.runtime.deps import RuntimeDependencies
from graph.runtime.runner import GraphRuntimeRunner
from memory.composite import CompositeMemory
from observability.bootstrap import ObservabilityBundle, build_observability, wire_tool_tracer
from persistence.bootstrap import PersistenceBundle, bind_runner, build_persistence
from plan.execution_critic import ExecutionCritic
from plan.executor import PlanExecutor
from plan.orchestrator import PlanOrchestrator
from plan.replanning_controller import ReplanningController
from plan.resolver import StepToolResolver
from plan.validator import PlanValidator
from tools.executor import ToolExecutor
from tools.mcp.bootstrap import shutdown_mcp_client, wire_mcp_tools_sync
from tools.policy.bootstrap import build_tool_policy_engine, build_tool_policy_tracer
from tools.registry import ToolRegistry
from tools.router import ToolSelectionRouter


def create_planner(
    settings: Settings,
    tool_registry: ToolRegistry,
    observability: ObservabilityBundle,
) -> PlannerAgent:
    from core.llm.factory import create_runtime_llm

    llm = create_runtime_llm(settings, observability)
    return PlannerAgent(llm, tool_registry=tool_registry, settings=settings)


def bootstrap_runtime(
    settings: Settings,
    *,
    tool_registry: ToolRegistry | None = None,
    mcp_wire: bool = True,
) -> tuple[
    ToolRegistry,
    CompositeMemory,
    ManagerAgent,
    ToolExecutor,
    PlanOrchestrator,
    ToolSelectionRouter,
    GraphRuntimeRunner,
    PersistenceBundle,
    ObservabilityBundle,
    EvalBundle,
]:
    tool_registry = tool_registry or ToolRegistry.default()
    if mcp_wire and settings.mcp_enabled:
        wire_mcp_tools_sync(tool_registry, settings)
    persistence = build_persistence(settings)
    observability = build_observability(settings)
    tool_executor = ToolExecutor(tool_registry)

    tool_callbacks = []
    if persistence.enabled and persistence.recorder is not None:
        tool_callbacks.append(persistence.recorder.on_tool_record)
    if observability.enabled and observability.observer is not None:
        tool_callbacks.append(observability.observer.on_tool_record)
    wire_tool_tracer(tool_executor, callbacks=tool_callbacks)

    tool_router = ToolSelectionRouter(tool_registry)
    tool_policy_engine = build_tool_policy_engine(tool_registry, settings)
    tool_policy_tracer = build_tool_policy_tracer(settings)
    memory_store = CompositeMemory()
    manager = ManagerAgent(tool_registry=tool_registry)
    manager.register_specialist(ExampleSpecialistAgent(tool_registry=tool_registry))
    planner = create_planner(settings, tool_registry, observability)
    validator = PlanValidator(tool_registry)
    resolver = StepToolResolver()
    plan_executor = PlanExecutor(
        tool_executor,
        planner=planner,
        validator=validator,
        resolver=resolver,
        summarizer=planner.llm,
        settings=settings,
        tool_policy_engine=tool_policy_engine,
        tool_policy_tracer=tool_policy_tracer,
    )
    plan_orchestrator = PlanOrchestrator(
        planner=planner,
        tool_executor=tool_executor,
        plan_executor=plan_executor,
        resolver=resolver,
        validator=validator,
    )
    graph_deps = RuntimeDependencies(
        planner=planner,
        tool_router=tool_router,
        plan_executor=plan_executor,
        critic=ExecutionCritic(planner.llm),
        replanner=ReplanningController(planner, validator),
        resolver=resolver,
        validator=validator,
        memory_store=memory_store,
        tool_policy_engine=tool_policy_engine,
        tool_policy_tracer=tool_policy_tracer,
    )
    graph_runner = GraphRuntimeRunner(
        graph_deps,
        max_iterations=settings.graph_max_iterations,
        recorder=persistence.recorder,
        metrics_observer=observability.observer,
    )
    bind_runner(persistence, graph_runner)
    eval_bundle = build_eval_system(settings, graph_runner, observability)

    return (
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
    )
