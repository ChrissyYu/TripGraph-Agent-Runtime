"""Phase 4 graph-native agent runtime."""

from graph.runtime.agent_state import AgentState
from graph.runtime.core.graph import Graph
from graph.runtime.execution_policy import ExecutionPolicy
from graph.runtime.hierarchical import AgentNode, StateMapper, SubgraphNode
from graph.runtime.state_merge import MergeStrategy, merge_states
from graph.runtime.state_versioning import StateVersionManager
from graph.runtime.workflow import AgentWorkflowBuilder

__all__ = [
    "AgentNode",
    "AgentState",
    "AgentWorkflowBuilder",
    "ExecutionPolicy",
    "Graph",
    "GraphReplayDebugger",
    "GraphRuntimeRunner",
    "MergeStrategy",
    "StateMapper",
    "StateVersionManager",
    "SubgraphNode",
    "merge_states",
]


def __getattr__(name: str):
    if name == "GraphRuntimeRunner":
        from graph.runtime.runner import GraphRuntimeRunner

        return GraphRuntimeRunner
    if name == "GraphReplayDebugger":
        from graph.runtime.replay_debug import GraphReplayDebugger

        return GraphReplayDebugger
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
