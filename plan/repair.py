"""Lightweight plan normalization and repair for LLM output."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from schemas.plan import Plan, PlanStep

BUDGET_TASK_PATTERN = re.compile(
    r"预算|费用|花费|总预算|旅行预算|计算.*预算",
    re.IGNORECASE,
)
SYNTHESIS_TASK_PATTERN = re.compile(
    r"综合|总结|汇总|生成完整|完整行程|最终计划|finalize|synthesis",
    re.IGNORECASE,
)
TOOL_ORDER = {"weather": 0, "map": 1, "budget": 2}


@dataclass
class RepairResult:
    plan: Plan
    repaired: bool = False
    notes: list[str] = field(default_factory=list)
    id_map: dict[int, int] = field(default_factory=dict)


def renumber_steps(steps: list[PlanStep]) -> tuple[list[PlanStep], dict[int, int], list[str]]:
    """Renumber step ids to continuous 1..n and remap dependencies."""
    if not steps:
        return [], {}, []

    sorted_steps = sorted(steps, key=lambda step: step.id)
    id_map = {step.id: index for index, step in enumerate(sorted_steps, start=1)}
    notes: list[str] = []
    expected = list(range(1, len(sorted_steps) + 1))
    if sorted(id_map.keys()) != expected or list(id_map.values()) != expected:
        notes.append(f"Renumbered step ids: {id_map}")

    remapped: list[PlanStep] = []
    for step in sorted_steps:
        new_id = id_map[step.id]
        new_deps: list[int] = []
        for dep in step.dependency or []:
            if dep not in id_map:
                notes.append(f"Step {step.id}: dropped unknown dependency {dep}")
                continue
            mapped = id_map[dep]
            if mapped >= new_id:
                notes.append(f"Step {step.id}: dropped non-prior dependency {dep}")
                continue
            new_deps.append(mapped)
        remapped.append(
            PlanStep(
                id=new_id,
                task=step.task,
                tool_hint=step.tool_hint,
                dependency=new_deps or None,
            ),
        )
    return remapped, id_map, notes


def remove_duplicate_steps(steps: list[PlanStep]) -> tuple[list[PlanStep], list[str]]:
    """Remove exact duplicate steps (same task + tool_hint)."""
    seen: set[tuple[str, str | None]] = set()
    deduped: list[PlanStep] = []
    notes: list[str] = []
    for step in steps:
        key = (step.task.strip(), step.tool_hint)
        if key in seen:
            notes.append(f"Removed duplicate step: task={step.task!r} tool_hint={step.tool_hint}")
            continue
        seen.add(key)
        deduped.append(step)
    return deduped, notes


def repair_steps(steps: list[PlanStep]) -> RepairResult:
    """Normalize a step list without changing goal (light repair for replan path)."""
    plan = Plan(goal="(replan)", steps=steps)
    result = repair_plan(plan)
    return RepairResult(
        plan=Plan(goal=plan.goal, steps=result.plan.steps),
        repaired=result.repaired,
        notes=result.notes,
        id_map=result.id_map,
    )


def normalize_plan(plan: Plan) -> RepairResult:
    """Planner-path normalization: dedup, synthesis cleanup, reorder, renumber."""
    notes: list[str] = []
    steps = list(plan.steps)

    steps, dedup_notes = remove_duplicate_steps(steps)
    notes.extend(dedup_notes)

    steps, budget_notes = deduplicate_budget_steps(steps)
    notes.extend(budget_notes)

    steps, synthesis_notes = normalize_synthesis_steps(steps)
    notes.extend(synthesis_notes)

    steps, order_notes = prefer_tool_execution_order(steps)
    notes.extend(order_notes)

    steps, id_map, renumber_notes = renumber_steps(steps)
    notes.extend(renumber_notes)

    return RepairResult(
        plan=Plan(goal=plan.goal, steps=steps),
        repaired=bool(notes),
        notes=notes,
        id_map=id_map,
    )


def repair_plan(plan: Plan) -> RepairResult:
    """Normalize a plan: deduplicate steps, renumber ids, remap dependencies."""
    notes: list[str] = []
    steps, dedup_notes = remove_duplicate_steps(plan.steps)
    notes.extend(dedup_notes)
    steps, id_map, renumber_notes = renumber_steps(steps)
    notes.extend(renumber_notes)
    return RepairResult(
        plan=Plan(goal=plan.goal, steps=steps),
        repaired=bool(notes),
        notes=notes,
        id_map=id_map,
    )


def deduplicate_budget_steps(steps: list[PlanStep]) -> tuple[list[PlanStep], list[str]]:
    """Keep one budget step when multiple tasks are clearly budget calculations."""
    notes: list[str] = []
    budget_indices = [
        index
        for index, step in enumerate(steps)
        if step.tool_hint == "budget" or BUDGET_TASK_PATTERN.search(step.task)
    ]
    if len(budget_indices) <= 1:
        return steps, notes

    keep_index = max(budget_indices, key=lambda index: len(steps[index].task))
    kept: list[PlanStep] = []
    for index, step in enumerate(steps):
        if index in budget_indices and index != keep_index:
            notes.append(f"Removed duplicate budget step: task={step.task!r}")
            continue
        kept.append(step)
    return kept, notes


def normalize_synthesis_steps(steps: list[PlanStep]) -> tuple[list[PlanStep], list[str]]:
    """Turn final synthesis tasks into non-tool steps instead of budget/map/weather calls."""
    notes: list[str] = []
    normalized: list[PlanStep] = []
    for step in steps:
        if step.tool_hint and SYNTHESIS_TASK_PATTERN.search(step.task):
            notes.append(
                f"Cleared tool_hint for synthesis step: task={step.task!r} was {step.tool_hint}",
            )
            normalized.append(
                PlanStep(
                    id=step.id,
                    task=step.task,
                    tool_hint=None,
                    dependency=step.dependency,
                ),
            )
            continue
        normalized.append(step)
    return normalized, notes


def prefer_tool_execution_order(steps: list[PlanStep]) -> tuple[list[PlanStep], list[str]]:
    """Stable-sort tool steps so weather tends to run before map and budget."""
    if len(steps) <= 1:
        return steps, []

    indexed = list(enumerate(steps))
    reordered = sorted(
        indexed,
        key=lambda item: (TOOL_ORDER.get(item[1].tool_hint or "", 99), item[0]),
    )
    if [index for index, _step in reordered] == list(range(len(steps))):
        return steps, []

    notes = ["Reordered steps to prefer weather → map → budget execution"]
    return [step for _index, step in reordered], notes
