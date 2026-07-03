"""Chat API request/response schemas."""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1, description="Conversation session identifier")
    message: str = Field(..., min_length=1, description="User message")
    stream: bool = Field(default=False, description="Enable SSE streaming response")


class ChatResponse(BaseModel):
    session_id: str
    message: str
    specialist: str | None = None
