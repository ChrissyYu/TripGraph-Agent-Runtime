"""Tests for ToolRegistry."""

import pytest

from tools.registry import ToolRegistry


def test_auto_discover_builtin_tools(tool_registry: ToolRegistry) -> None:
    names = tool_registry.list_names()
    assert "echo" in names
    assert "weather" in names
    assert "map" in names
    assert "budget" in names


def test_duplicate_registration_raises(tool_registry: ToolRegistry) -> None:
    weather = tool_registry.get("weather")
    with pytest.raises(ValueError, match="already registered"):
        tool_registry.register(weather)


def test_openai_schema_export(tool_registry: ToolRegistry) -> None:
    schemas = tool_registry.to_openai_schemas()
    names = {s["function"]["name"] for s in schemas}
    assert "weather" in names
    assert all(s["type"] == "function" for s in schemas)


def test_tool_definitions_have_parameters(tool_registry: ToolRegistry) -> None:
    weather_def = next(d for d in tool_registry.get_definitions() if d.name == "weather")
    assert "city" in weather_def.parameters["properties"]
