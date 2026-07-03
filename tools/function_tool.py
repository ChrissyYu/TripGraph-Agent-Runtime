"""Wrap plain callables as BaseTool instances."""

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel

from tools.base import BaseTool


class FunctionTool(BaseTool):
    """Adapter that exposes a Python function as a BaseTool."""

    def __init__(
        self,
        fn: Callable[..., Any | Awaitable[Any]],
        name: str,
        description: str,
        input_schema: type[BaseModel],
    ) -> None:
        self._fn = fn
        self.name = name
        self.description = description
        self.input_schema = input_schema

    async def run(self, args: dict[str, Any]) -> Any:
        validated = self.validate_args(args)
        kwargs = validated.model_dump()
        result = self._fn(**kwargs)
        if inspect.isawaitable(result):
            return await result
        return result
