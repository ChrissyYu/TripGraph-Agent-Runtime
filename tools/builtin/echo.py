"""Example echo tool for development."""

from pydantic import BaseModel, Field

from tools.decorator import tool


class EchoInput(BaseModel):
    message: str = Field(..., description="Text to echo back")


@tool(
    name="echo",
    description="Echoes the input message back to the caller.",
    input_schema=EchoInput,
)
async def echo_tool(message: str) -> str:
    return message
