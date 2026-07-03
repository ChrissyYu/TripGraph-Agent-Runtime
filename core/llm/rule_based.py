"""Rule-based LLM client for development and testing without API keys."""

from __future__ import annotations

import json
import re

from core.llm.base import LLMMessage


class RuleBasedLLMClient:
    """Generates structured plan JSON from travel-planning queries."""

    provider: str = "rule_based"

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        response_json: bool = False,
    ) -> str:
        system_msgs = [m.content for m in messages if m.role == "system"]
        system = system_msgs[0] if system_msgs else ""

        if "execution critic" in system.lower():
            from plan.execution_critic import RuleBasedExecutionCritic

            return await RuleBasedExecutionCritic().complete(
                messages,
                temperature=temperature,
                response_json=response_json,
            )

        if "compress plan execution context" in system.lower():
            from plan.context_compression import RuleBasedContextSummarizer

            return await RuleBasedContextSummarizer().complete(
                messages,
                temperature=temperature,
                response_json=response_json,
            )

        if "tool selection router" in system.lower():
            from tools.registry import ToolRegistry
            from tools.router.llm import RuleBasedToolSelectionLLM

            return await RuleBasedToolSelectionLLM(ToolRegistry.default()).complete(
                messages,
                temperature=temperature,
                response_json=response_json,
            )

        user_msgs = [m.content for m in messages if m.role == "user"]
        query = user_msgs[-1] if user_msgs else ""
        available_tools = _extract_available_tools(messages)

        if "Failed step id" in query or "replacement steps" in query or "Critic assessment" in query:
            return json.dumps(_build_replan_steps(query, available_tools), ensure_ascii=False)

        first_query = user_msgs[0] if user_msgs else ""
        plan = _build_plan_for_query(first_query, available_tools)
        return json.dumps(plan, ensure_ascii=False)


def _extract_available_tools(messages: list[LLMMessage]) -> list[str]:
    for message in messages:
        if message.role != "system":
            continue
        match = re.search(r"Valid tool_hint values:\s*(.+)", message.content)
        if match:
            return [name.strip() for name in match.group(1).split(",") if name.strip()]
    return ["weather", "map", "budget"]


def _pick_tool(name: str, available: list[str], *, prefer_mcp: bool = False) -> str | None:
    mcp_name = f"mcp_{name}"
    if prefer_mcp and mcp_name in available:
        return mcp_name
    if name in available:
        return name
    if mcp_name in available:
        return mcp_name
    return None


def _prefer_mcp_tools(query: str) -> bool:
    lowered = query.lower()
    return "mcp" in lowered or "mcp_" in lowered


CITY_NAMES = ("上海", "北京", "广州", "深圳", "杭州", "成都", "西安", "南京", "苏州")


def _extract_city(query: str) -> str | None:
    for city in CITY_NAMES:
        if city in query:
            return city
    return None


def _extract_days(query: str) -> int | None:
    match = re.search(r"(\d+)\s*[日天]", query)
    if match:
        return int(match.group(1))
    return None


def _is_trip_with_budget(query: str) -> bool:
    lowered = query.lower()
    has_budget = any(token in query or token in lowered for token in ("预算", "费用", "花费", "budget"))
    has_trip = any(
        token in query
        for token in ("规划", "日游", "旅行", "行程", "旅游", "出游", "游玩")
    )
    has_city_or_days = _extract_city(query) is not None or _extract_days(query) is not None
    return has_budget and has_trip and has_city_or_days


def _build_trip_weather_map_budget_plan(
    query: str,
    available_tools: list[str],
    *,
    city: str | None = None,
    days: int | None = None,
) -> dict:
    """Standard weather → map → budget plan for trip + budget queries."""
    resolved_city = city or _extract_city(query) or "目的地"
    resolved_days = days or _extract_days(query) or 3
    prefer_mcp = _prefer_mcp_tools(query)
    weather = _pick_tool("weather", available_tools, prefer_mcp=prefer_mcp)
    map_tool = _pick_tool("map", available_tools, prefer_mcp=prefer_mcp)
    budget = _pick_tool("budget", available_tools, prefer_mcp=prefer_mcp)

    steps: list[dict] = []
    step_id = 1
    weather_dep: list[int] = []
    map_dep: list[int] = []

    if weather:
        steps.append(
            {
                "id": step_id,
                "task": f"查询{resolved_city}天气",
                "tool_hint": weather,
            },
        )
        weather_dep = [step_id]
        step_id += 1

    if map_tool:
        steps.append(
            {
                "id": step_id,
                "task": f"规划{resolved_city}{resolved_days}日景点路线",
                "tool_hint": map_tool,
                "dependency": weather_dep or None,
            },
        )
        map_dep = weather_dep + [step_id]
        step_id += 1

    if budget:
        steps.append(
            {
                "id": step_id,
                "task": f"计算{resolved_city}{resolved_days}天旅行预算",
                "tool_hint": budget,
                "dependency": map_dep or weather_dep or None,
            },
        )

    if not steps:
        steps.append({"id": 1, "task": f"规划{resolved_city}{resolved_days}日游", "tool_hint": None})

    goal = query.strip() or f"规划{resolved_city}{resolved_days}日游并计算预算"
    return {"goal": goal, "steps": steps}


