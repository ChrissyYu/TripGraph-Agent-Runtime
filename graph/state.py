"""Shared LangGraph state definition.

When LangGraph is installed, replace `messages` reducer with:
    from langgraph.graph.message import add_messages
    messages: Annotated[list[Any], add_messages]
"""

from typing import Any, TypedDict


class GraphState(TypedDict, total=False):
    """State passed between LangGraph nodes."""

    session_id: str
    task_id: str
    query: str
    messages: list[Any]
    current_agent: str
    tool_results: list[dict[str, Any]]
    final_output: str
    metadata: dict[str, Any]
