"""Bootstrap helpers for registering MCP tools into ToolRegistry."""

from __future__ import annotations

import asyncio

from config.settings import Settings, get_settings
from core.logging import get_logger
from tools.mcp.client import MCPClientError, MCPStdioClient
from tools.registry import ToolRegistry

logger = get_logger(__name__)

_active_client: MCPStdioClient | None = None


def get_active_mcp_client() -> MCPStdioClient | None:
    return _active_client


async def wire_mcp_tools(
    registry: ToolRegistry,
    settings: Settings | None = None,
    *,
    client: MCPStdioClient | None = None,
) -> MCPStdioClient | None:
    """Connect to MCP server and register discovered tools."""
    global _active_client

    cfg = settings or get_settings()
    if not cfg.mcp_enabled:
        return None

    if (
        client is None
        and _active_client is not None
        and isinstance(_active_client, MCPStdioClient)
        and _active_client.connected
    ):
        return _active_client

    from tools.adapters.mcp import MCPToolProvider

    try:
        mcp_client = client or MCPStdioClient.from_settings(cfg)
        provider = MCPToolProvider(mcp_client, tool_prefix=cfg.mcp_tool_prefix)
        count = await provider.register_all(registry)
        _active_client = mcp_client
        logger.info("MCP tools registered: count=%d names=%s", count, provider.registered_names)
        return mcp_client
    except Exception as exc:
        if cfg.mcp_required:
            raise MCPClientError(f"MCP is required but connection failed: {exc}") from exc
        logger.warning("MCP tool registration skipped: %s", exc)
        return None


def wire_mcp_tools_sync(
    registry: ToolRegistry,
    settings: Settings | None = None,
    *,
    client: MCPStdioClient | None = None,
) -> MCPStdioClient | None:
    """Synchronous wrapper used by bootstrap_runtime and smoke scripts."""
    coro = wire_mcp_tools(registry, settings, client=client)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(asyncio.run, coro)
        return future.result()


async def shutdown_mcp_client() -> None:
    global _active_client
    if _active_client is not None:
        disconnect = getattr(_active_client, "disconnect", None)
        if callable(disconnect):
            await disconnect()
        _active_client = None
