"""FastAPI dependency providers."""

from fastapi import Request

from agents.manager import ManagerAgent
from config.settings import Settings, get_settings
from memory.composite import CompositeMemory
from tools.registry import ToolRegistry


def get_app_settings() -> Settings:
    return get_settings()


def get_tool_registry(request: Request) -> ToolRegistry:
    return request.app.state.tool_registry


def get_memory_store(request: Request) -> CompositeMemory:
    return request.app.state.memory_store


def get_manager_agent(request: Request) -> ManagerAgent:
    return request.app.state.manager_agent


async def get_request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")
