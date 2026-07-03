"""Resolve plan steps into tool calls."""

from __future__ import annotations

import re
from typing import Any

from schemas.plan import PlanStep
from plan.state import PlanState


class StepToolResolver:
    """Maps plan steps with tool_hint to concrete tool arguments."""

    def resolve(self, step: PlanStep, state: PlanState) -> dict[str, Any] | None:
        if not step.tool_hint:
            return None

        ctx = state.global_context
        hint = step.tool_hint.lower()

        if hint == "weather":
            return {
                "city": ctx.get("city", "上海"),
                "date": ctx.get("date", "today"),
            }

        if hint == "map":
            return {
                "origin": ctx.get("origin", "上海站"),
                "destination": ctx.get("destination", "外滩"),
                "mode": ctx.get("transport_mode", "transit"),
            }

        if hint == "budget":
            return {
                "days": ctx.get("days", 3),
                "daily_food": ctx.get("daily_food", 200.0),
                "daily_transport": ctx.get("daily_transport", 50.0),
                "daily_accommodation": ctx.get("daily_accommodation", 400.0),
                "activities": ctx.get("activities", 500.0),
                "currency": ctx.get("currency", "CNY"),
            }

        if hint == "mcp_weather":
            return {
                "city": ctx.get("city", "上海"),
                "date": ctx.get("date", "today"),
            }

        if hint == "mcp_map":
            return {
                "origin": ctx.get("origin", "酒店"),
                "destination": ctx.get("destination", ctx.get("city", "外滩")),
                "day": ctx.get("days", 1),
            }

        if hint == "mcp_budget":
            return {
                "city": ctx.get("city", "上海"),
                "days": ctx.get("days", 3),
                "currency": ctx.get("currency", "CNY"),
            }

        return ctx.get("tool_args", {}).get(hint)

    @staticmethod
    def enrich_context_from_query(query: str) -> dict[str, Any]:
        """Extract common travel entities from natural language query."""
        context: dict[str, Any] = {"user_query": query}

        city_match = re.search(r"(?:规划)?([\u4e00-\u9fff]{2,4})(\d+)日", query)
        if city_match:
            context["city"] = city_match.group(1)
            context["destination"] = city_match.group(1)
            context["days"] = int(city_match.group(2))
        else:
            city_only = re.search(r"(?:规划)?([\u4e00-\u9fff]{2,4})(?:游|旅行)", query)
            if city_only:
                context["city"] = city_only.group(1)
                context["destination"] = city_only.group(1)

        days_match = re.search(r"(\d+)\s*日", query)
        if days_match and "days" not in context:
            context["days"] = int(days_match.group(1))

        return context
