"""Manager routing node for LangGraph workflows."""

from graph.state import GraphState


async def manager_node(state: GraphState) -> GraphState:
    """Route the query to a specialist agent.

    Replace heuristic routing with LLM-based delegation when wiring LangGraph.
    """
    return {
        **state,
        "current_agent": state.get("current_agent") or "example_specialist",
        "metadata": {
            **state.get("metadata", {}),
            "routed_by": "manager_node",
        },
    }
