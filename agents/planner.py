"""Planner agent: LLM-driven structured plan generation."""

from __future__ import annotations

import json

from pydantic import ValidationError

from agents.planner_prompt import build_planner_system_prompt, build_replan_system_prompt
from config.settings import Settings, get_settings
from core.exceptions import AgentLoopError
from core.llm.base import LLMClient, LLMMessage
from core.llm.factory import unwrap_llm_client
from core.llm.json_utils import extract_json_text
from core.llm.rule_based import RuleBasedLLMClient
from core.logging import get_logger
from schemas.execution_critic import ExecutionCritique
from plan.repair import normalize_plan
from plan.state import PlanState
from schemas.plan import Plan, PlanStep
from tools.registry import ToolRegistry

logger = get_logger(__name__)


class PlannerAgent:
    """Generates structured plans from user queries using an LLM."""

    def __init__(
        self,
        llm: LLMClient,
        *,
        tool_registry: ToolRegistry | None = None,
        max_retries: int | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._llm = llm
        self._tool_registry = tool_registry
        self._planner_system_prompt = build_planner_system_prompt(tool_registry)
        self._replan_system_prompt = build_replan_system_prompt(tool_registry)
        cfg = settings or get_settings()
        self._max_retries = max_retries if max_retries is not None else cfg.planner_max_retries

    @property
    def planner_system_prompt(self) -> str:
        return self._planner_system_prompt

    @property
    def replan_system_prompt(self) -> str:
        return self._replan_system_prompt

    @property
    def llm(self) -> LLMClient:
        return self._llm

    async def create_plan(self, user_query: str) -> Plan:
        last_error: str | None = None
        messages = [
            LLMMessage(role="system", content=self._planner_system_prompt),
            LLMMessage(role="user", content=user_query),
        ]

        for attempt in range(1, self._max_retries + 2):
            try:
                raw = await self._llm.complete(messages, response_json=True)
                plan = self._parse_plan(raw)
                normalized = normalize_plan(plan)
                if normalized.repaired:
                    logger.info("Plan normalized: %s", "; ".join(normalized.notes))
                logger.info(
                    "Plan generated with %d steps (attempt %d)",
                    len(normalized.plan.steps),
                    attempt,
                )
                return normalized.plan
            except (ValidationError, json.JSONDecodeError, ValueError) as exc:
                last_error = str(exc)
                logger.warning("Plan parse failed attempt %d: %s", attempt, last_error)
                messages.append(
                    LLMMessage(
                        role="user",
                        content=self._build_retry_feedback(last_error),
                    ),
                )

        if not isinstance(unwrap_llm_client(self._llm), RuleBasedLLMClient):
            try:
                return await self._fallback_rule_based_plan(user_query)
            except (ValidationError, json.JSONDecodeError, ValueError) as exc:
                logger.warning("RuleBased plan fallback also failed: %s", exc)

        raise AgentLoopError(f"Failed to generate valid plan after retries: {last_error}")

    async def _fallback_rule_based_plan(self, user_query: str) -> Plan:
        logger.warning("Plan generation failed with real LLM; falling back to RuleBasedLLMClient")
        fallback = RuleBasedLLMClient()
        messages = [
            LLMMessage(role="system", content=self._planner_system_prompt),
            LLMMessage(role="user", content=user_query),
        ]
        raw = await fallback.complete(messages, response_json=True)
        return normalize_plan(self._parse_plan(raw)).plan

    async def replan_unfinished_steps(
        self,
        state: PlanState,
        *,
        failed_step_id: int,
        error: str,
    ) -> list[PlanStep]:
        """Rewrite only unfinished steps using current execution state."""
        context = state.replan_context()
        user_content = (
            f"Original goal: {state.plan.goal}\n"
            f"Failed step id: {failed_step_id}\n"
            f"Failure error: {error}\n"
            f"Completed step ids: {context['completed_steps']}\n"
            f"Unfinished step ids: {context['unfinished_step_ids']}\n"
            f"Global context: {json.dumps(context['global_context'], ensure_ascii=False)}\n"
            f"Step results: {json.dumps(context['step_results'], ensure_ascii=False)}\n"
            "Return replacement steps JSON for remaining work only."
        )
        messages = [
            LLMMessage(role="system", content=self._replan_system_prompt),
            LLMMessage(role="user", content=user_content),
        ]

        last_error: str | None = None
        for attempt in range(1, self._max_retries + 2):
            try:
                raw = await self._llm.complete(messages, response_json=True)
                steps = self._parse_replan_steps(raw)
                logger.info("Replanned %d unfinished steps (attempt %d)", len(steps), attempt)
                return steps
            except (ValidationError, json.JSONDecodeError, ValueError) as exc:
                last_error = str(exc)
                messages.append(
                    LLMMessage(
                        role="user",
                        content=self._build_retry_feedback(last_error),
                    ),
                )

        if not isinstance(unwrap_llm_client(self._llm), RuleBasedLLMClient):
            try:
                return await self._fallback_rule_based_replan(messages)
            except (ValidationError, json.JSONDecodeError, ValueError) as exc:
                logger.warning("RuleBased replan fallback also failed: %s", exc)

        raise AgentLoopError(f"Failed to replan after retries: {last_error}")

    async def replan_from_critique(
        self,
        state: PlanState,
        *,
        critique: ExecutionCritique,
        anchor_step_id: int,
    ) -> list[PlanStep]:
        """Rewrite unfinished steps using execution critic feedback."""
        messages = self._build_critique_replan_messages(state, critique, anchor_step_id)
        return await self._complete_replan_messages(messages, context="critique")

    async def rulebased_replan_from_critique(
        self,
        state: PlanState,
        *,
        critique: ExecutionCritique,
        anchor_step_id: int,
    ) -> list[PlanStep]:
        """RuleBased fallback for critic-driven replan."""
        messages = self._build_critique_replan_messages(state, critique, anchor_step_id)
        return await self._fallback_rule_based_replan(messages)

    def _build_critique_replan_messages(
        self,
        state: PlanState,
        critique: ExecutionCritique,
        anchor_step_id: int,
    ) -> list[LLMMessage]:
        context = state.replan_context()
        user_content = (
            f"Original goal: {state.plan.goal}\n"
            f"Anchor step id: {anchor_step_id}\n"
            f"Critic score: {critique.score}\n"
            f"Critic assessment: {critique.critique}\n"
            f"Goal completed: {critique.goal_completed}\n"
            f"Missing info: {json.dumps(critique.missing_info, ensure_ascii=False)}\n"
            f"Completed step ids: {context['completed_steps']}\n"
            f"Unfinished step ids: {context['unfinished_step_ids']}\n"
            f"Global context: {json.dumps(context['global_context'], ensure_ascii=False)}\n"
            f"Step results: {json.dumps(context['step_results'], ensure_ascii=False)}\n"
            "Return a complete renumbered plan JSON (goal + steps). "
            "Step ids must start at 1 and be continuous. "
            "Do not use markdown."
        )
        return [
            LLMMessage(role="system", content=self._replan_system_prompt),
            LLMMessage(role="user", content=user_content),
        ]

    async def _complete_replan_messages(
        self,
        messages: list[LLMMessage],
        *,
        context: str,
    ) -> list[PlanStep]:
        last_error: str | None = None
        for attempt in range(1, self._max_retries + 2):
            try:
                raw = await self._llm.complete(messages, response_json=True)
                steps = self._parse_replan_steps(raw)
                logger.info(
                    "%s replanned %d steps (attempt %d)",
                    context,
                    len(steps),
                    attempt,
                )
                return steps
            except (ValidationError, json.JSONDecodeError, ValueError) as exc:
                last_error = str(exc)
                messages.append(
                    LLMMessage(
                        role="user",
                        content=self._build_retry_feedback(last_error),
                    ),
                )

        if not isinstance(unwrap_llm_client(self._llm), RuleBasedLLMClient):
            try:
                return await self._fallback_rule_based_replan(messages)
            except (ValidationError, json.JSONDecodeError, ValueError) as exc:
                logger.warning("RuleBased %s replan fallback also failed: %s", context, exc)

        raise AgentLoopError(f"Failed to replan from {context} after retries: {last_error}")

    async def _fallback_rule_based_replan(self, messages: list[LLMMessage]) -> list[PlanStep]:
        logger.warning("Replan failed with real LLM; falling back to RuleBasedLLMClient")
        fallback = RuleBasedLLMClient()
        raw = await fallback.complete(messages, response_json=True)
        return self._parse_replan_steps(raw)

    def _build_retry_feedback(self, error: str) -> str:
        parts = [
            f"Your previous response was invalid: {error}.",
            "Return corrected JSON only.",
        ]
        if self._tool_registry is not None:
            available = ", ".join(self._tool_registry.list_names()) or "(none)"
            parts.append(
                f"Remember: tool_hint must exactly match a registered tool name. "
                f"Available tools: {available}.",
            )
        return " ".join(parts)

    @staticmethod
    def _parse_replan_steps(raw: str) -> list[PlanStep]:
        text = extract_json_text(raw)
        payload = json.loads(text)
        if isinstance(payload, list):
            return [PlanStep.model_validate(item) for item in payload]
        steps_payload = payload.get("steps", payload)
        return [PlanStep.model_validate(item) for item in steps_payload]

    @staticmethod
    def _parse_plan(raw: str) -> Plan:
        text = extract_json_text(raw)
        payload = json.loads(text)
        return Plan.model_validate(payload)
