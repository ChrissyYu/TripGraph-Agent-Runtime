"""Validate structured plans before execution."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from schemas.plan import Plan, PlanStep, PlanValidationReport
from tools.registry import ToolRegistry


class PlanValidator:
    """Validates plan structure, dependencies, tools, and step ids."""

    def __init__(self, tool_registry: ToolRegistry) -> None:
        self._registry = tool_registry

    def validate(self, plan: Plan) -> PlanValidationReport:
        errors: list[str] = []
        errors.extend(self._validate_structure(plan))
        if errors:
            return PlanValidationReport(success=False, errors=errors)

        step_ids = {step.id for step in plan.steps}
        errors.extend(self._validate_step_id_continuity(plan.steps))
        errors.extend(self._validate_duplicate_step_ids(plan.steps))
        errors.extend(self._validate_dependencies_exist(plan.steps, step_ids))
        errors.extend(self._validate_dependency_cycles(plan.steps))
        errors.extend(self._validate_tool_hints(plan.steps))

        return PlanValidationReport(success=len(errors) == 0, errors=errors)

    def validate_raw(self, raw: str | dict[str, Any]) -> PlanValidationReport:
        """Parse and validate raw JSON plan payload."""
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
            plan = Plan.model_validate(payload)
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            return PlanValidationReport(
                success=False,
                errors=[f"Invalid plan JSON structure: {exc}"],
            )
        return self.validate(plan)

    def assert_valid(self, plan: Plan) -> PlanValidationReport:
        report = self.validate(plan)
        if not report.success:
            from core.exceptions import PlanValidationError

            raise PlanValidationError(
                report.readable_message(),
                errors=report.errors,
            )
        return report

    @staticmethod
    def _validate_structure(plan: Plan) -> list[str]:
        errors: list[str] = []
        if not plan.goal or not plan.goal.strip():
            errors.append("Field 'goal' must be a non-empty string.")
        if not plan.steps:
            errors.append("Plan must contain at least one step.")
        for step in plan.steps:
            if not step.task or not step.task.strip():
                errors.append(f"Step {step.id}: 'task' must be a non-empty string.")
        return errors

    @staticmethod
    def _validate_step_id_continuity(steps: list[PlanStep]) -> list[str]:
        if not steps:
            return []
        sorted_ids = sorted(step.id for step in steps)
        expected = list(range(1, len(steps) + 1))
        if sorted_ids != expected:
            return [
                f"Step ids must be continuous starting from 1; "
                f"expected {expected}, got {sorted_ids}.",
            ]
        return []

    @staticmethod
    def _validate_duplicate_step_ids(steps: list[PlanStep]) -> list[str]:
        seen: set[int] = set()
        errors: list[str] = []
        for step in steps:
            if step.id in seen:
                errors.append(f"Duplicate step id: {step.id}.")
            seen.add(step.id)
        return errors

    @staticmethod
    def _validate_dependencies_exist(
        steps: list[PlanStep],
        step_ids: set[int],
    ) -> list[str]:
        errors: list[str] = []
        for step in steps:
            if not step.dependency:
                continue
            for dep in step.dependency:
                if dep not in step_ids:
                    errors.append(
                        f"Step {step.id}: dependency {dep} references unknown step.",
                    )
                if dep >= step.id:
                    errors.append(
                        f"Step {step.id}: dependency {dep} must refer to a prior step.",
                    )
        return errors

    @staticmethod
    def _validate_dependency_cycles(steps: list[PlanStep]) -> list[str]:
        graph: dict[int, list[int]] = {step.id: list(step.dependency or []) for step in steps}
        visiting: set[int] = set()
        visited: set[int] = set()

        def dfs(node: int) -> bool:
            if node in visiting:
                return True
            if node in visited:
                return False
            visiting.add(node)
            for neighbor in graph.get(node, []):
                if neighbor in graph and dfs(neighbor):
                    return True
            visiting.remove(node)
            visited.add(node)
            return False

        for step_id in graph:
            if dfs(step_id):
                return ["Dependency graph contains a cycle."]
        return []

    def _validate_tool_hints(self, steps: list[PlanStep]) -> list[str]:
        available = set(self._registry.list_names())
        errors: list[str] = []
        for step in steps:
            if step.tool_hint is None:
                continue
            if step.tool_hint not in available:
                errors.append(
                    f"Step {step.id}: tool_hint '{step.tool_hint}' is not registered. "
                    f"Available tools: {', '.join(sorted(available)) or '(none)'}.",
                )
        return errors
