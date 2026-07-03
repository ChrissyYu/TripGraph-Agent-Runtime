"""Planner system prompts with tool registry context injection."""

from __future__ import annotations

from schemas.tool import ToolDefinition
from tools.registry import ToolRegistry

PLANNER_OUTPUT_SCHEMA = """{
  "goal": "<overall goal string>",
  "steps": [
    {
      "id": 1,
      "task": "<concise subtask description>",
      "tool_hint": "<exact registered tool name, or null if no tool applies>",
      "dependency": [<optional list of prior step ids>]
    }
  ]
}"""

REPLAN_OUTPUT_SCHEMA = """{
  "goal": "<overall goal string>",
  "steps": [
    {
      "id": 1,
      "task": "<concise subtask description>",
      "tool_hint": "<exact registered tool name, or null if no tool applies>",
      "dependency": [<optional list of prior step ids>]
    }
  ]
}"""

TRAVEL_PLANNING_HEURISTICS = """## Travel Planning Heuristics
- If the query mentions itinerary / trip / \"X日游\" / route planning, include a **map** step for route or itinerary.
- If the query mentions budget / cost / expense / \"预算\" / \"费用\", include a **budget** step.
- If the query mentions a destination and trip length, strongly prefer a **weather** step for that destination.
- Avoid duplicate steps with the same task and tool_hint.
- Every executable step should include a valid `tool_hint` when a registered tool applies.
- `tool_hint` MUST be one of the registered tool names from the Tool Registry below."""

PLANNER_PLANNING_RULES = """## Planning Rules
1. **Minimum steps**: Use the fewest steps that fully satisfy the goal. Do not add redundant or duplicate tool calls.
2. **tool_hint accuracy**: When a step needs a tool, `tool_hint` MUST exactly match one registered tool `name` (case-sensitive). Never invent tool names.
3. **Executable steps**: Prefer assigning `tool_hint` for weather / map / budget / echo when the step calls a tool.
4. **Dependencies**: Add `dependency` only when a step truly needs outputs or context from prior steps. Independent tool calls should not depend on each other.
5. **Complex tasks**: For multi-city trips, long itineraries, or multi-concern requests, decompose into focused subtasks (one clear action per step).
6. **Step ids**: Sequential integers starting at 1 with no gaps.
7. **Output**: Return strict JSON only — no markdown fences, no code blocks, no commentary or explanations."""

REPLAN_PLANNING_RULES = """## Replan Rules
1. Output **strict JSON only**. No markdown fences, no code blocks, no explanations.
2. Return a **complete valid plan** (goal + steps), renumbered from 1 as a continuous plan.
3. **Completed steps are immutable** — copy completed step id/task/tool_hint/dependencies exactly.
4. Do not modify, reword, or renumber completed steps. Only add or modify unfinished/failed steps.
5. Step ids in the returned plan must start at 1 and be continuous without gaps.
6. Dependencies must reference existing smaller step ids only.
7. Do not create duplicate steps (same task + tool_hint).
8. Every executable step should include a valid `tool_hint` when a registered tool applies.
9. `tool_hint` MUST exactly match a registered tool `name`, or be null only for pure synthesis.
10. Valid `tool_hint` values come from the Tool Registry below.
11. Even if previous steps are completed, return a complete plan with completed steps copied exactly at the front."""


def format_tool_registry_context(registry: ToolRegistry) -> str:
    """Build tool catalog section injected into planner prompts."""
    definitions = sorted(registry.get_definitions(), key=lambda d: d.name)
    if not definitions:
        return (
            "## Tool Registry\n"
            "No tools are registered. Do not set `tool_hint` on any step.\n"
        )

    lines = [
        "## Tool Registry",
        "You may ONLY use the tools listed below. Each `tool_hint` must exactly match a tool `name`.",
        "",
    ]
    for definition in definitions:
        lines.extend(_format_tool_entry(definition))

    names = ", ".join(d.name for d in definitions)
    lines.append(f"Valid tool_hint values: {names}")
    return "\n".join(lines)


def build_planner_system_prompt(registry: ToolRegistry | None = None) -> str:
    tool_context = (
        format_tool_registry_context(registry)
        if registry is not None
        else "## Tool Registry\n(no registry provided — omit tool_hint unless explicitly known)\n"
    )
    return f"""You are a travel planning assistant. Given a user query, produce an executable JSON plan.

## Output Schema
{PLANNER_OUTPUT_SCHEMA}

{PLANNER_PLANNING_RULES}

{TRAVEL_PLANNING_HEURISTICS}

{tool_context}
"""


def build_replan_system_prompt(registry: ToolRegistry | None = None) -> str:
    tool_context = (
        format_tool_registry_context(registry)
        if registry is not None
        else "## Tool Registry\n(no registry provided — omit tool_hint unless explicitly known)\n"
    )
    return f"""You are a travel planning assistant. A plan is partially executed and needs revision.
Produce a complete renumbered JSON plan that satisfies the goal.

## Output Schema
{REPLAN_OUTPUT_SCHEMA}

{REPLAN_PLANNING_RULES}

Important: Return a complete valid plan with step ids 1..N (continuous). Do not return markdown.

{tool_context}
"""


def _format_tool_entry(definition: ToolDefinition) -> list[str]:
    lines = [f"- **{definition.name}**: {definition.description}"]
    properties = definition.parameters.get("properties", {})
    required = set(definition.parameters.get("required", []))
    if not properties:
        return lines

    param_parts: list[str] = []
    for name, schema in properties.items():
        req_label = "required" if name in required else "optional"
        ptype = schema.get("type", "any")
        desc = schema.get("description", "")
        detail = f"{name} ({ptype}, {req_label})"
        if desc:
            detail = f"{detail}: {desc}"
        param_parts.append(detail)
    lines.append(f"  Parameters: {'; '.join(param_parts)}")
    return lines
