"""Adapters for external tool providers (MCP, etc.)."""

from tools.adapters.base import (
    ExternalToolAdapter,
    ExternalToolProvider,
    schema_from_json_schema,
)
from tools.adapters.mcp import MCPToolAdapter, MCPToolProvider

__all__ = [
    "ExternalToolAdapter",
    "ExternalToolProvider",
    "MCPToolAdapter",
    "MCPToolProvider",
    "schema_from_json_schema",
]
