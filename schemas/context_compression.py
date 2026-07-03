"""Schemas for plan context compression."""

from pydantic import BaseModel, Field


class ContextCompressionResult(BaseModel):
    compressed_context: str
    key_facts: list[str] = Field(default_factory=list)
