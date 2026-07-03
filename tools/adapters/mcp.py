"""MCP tool provider and adapter."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from tools.adapters.base import ExternalToolAdapter, ExternalToolProvider, schema_from_json_schema
from tools.mcp.client import MCPStdioClient
from tools.registry import ToolRegistry


class MCPToolAdapter(ExternalToolAdapter):
    """Wrap a single MCP tool as a BaseTool-compatible adapter."""

    def __init__(
        self,
        tool_name: str,
        tool_description: str,
        input_schema: type[BaseModel],
        client: MCPStdioClient,
    ) -> None:
        self._name = tool_name
        self._description = tool_description
        self._input_schema = input_schema
        self._client = client

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> type[BaseModel]:
        return self._input_schema

    async def invoke(self, args: dict[str, Any]) -> Any:
        return await self._client.call_tool(self._name, args)


class MCPToolProvider(ExternalToolProvider):
    """Discover tools from an MCP server and register them."""

    def __init__(
        self,
        client: MCPStdioClient,
        *,
        tool_prefix: str = "mcp_",
    ) -> None:
        self._client = client
        self._tool_prefix = tool_prefix
        self._registered_names: list[str] = []

    @property
    def registered_names(self) -> list[str]:
        return list(self._registered_names)

    async def list_tools(self) -> list[MCPToolAdapter]:
        raw_tools = await self._client.list_tools()
        adapters: list[MCPToolAdapter] = []
        for item in raw_tools:
            name = item["name"]
            if self._tool_prefix and not name.startswith(self._tool_prefix):
                continue
            schema_model = schema_from_json_schema(name, item["input_schema"])
            adapters.append(
                MCPToolAdapter(
                    tool_name=name,
                    tool_description=item.get("description", ""),
                    input_schema=schema_model,
                    client=self._client,
                ),
            )
        return adapters

    async def register_all(self, registry: ToolRegistry) -> int:
        self._registered_names = []
        tools = await self.list_tools()
        count = 0
        for adapter in tools:
            if registry.has(adapter.name):
                continue
            registry.register(adapter.to_base_tool())
            self._registered_names.append(adapter.name)
            count += 1
        return count


def parse_mcp_tool_payload(payload: Any) -> dict[str, Any]:
    """Normalize MCP tool call result to a dict (test helper)."""
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        return json.loads(payload)
    return {"value": payload}
