"""@tool decorator for declarative tool registration."""

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from pydantic import BaseModel

from tools.function_tool import FunctionTool

F = TypeVar("F", bound=Callable[..., Any | Awaitable[Any]])

_PENDING_TOOLS: list[FunctionTool] = []


def tool(
    *,
    name: str | None = None,
    description: str | None = None,
    input_schema: type[BaseModel],
) -> Callable[[F], F]:
    """Register a function as a tool.

    Example::

        @tool(name="weather", description="Get weather", input_schema=WeatherInput)
        async def weather_tool(city: str) -> dict:
            ...
    """

    def decorator(fn: F) -> F:
        tool_name = name or fn.__name__
        tool_desc = (description or fn.__doc__ or "").strip()
        instance = FunctionTool(
            fn=fn,
            name=tool_name,
            description=tool_desc,
            input_schema=input_schema,
        )
        _PENDING_TOOLS.append(instance)
        fn._tool_instance = instance  # type: ignore[attr-defined]
        return fn

    return decorator


def get_pending_tools() -> list[FunctionTool]:
    """Return a snapshot of tools registered via @tool (not yet in a registry)."""
    return list(_PENDING_TOOLS)


def clear_pending_tools() -> None:
    """Clear pending tools — useful in tests."""
    _PENDING_TOOLS.clear()
