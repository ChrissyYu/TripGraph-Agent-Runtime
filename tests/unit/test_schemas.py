"""Tests for pydantic schemas."""

from schemas.tool import ToolDefinition


def test_tool_definition_openai_format() -> None:
    definition = ToolDefinition(
        name="search",
        description="Search the web",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    )
    schema = definition.to_openai_schema()
    assert schema["function"]["name"] == "search"
    assert "query" in schema["function"]["parameters"]["properties"]
