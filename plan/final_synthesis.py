"""Structured final result synthesis from tool execution outputs."""

from __future__ import annotations

import json
from typing import Any

from plan.state import PlanState
from schemas.plan import Plan, StepStatus

WEATHER_TOOL_NAMES = ("weather", "mcp_weather")
MAP_TOOL_NAMES = ("map", "mcp_map")
BUDGET_TOOL_NAMES = ("budget", "mcp_budget")


def synthesize_final_result(plan: Plan, state: PlanState) -> str:
    """Build a deduplicated final answer from structured tool outputs."""
    sections: list[str] = [f"目标：{plan.goal}"]

    weather_lines = _collect_weather_lines(state)
    if weather_lines:
        sections.append("天气信息：")
        sections.extend(f"- {line}" for line in weather_lines)

    route_lines = _collect_route_lines(state)
    if route_lines:
        sections.append("行程路线：")
        sections.extend(f"- {line}" for line in route_lines)

    budget_lines = _collect_budget_lines(state)
    if budget_lines:
        sections.append("预算估算：")
        sections.extend(f"- {line}" for line in budget_lines)

    summary = _build_summary(plan, state, weather_lines, route_lines, budget_lines)
    sections.append(summary)
    return "\n".join(sections)


def check_final_result_coverage(text: str) -> dict[str, bool]:
    """Return whether final_result contains weather/route/budget sections."""
    return {
        "contains_weather_section": "天气信息：" in text or text.startswith("天气："),
        "contains_route_section": "行程路线：" in text,
        "contains_budget_section": "预算估算：" in text or "预算：" in text,
    }


def _collect_weather_lines(state: PlanState) -> list[str]:
    seen: set[str] = set()
    lines: list[str] = []
    for tool_name in WEATHER_TOOL_NAMES:
        for observation in _iter_tool_observations(state, tool_name):
            city = observation.get("city", "")
            date = observation.get("date", "")
            condition = observation.get("condition", "")
            temp_c = observation.get("temp_c", "")
            key = json.dumps(
                {"city": city, "date": date, "condition": condition, "temp_c": temp_c},
                sort_keys=True,
                ensure_ascii=False,
            )
            if key in seen:
                continue
            seen.add(key)
            parts = [p for p in (city, date, condition, f"{temp_c}°C" if temp_c != "" else "") if p]
            if parts:
                lines.append("，".join(str(p) for p in parts))
    return lines


def _collect_route_lines(state: PlanState) -> list[str]:
    seen: set[str] = set()
    lines: list[str] = []
    for tool_name in MAP_TOOL_NAMES:
        for observation in _iter_tool_observations(state, tool_name):
            origin = observation.get("origin", "")
            destination = observation.get("destination", "")
            duration = observation.get("duration_min", "")
            mode = observation.get("mode", "")
            route_text = observation.get("route", "")
            key = json.dumps(
                {
                    "origin": origin,
                    "destination": destination,
                    "duration_min": duration,
                    "mode": mode,
                    "route": route_text,
                },
                sort_keys=True,
                ensure_ascii=False,
            )
            if key in seen:
                continue
            seen.add(key)
            if route_text:
                route = str(route_text)
            else:
                route = f"{origin} → {destination}"
            if duration != "":
                route += f"（约{duration}分钟"
                if mode:
                    route += f"，{mode}"
                route += "）"
            places = observation.get("places")
            if isinstance(places, list) and places:
                route += f"；途经：{', '.join(str(p) for p in places)}"
            lines.append(route)
    return lines


def _collect_budget_lines(state: PlanState) -> list[str]:
    seen: set[str] = set()
    lines: list[str] = []
    for tool_name in BUDGET_TOOL_NAMES:
        for observation in _iter_tool_observations(state, tool_name):
            total = observation.get("total", "")
            currency = observation.get("currency", "")
            days = observation.get("days", "")
            key = json.dumps(
                {"total": total, "currency": currency, "days": days},
                sort_keys=True,
                ensure_ascii=False,
            )
            if key in seen:
                continue
            seen.add(key)
            line = f"{total} {currency}".strip()
            if days != "":
                line += f"（{days}天）"
            breakdown = observation.get("breakdown")
            if isinstance(breakdown, dict) and breakdown:
                details = ", ".join(f"{k}:{v}" for k, v in breakdown.items())
                line += f"；明细：{details}"
            lines.append(line.strip())
    return lines


def _iter_tool_observations(state: PlanState, tool_name: str) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_observation(observation: dict[str, Any]) -> None:
        key = json.dumps(observation, sort_keys=True, ensure_ascii=False)
        if key in seen:
            return
        seen.add(key)
        observations.append(observation)

    for result in state.step_results.values():
        if result.status != StepStatus.COMPLETED:
            continue
        if result.tool_name != tool_name:
            continue
        if isinstance(result.observation, dict):
            add_observation(result.observation)

    step_by_id = {step.id: step for step in state.plan.steps}
    for raw_id, output in state.global_context.get("step_outputs", {}).items():
        if not isinstance(output, dict):
            continue
        step_id = int(raw_id) if str(raw_id).isdigit() else raw_id
        step = step_by_id.get(step_id)
        if step is None or step.tool_hint != tool_name:
            continue
        add_observation(output)

    tool_outputs = state.global_context.get("tool_outputs", {})
    fallback = tool_outputs.get(tool_name)
    if isinstance(fallback, dict):
        add_observation(fallback)

    return observations


def _build_summary(
    plan: Plan,
    state: PlanState,
    weather_lines: list[str],
    route_lines: list[str],
    budget_lines: list[str],
) -> str:
    ctx = state.global_context
    city = ctx.get("city", "")
    days = ctx.get("days", "")
    location_hint = f"{city}{days}日游" if city or days else "旅行"

    parts: list[str] = []
    if weather_lines:
        parts.append("天气")
    if route_lines:
        parts.append("路线")
    if budget_lines:
        parts.append("预算")

    if parts:
        return f"总结：已完成{location_hint}规划，包含{'、'.join(parts)}信息。"
    return f"总结：已完成{location_hint}规划。"
