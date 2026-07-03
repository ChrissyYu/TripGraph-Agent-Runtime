"""LLM-driven tool selection."""

from __future__ import annotations

import json
import re

from core.llm.base import LLMClient, LLMMessage
from schemas.tool_router import ToolAlternative, ToolRouterStrategy
from tools.registry import ToolRegistry
from tools.router._helpers import rank_to_result, tool_catalog
from tools.router.rule_based import RuleBasedToolSelector

TOOL_SELECTION_SYSTEM_PROMPT = """You are a tool selection router for a travel planning agent.
Given a task description and registered tools, choose the best matching tool.

Return JSON only:
{
  "best_tool": "<exact tool name or null>",
  "confidence": <float 0.0-1.0>,
  "alternatives": [
    {"tool": "<tool name>", "confidence": <float 0.0-1.0>}
  ]
}

Rules:
- best_tool must exactly match a registered tool name, or null if none apply
- alternatives excludes best_tool, ordered by confidence descending
- confidence reflects match strength, not execution certainty
- Output JSON only, no markdown fences
"""


class RuleBasedToolSelectionLLM:
    """Deterministic LLM fallback that delegates to rule-based selector."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._selector = RuleBasedToolSelector(registry)

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        response_json: bool = False,
    ) -> str:
        user_msgs = [m.content for m in messages if m.role == "user"]
        payload = json.loads(user_msgs[-1]) if user_msgs else {}
        task = payload.get("task", "")
        result = self._selector.select(task)
        return json.dumps(
            {
                "best_tool": result["best_tool"],
                "confidence": result["confidence"],
                "alternatives": [
                    alt.model_dump() if hasattr(alt, "model_dump") else alt
                    for alt in result["alternatives"]
                ],
            },
            ensure_ascii=False,
        )


class LLMToolSelector:
    """Select tools using an LLM over the registry catalog."""

    def __init__(self, registry: ToolRegistry, llm: LLMClient | None = None) -> None:
        self._registry = registry
        self._llm = llm or RuleBasedToolSelectionLLM(registry)

    async def select(self, task: str) -> dict:
        tools = [
            {
                "name": definition.name,
                "description": definition.description,
            }
            for definition in tool_catalog(self._registry)
        ]
        payload = json.dumps({"task": task, "tools": tools}, ensure_ascii=False)
        messages = [
            LLMMessage(role="system", content=TOOL_SELECTION_SYSTEM_PROMPT),
            LLMMessage(role="user", content=payload),
        ]
        raw = await self._llm.complete(messages, response_json=True)
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\n?", "", text)
            text = re.sub(r"\n?```$", "", text).strip()

        parsed = json.loads(text)
        best_tool = parsed.get("best_tool")
        if best_tool is not None and not self._registry.has(best_tool):
            best_tool = None

        alternatives = []
        for item in parsed.get("alternatives", []):
            tool_name = item.get("tool")
            if not tool_name or tool_name == best_tool or not self._registry.has(tool_name):
                continue
            alternatives.append(
                {
                    "tool": tool_name,
                    "confidence": float(item.get("confidence", 0.0)),
                },
            )

        if best_tool is None:
            return rank_to_result(task, [], strategy="llm")

        return {
            "task": task,
            "best_tool": best_tool,
            "confidence": round(float(parsed.get("confidence", 0.0)), 4),
            "alternatives": [ToolAlternative(**item) for item in alternatives],
            "strategy": ToolRouterStrategy.LLM,
        }
