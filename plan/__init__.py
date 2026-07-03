"""Plan execution package."""

from plan.executor import PlanExecutor
from plan.failure_policy import FailurePolicy, PlanFailureConfig
from plan.resolver import StepToolResolver
from plan.state import PlanState
from plan.validator import PlanValidator

__all__ = [
    "ContextCompressionConfig",
    "ContextCompressor",
    "ExecutionCritic",
    "ExecutionCriticConfig",
    "FailurePolicy",
    "PlanExecutionGraph",
    "PlanExecutor",
    "PlanFailureConfig",
    "PlanOrchestrator",
    "PlanState",
    "PlanValidator",
    "ReplanningConfig",
    "ReplanningController",
    "ReplanningOutcome",
    "StepToolResolver",
]


def __getattr__(name: str):
    if name == "PlanOrchestrator":
        from plan.orchestrator import PlanOrchestrator

        return PlanOrchestrator
    if name == "PlanExecutionGraph":
        from plan.graph import PlanExecutionGraph

        return PlanExecutionGraph
    if name in ("ContextCompressionConfig", "ContextCompressor"):
        from plan import context_compression

        return getattr(context_compression, name)
    if name in ("ExecutionCritic", "ExecutionCriticConfig"):
        from plan import execution_critic

        return getattr(execution_critic, name)
    if name in ("ReplanningController", "ReplanningConfig", "ReplanningOutcome"):
        from plan import replanning_controller

        return getattr(replanning_controller, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
