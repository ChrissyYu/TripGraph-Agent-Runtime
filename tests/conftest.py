"""Shared pytest fixtures."""

from __future__ import annotations

import os

# Isolate pytest from developer .env (Qwen / real LLM must never run in CI).
os.environ["EVAL_MODE"] = "deterministic_eval"
os.environ["LLM_PROVIDER"] = "rule_based"
os.environ["MCP_ENABLED"] = "false"

import pytest
from httpx import ASGITransport, AsyncClient

from agents.manager import ManagerAgent
from agents.specialists.example_specialist import ExampleSpecialistAgent
from app.main import create_app
from memory.composite import CompositeMemory
from tools.registry import ToolRegistry


@pytest.fixture(autouse=True)
def _isolate_llm_env(monkeypatch) -> None:
    """Re-apply deterministic LLM settings before each test."""
    monkeypatch.setenv("EVAL_MODE", "deterministic_eval")
    monkeypatch.setenv("LLM_PROVIDER", "rule_based")
    monkeypatch.setenv("MCP_ENABLED", "false")
    from config.settings import get_settings

    get_settings.cache_clear()
    yield  # type: ignore[misc]
    get_settings.cache_clear()


@pytest.fixture
def tool_registry() -> ToolRegistry:
    return ToolRegistry.default()


@pytest.fixture
def manager_agent(tool_registry: ToolRegistry) -> ManagerAgent:
    manager = ManagerAgent(tool_registry=tool_registry)
    manager.register_specialist(ExampleSpecialistAgent(tool_registry=tool_registry))
    return manager


@pytest.fixture
def memory_store(tmp_path, monkeypatch) -> CompositeMemory:
    monkeypatch.setenv("LONG_TERM_STORE_PATH", str(tmp_path / "memory"))
    from config.settings import get_settings

    get_settings.cache_clear()
    return CompositeMemory()


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def async_client(app):
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