def _build_replan_steps(query: str, available_tools: list[str]) -> dict:
    goal = query
    if "Original goal:" in query:
        match = re.search(r"Original goal:\s*(.+)", query)
        if match:
            goal = match.group(1).strip()

    if _is_trip_with_budget(goal) or _is_trip_with_budget(query):
        plan = _build_trip_weather_map_budget_plan(goal, available_tools)
        return {"steps": plan["steps"]}

    completed: list[int] = []
    if "Completed step ids:" in query:
        match = re.search(r"Completed step ids:\s*\[(.*?)\]", query)
        if match and match.group(1).strip():
            completed = [int(x.strip()) for x in match.group(1).split(",") if x.strip()]

    budget_hint = _pick_tool("budget", available_tools)
    return {
        "steps": [
            {
                "id": 1,
                "task": "重新计算3天旅行预算",
                "tool_hint": budget_hint,
                "dependency": completed or None,
            },
        ],
    }


def _build_plan_for_query(query: str, available_tools: list[str]) -> dict:
    if _is_dual_city_query(query):
        return _build_dual_city_plan(query, available_tools)

    if _is_trip_with_budget(query):
        return _build_trip_weather_map_budget_plan(query, available_tools)

    if "上海" in query and ("3日" in query or "3天" in query):
        return _build_trip_weather_map_budget_plan(
            query,
            available_tools,
            city="上海",
            days=3,
        )

    if _is_complex_query(query):
        return _build_complex_plan(query, available_tools)

    return _build_default_plan(query, available_tools)


def _is_dual_city_query(query: str) -> bool:
    cities = ["上海", "北京", "广州", "深圳", "杭州", "成都"]
    return sum(1 for city in cities if city in query) >= 2


def _is_complex_query(query: str) -> bool:
    if re.search(r"[5-9]日|[5-9]天|1[0-9]日|1[0-9]天", query):
        return True
    keywords = ("双城", "多城", "对比", "详细", "并且", "同时", "分段")
    return any(keyword in query for keyword in keywords)


def _build_shanghai_3day_plan(available_tools: list[str]) -> dict:
    return _build_trip_weather_map_budget_plan(
        "规划上海3日游并计算预算",
        available_tools,
        city="上海",
        days=3,
    )


def _build_dual_city_plan(query: str, available_tools: list[str]) -> dict:
    cities = [city for city in ("上海", "北京", "广州", "深圳", "杭州", "成都") if city in query]
    if len(cities) < 2:
        cities = ["上海", "北京"]

    weather = _pick_tool("weather", available_tools)
    map_tool = _pick_tool("map", available_tools)
    budget = _pick_tool("budget", available_tools)

    steps: list[dict] = []
    step_id = 1
    city_deps: dict[str, list[int]] = {}

    for city in cities:
        if weather:
            steps.append({"id": step_id, "task": f"查询{city}天气", "tool_hint": weather})
            city_deps[city] = [step_id]
            step_id += 1

    for city in cities:
        if map_tool:
            steps.append(
                {
                    "id": step_id,
                    "task": f"规划{city}市内路线",
                    "tool_hint": map_tool,
                    "dependency": city_deps.get(city) or None,
                },
            )
            city_deps[city] = (city_deps.get(city) or []) + [step_id]
            step_id += 1

    for city in cities:
        if budget:
            steps.append(
                {
                    "id": step_id,
                    "task": f"估算{city}段旅行预算",
                    "tool_hint": budget,
                    "dependency": city_deps.get(city) or None,
                },
            )
            step_id += 1

    if not steps:
        steps.append({"id": 1, "task": f"规划{'、'.join(cities)}双城游", "tool_hint": None})

    return {"goal": f"规划{'、'.join(cities)}双城游", "steps": steps}


def _build_complex_plan(query: str, available_tools: list[str]) -> dict:
    weather = _pick_tool("weather", available_tools)
    map_tool = _pick_tool("map", available_tools)
    budget = _pick_tool("budget", available_tools)

    steps: list[dict] = []
    step_id = 1
    deps: list[int] = []

    if weather:
        steps.append({"id": step_id, "task": "查询目的地天气", "tool_hint": weather})
        deps = [step_id]
        step_id += 1

    if map_tool:
        steps.append(
            {
                "id": step_id,
                "task": "规划主要景点与交通路线",
                "tool_hint": map_tool,
                "dependency": deps or None,
            },
        )
        deps = deps + [step_id]
        step_id += 1

    if budget:
        steps.append(
            {
                "id": step_id,
                "task": "分段估算旅行预算",
                "tool_hint": budget,
                "dependency": deps or None,
            },
        )
        step_id += 1

    if not steps:
        steps.append({"id": 1, "task": f"分析并规划: {query}", "tool_hint": None})

    return {"goal": query, "steps": steps}


def _build_default_plan(query: str, available_tools: list[str]) -> dict:
    if _is_trip_with_budget(query):
        return _build_trip_weather_map_budget_plan(query, available_tools)

    weather = _pick_tool("weather", available_tools)
    map_tool = _pick_tool("map", available_tools)
    budget = _pick_tool("budget", available_tools)

    steps: list[dict] = []
    step_id = 1
    deps: list[int] = []

    if weather:
        steps.append({"id": step_id, "task": "查询天气", "tool_hint": weather})
        deps = [step_id]
        step_id += 1

    if map_tool:
        steps.append(
            {
                "id": step_id,
                "task": "规划路线",
                "tool_hint": map_tool,
                "dependency": deps or None,
            },
        )
        deps = deps + [step_id]
        step_id += 1

    if budget:
        steps.append(
            {
                "id": step_id,
                "task": "计算预算",
                "tool_hint": budget,
                "dependency": deps or None,
            },
        )
        step_id += 1

    if not steps:
        steps.append({"id": 1, "task": f"分析需求: {query}", "tool_hint": None})

    return {"goal": query, "steps": steps}
