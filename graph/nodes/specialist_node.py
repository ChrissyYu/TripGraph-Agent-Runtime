"""Specialist execution node for LangGraph workflows."""

from graph.state import GraphState


async def specialist_node(state: GraphState) -> GraphState:
    """Execute specialist logic within the graph."""
    query = state.get("query", "")
    agent = state.get("current_agent", "unknown")
    return {
        **state,
        "final_output": f"[{agent}] {query}",
        "metadata": {
            **state.get("metadata", {}),
            "executed_by": agent,
        },
    }
