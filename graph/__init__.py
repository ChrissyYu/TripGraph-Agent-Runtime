"""LangGraph workflow engine integration (interface layer)."""

from graph.builder import GraphBuilder
from graph.runner import GraphRunner
from graph.state import GraphState

__all__ = [
    "GraphBuilder",
    "GraphRunner",
    "GraphState",
    "AgentState",
    "GraphRuntimeRunner",
    "AgentWorkflowBuilder",
]


def __getattr__(name: str):
    if name in ("AgentState", "GraphRuntimeRunner", "AgentWorkflowBuilder"):
        from graph import runtime

        return getattr(runtime, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
