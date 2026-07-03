"""Tool execution node for LangGraph workflows."""

from graph.state import GraphState
from schemas.tool import ToolCall
from tools.executor import ToolExecutor


async def tool_node(state: GraphState, executor: ToolExecutor) -> GraphState:
    """Execute pending tool calls and append results to state."""
    pending = state.get("metadata", {}).get("pending_tool_calls", [])
    if not pending:
        return state

    calls = [ToolCall.model_validate(item) for item in pending]
    results = await executor.execute_batch(calls)

    return {
        **state,
        "tool_results": [
            *state.get("tool_results", []),
            *[result.model_dump() for result in results],
        ],
        "metadata": {
            **state.get("metadata", {}),
            "pending_tool_calls": [],
        },
    }
