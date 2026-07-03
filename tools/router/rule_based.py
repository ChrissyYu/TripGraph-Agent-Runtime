"""Rule-based tool selection by keyword matching."""

from __future__ import annotations

import re

from tools.registry import ToolRegistry
from tools.router._helpers import rank_to_result, tool_catalog

TOOL_KEYWORDS: dict[str, list[str]] = {
    "weather": [
        "天气",
        "气温",
        "温度",
        "降雨",
        "forecast",
        "weather",
        "climate",
    ],
    "map": [
        "路线",
        "导航",
        "地图",
        "交通",
        "出行",
        "route",
        "map",
        "directions",
        "driving",
    ],
    "budget": [
        "预算",
        "费用",
        "花费",
        "成本",
        "价格",
        "budget",
        "cost",
        "spend",
    ],
    "echo": ["echo", "回显", "测试", "test"],
}


class RuleBasedToolSelector:
    """Score tools by keyword overlap with the task description."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry
        self._available = set(registry.list_names())

    def select(self, task: str) -> dict:
        scores: dict[str, float] = {name: 0.0 for name in self._available}

        task_lower = task.lower()
        for tool_name, keywords in TOOL_KEYWORDS.items():
            if tool_name not in self._available:
                continue
            hits = sum(1 for keyword in keywords if keyword in task_lower or keyword in task)
            if hits:
                scores[tool_name] = min(1.0, hits / max(len(keywords) * 0.35, 1))

        for definition in tool_catalog(self._registry):
            if scores.get(definition.name, 0) > 0:
                continue
            name_hits = len(re.findall(re.escape(definition.name), task_lower))
            if name_hits:
                scores[definition.name] = min(1.0, 0.5 + name_hits * 0.2)

        ranked = sorted(
            ((tool, score) for tool, score in scores.items() if score > 0),
            key=lambda item: item[1],
            reverse=True,
        )
        return rank_to_result(task, ranked, strategy="rule_based")
