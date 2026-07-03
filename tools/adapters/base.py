"""Base adapter for wrapping external tool sources as BaseTool instances."""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, create_model

from tools.base import BaseTool
from tools.registry import ToolRegistry


class ExternalToolAdapter(ABC):
    """Wrap a single external tool (e.g. from an MCP server) as a BaseTool."""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        ...

    @property
    @abstractmethod
    def input_schema(self) -> type[BaseModel]:
        ...

    @abstractmethod
    async def invoke(self, args: dict[str, Any]) -> Any:
        """Call the external tool backend."""

    def to_base_tool(self) -> BaseTool:
        adapter = self

        class AdaptedTool(BaseTool):
            name = adapter.name
            description = adapter.description
            input_schema = adapter.input_schema

            async def run(self, args: dict[str, Any]) -> Any:
                return await adapter.invoke(args)

        return AdaptedTool()


class ExternalToolProvider(ABC):
    """Discover and register tools from an external source (MCP server, plugin, etc.)."""

    @abstractmethod
    async def list_tools(self) -> list[ExternalToolAdapter]:
        ...

    async def register_all(self, registry: ToolRegistry) -> int:
        tools = await self.list_tools()
        count = 0
        for adapter in tools:
            if not registry.has(adapter.name):
                registry.register(adapter.to_base_tool())
                count += 1
        return count


def schema_from_json_schema(name: str, json_schema: dict[str, Any]) -> type[BaseModel]:
    """Build a dynamic Pydantic model from a JSON Schema (for MCP tool params)."""
    properties = json_schema.get("properties", {})
    required = set(json_schema.get("required", []))
    fields: dict[str, Any] = {}
    for field_name, field_schema in properties.items():
        field_type = Any
        default = ... if field_name in required else None
        fields[field_name] = (field_type, default)
    return create_model(f"{name.title()}Input", **fields)
