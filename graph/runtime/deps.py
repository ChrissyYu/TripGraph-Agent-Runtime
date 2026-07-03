"""Runtime node dependencies."""

from __future__ import annotations

from dataclasses import dataclass

from memory.composite import CompositeMemory
from agents.planner import PlannerAgent
from plan.execution_critic import ExecutionCritic
from plan.executor import PlanExecutor
from plan.replanning_controller import ReplanningController
from plan.resolver import StepToolResolver
from plan.validator import PlanValidator
from tools.policy.engine import ToolPolicyEngine
from tools.policy.trace import ToolPolicyTracer
from tools.router import ToolSelectionRouter


@dataclass
class RuntimeDependencies:
    planner: PlannerAgent
    tool_router: ToolSelectionRouter
    plan_executor: PlanExecutor
    critic: ExecutionCritic
    replanner: ReplanningController
    resolver: StepToolResolver
    validator: PlanValidator
    memory_store: CompositeMemory | None = None
    tool_policy_engine: ToolPolicyEngine | None = None
    tool_policy_tracer: ToolPolicyTracer | None = None
