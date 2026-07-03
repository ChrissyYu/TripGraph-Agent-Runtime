"""Stdio MCP client for local tool servers."""

from __future__ import annotations

import json
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from config.settings import Settings, get_settings
from core.logging import get_logger

logger = get_logger(__name__)

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except ImportError:  # pragma: no cover - optional dependency
    ClientSession = None  # type: ignore[assignment,misc]
    StdioServerParameters = None  # type: ignore[assignment,misc]
    stdio_client = None  # type: ignore[assignment]


class MCPClientError(RuntimeError):
    """Raised when MCP transport or protocol operations fail."""


class MCPStdioClient:
    """Long-lived stdio MCP client used by MCPToolAdapter."""

    def __init__(
        self,
        *,
        command: str,
        args: list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        if ClientSession is None or stdio_client is None:
            raise MCPClientError(
                "mcp package is not installed. Install with: pip install mcp",
            )
        self._command = command
        self._args = args
        self._cwd = cwd
        self._env = env
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> MCPStdioClient:
        cfg = settings or get_settings()
        command = cfg.mcp_server_command
        args = list(cfg.mcp_server_args)
        if not args:
            raise MCPClientError("MCP_SERVER_ARGS is empty")
        resolved_args = [_resolve_server_path(arg) for arg in args]
        return cls(command=command, args=resolved_args)

    @property
    def connected(self) -> bool:
        return self._session is not None

    async def connect(self) -> None:
        if self._session is not None:
            return
        params = StdioServerParameters(
            command=self._command,
            args=self._args,
            cwd=self._cwd,
            env=self._env,
        )
        stack = AsyncExitStack()
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._stack = stack
        self._session = session
        logger.info(
            "MCP stdio client connected: command=%s args=%s",
            self._command,
            self._args,
        )

    async def disconnect(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self._session = None

    async def list_tools(self) -> list[dict[str, Any]]:
        await self.connect()
        assert self._session is not None
        response = await self._session.list_tools()
        tools: list[dict[str, Any]] = []
        for item in response.tools:
            tools.append(
                {
                    "name": item.name,
                    "description": item.description or "",
                    "input_schema": item.inputSchema or {"type": "object", "properties": {}},
                },
            )
        return tools

    async def call_tool(self, tool_name: str, args: dict[str, Any]) -> Any:
        await self.connect()
        assert self._session is not None
        result = await self._session.call_tool(tool_name, args)
        return _parse_tool_result(result)


def _resolve_server_path(arg: str) -> str:
    path = Path(arg)
    if path.is_file():
        return str(path.resolve())
    repo_root = Path(__file__).resolve().parents[2]
    candidate = repo_root / arg
    if candidate.is_file():
        return str(candidate)
    return arg


def _parse_tool_result(result: Any) -> Any:
    if getattr(result, "structuredContent", None) is not None:
        return result.structuredContent
    content = getattr(result, "content", None) or []
    texts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if text:
            texts.append(text)
    if not texts:
        return {}
    combined = "\n".join(texts).strip()
    try:
        return json.loads(combined)
    except json.JSONDecodeError:
        return {"text": combined}


def default_python_command() -> str:
    return sys.executable
