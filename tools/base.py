"""Abstract tool interface with OpenAI-compatible schema generation."""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

from schemas.tool import ToolDefinition


class BaseTool(ABC):
    """Base class for callable tools exposed to agents."""

    name: str
    description: str
    input_schema: type[BaseModel]

    @abstractmethod
    async def run(self, args: dict[str, Any]) -> Any:
        """Execute the tool with validated arguments and return the result."""

    async def execute(self, **kwargs: Any) -> Any:
        """Backward-compatible entry point."""
        return await self.run(kwargs)

    def validate_args(self, args: dict[str, Any]) -> BaseModel:
        return self.input_schema.model_validate(args)

    def get_definition(self) -> ToolDefinition:
        schema = self.input_schema.model_json_schema()
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": schema.get("properties", {}),
                "required": schema.get("required", []),
            },
        )

    def to_openai_schema(self) -> dict[str, Any]:
        return self.get_definition().to_openai_schema()
