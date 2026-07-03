"""Detect logical LLM caller from message contents."""

from __future__ import annotations

from core.llm.base import LLMMessage


def detect_caller_from_messages(messages: list[LLMMessage]) -> str:
    system = next((message.content for message in messages if message.role == "system"), "")
    lowered = system.lower()
    if "execution critic" in lowered or "need_replan" in lowered:
        return "critic"
    if "summarizer" in lowered or "summarize" in lowered:
        return "summarizer"
    if "tool router" in lowered or "tool selection" in lowered:
        return "router"
    if "replan" in lowered:
        return "replanner"
    return "planner"
