"""Tool calling schemas (OpenAI function-calling compatible)."""

import json
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator


class LLMOutputKind(StrEnum):
    TOOL_CALL = "tool_call"
    FINAL = "final"
    PARSE_ERROR = "parse_error"


class ToolParameterSchema(BaseModel):
    """JSON Schema fragment for a single tool parameter."""

    type: Literal["string", "number", "integer", "boolean", "object", "array"]
    description: str | None = None
    enum: list[Any] | None = None


class ToolDefinition(BaseModel):
    """OpenAI-compatible tool definition."""

    name: str
    description: str
    parameters: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}, "required": []},
    )

    def to_openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolCall(BaseModel):
    call_id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolCallResult(BaseModel):
    call_id: str
    name: str
    output: Any
    success: bool = True
    error: str | None = None


class LLMToolCall(BaseModel):
    """Tool invocation format returned by LLM."""

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def parse(cls, raw: str | dict[str, Any]) -> "LLMToolCall":
        """Parse LLM output that may be a dict or JSON string."""
        if isinstance(raw, dict):
            return cls.model_validate(raw)

        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(line for line in lines if not line.startswith("```")).strip()

        return cls.model_validate(json.loads(text))

    @field_validator("tool")
    @classmethod
    def tool_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("tool name must not be empty")
        return value


class ToolObservation(BaseModel):
    """Structured observation returned after tool execution."""

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    output: Any = None
    success: bool = True
    error: str | None = None

    def to_message(self) -> str:
        """Format observation for feeding back to the LLM."""
        if not self.success:
            return f"Tool '{self.tool}' failed: {self.error}"
        return f"Tool '{self.tool}' observation: {json.dumps(self.output, ensure_ascii=False)}"


class LLMExecutionResult(BaseModel):
    """Unified result after processing raw LLM output."""

    kind: LLMOutputKind
    observation: ToolObservation | None = None
    final: str | None = None
    error: str | None = None
    raw: str | dict[str, Any] | None = None


class LLMOutputParser:
    """Parse raw LLM output into tool_call, final response, or parse error."""

    _FINAL_KEYS = ("final", "content", "message", "answer")

    @classmethod
    def parse(cls, raw: str | dict[str, Any]) -> LLMExecutionResult:
        if isinstance(raw, dict):
            return cls._parse_dict(raw, raw)

        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(line for line in lines if not line.startswith("```")).strip()

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            if text.startswith(("{", "[")):
                return LLMExecutionResult(
                    kind=LLMOutputKind.PARSE_ERROR,
                    error=f"Invalid JSON: {exc.msg}",
                    raw=raw,
                )
            return LLMExecutionResult(
                kind=LLMOutputKind.FINAL,
                final=text,
                raw=raw,
            )

        if not isinstance(payload, dict):
            return LLMExecutionResult(
                kind=LLMOutputKind.PARSE_ERROR,
                error="LLM output JSON must be an object",
                raw=raw,
            )

        return cls._parse_dict(payload, raw)

    @classmethod
    def _parse_dict(cls, payload: dict[str, Any], raw: str | dict[str, Any]) -> LLMExecutionResult:
        if "tool" in payload:
            try:
                LLMToolCall.model_validate(payload)
            except ValidationError as exc:
                return LLMExecutionResult(
                    kind=LLMOutputKind.PARSE_ERROR,
                    error=str(exc),
                    raw=raw,
                )
            return LLMExecutionResult(kind=LLMOutputKind.TOOL_CALL, raw=raw)

        for key in cls._FINAL_KEYS:
            if key in payload:
                content = payload[key]
                if not isinstance(content, str):
                    return LLMExecutionResult(
                        kind=LLMOutputKind.PARSE_ERROR,
                        error=f"Field '{key}' must be a string",
                        raw=raw,
                    )
                return LLMExecutionResult(kind=LLMOutputKind.FINAL, final=content, raw=raw)

        return LLMExecutionResult(
            kind=LLMOutputKind.PARSE_ERROR,
            error="Unrecognized LLM output: expected 'tool' or final response field",
            raw=raw,
        )

    @classmethod
    def to_tool_call(cls, parsed: LLMExecutionResult) -> LLMToolCall:
        if parsed.kind != LLMOutputKind.TOOL_CALL or not isinstance(parsed.raw, dict):
            if isinstance(parsed.raw, str):
                return LLMToolCall.parse(parsed.raw)
            raise ValueError("Not a tool call")
        return LLMToolCall.model_validate(parsed.raw)
