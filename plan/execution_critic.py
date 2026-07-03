"""Evaluate plan execution quality after all steps finish."""

from __future__ import annotations

import json
from dataclasses import dataclass

from config.settings import Settings, get_settings
from core.llm.base import LLMClient, LLMMessage
from core.llm.factory import unwrap_llm_client
from core.llm.json_utils import extract_json_text
from core.llm.rule_based import RuleBasedLLMClient
from core.logging import get_logger
from plan.state import PlanState
from schemas.execution_critic import ExecutionCritique
from schemas.plan import StepStatus

logger = get_logger(__name__)

CRITIC_SYSTEM_PROMPT = """You are an execution critic for a travel planning agent.
Evaluate whether the plan execution satisfied the user's goal.

Return JSON only with this schema:
{
  "score": <float 0.0-1.0>,
  "critique": "<concise assessment>",
  "need_replan": <true|false>,
  "goal_completed": <true|false>,
  "missing_info": ["<missing item 1>", ...]
}

Judgment criteria:
1. goal_completed — Did execution produce enough information to fulfill the stated goal?
2. missing_info — List concrete gaps (e.g. missing budget, weather, route) or [] if none.
3. need_replan — true only when replanning would likely fix gaps; false if results are adequate.
4. score — 1.0 = fully satisfies goal; 0.0 = completely inadequate.

Rules:
- Base judgments on provided step results and tool outputs, not assumptions.
- Output strict JSON only. No markdown fences, no commentary, no explanations.
"""


@dataclass(frozen=True)
class ExecutionCriticConfig:
    enabled: bool = True


class RuleBasedExecutionCritic:
    """Deterministic critic for development and tests."""

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        response_json: bool = False,
    ) -> str:
        user_msgs = [m.content for m in messages if m.role == "user"]
        payload_text = user_msgs[-1] if user_msgs else "{}"
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            payload = {}

        return json.dumps(_evaluate_payload(payload), ensure_ascii=False)


class ExecutionCritic:
    """LLM-driven post-execution quality assessment."""

    def __init__(
        self,
        llm: LLMClient | None = None,
        *,
        config: ExecutionCriticConfig | None = None,
        settings: Settings | None = None,
    ) -> None:
        cfg = settings or get_settings()
        self._config = config or ExecutionCriticConfig(
            enabled=cfg.plan_execution_critic_enabled,
        )
        self._llm = llm or RuleBasedExecutionCritic()

    @property
    def config(self) -> ExecutionCriticConfig:
        return self._config

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    async def evaluate(
        self,
        state: PlanState,
        final_result: str,
    ) -> ExecutionCritique:
        if not self._config.enabled:
            raise RuntimeError("Execution critic is disabled")

        payload = self._build_payload(state, final_result)
        messages = [
            LLMMessage(role="system", content=CRITIC_SYSTEM_PROMPT),
            LLMMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
        ]
        last_error: str | None = None
        for attempt in range(1, 3):
            try:
                raw = await self._llm.complete(messages, response_json=True)
                text = extract_json_text(raw)
                critique = ExecutionCritique.model_validate(json.loads(text))
                logger.info(
                    "Execution critique: score=%.2f need_replan=%s goal_completed=%s",
                    critique.score,
                    critique.need_replan,
                    critique.goal_completed,
                )
                return critique
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                last_error = str(exc)
                logger.warning("Critic parse failed attempt %d: %s", attempt, last_error)
                if attempt < 2:
                    messages.append(
                        LLMMessage(
                            role="user",
                            content="Return corrected strict JSON only. No markdown or explanation.",
                        ),
                    )

        inner = unwrap_llm_client(self._llm)
        if not isinstance(inner, (RuleBasedLLMClient, RuleBasedExecutionCritic)):
            logger.warning("Critic parse failed with real LLM; falling back to RuleBasedExecutionCritic")
            fallback = RuleBasedExecutionCritic()
            raw = await fallback.complete(messages, response_json=True)
            text = extract_json_text(raw)
            return ExecutionCritique.model_validate(json.loads(text))

        raise ValueError(f"Failed to parse execution critique: {last_error}")

    @staticmethod
    def _build_payload(state: PlanState, final_result: str) -> dict:
        tool_outputs = state.global_context.get("tool_outputs", {})
        step_summaries = []
        for step in sorted(state.plan.steps, key=lambda s: s.id):
            result = state.step_results.get(step.id)
            step_summaries.append(
                {
                    "step_id": step.id,
                    "task": step.task,
                    "tool_hint": step.tool_hint,
                    "status": state.get_step_status(step.id).value,
                    "tool_name": result.tool_name if result else None,
                    "observation": result.observation if result else None,
                    "error": result.error if result else None,
                },
            )

        return {
            "goal": state.plan.goal,
            "user_query": state.global_context.get("user_query"),
            "final_result": final_result,
            "step_summaries": step_summaries,
            "tool_outputs": tool_outputs,
            "key_facts": state.global_context.get("key_facts", []),
            "compressed_context": state.global_context.get("compressed_context"),
            "unfinished_steps": state.unfinished_step_ids(),
            "failed_steps": [
                step_id
                for step_id, status in state._step_status.items()
                if status == StepStatus.FAILED
            ],
            "skipped_steps": [
                step_id
                for step_id, status in state._step_status.items()
                if status == StepStatus.SKIPPED
            ],
        }


def _evaluate_payload(payload: dict) -> dict:
    goal = payload.get("goal", "")
    tool_outputs = payload.get("tool_outputs") or {}
    step_summaries = payload.get("step_summaries") or []
    failed_steps = payload.get("failed_steps") or []
    skipped_steps = payload.get("skipped_steps") or []
    unfinished_steps = payload.get("unfinished_steps") or []

    missing_info: list[str] = []
    goal_lower = goal.lower()

    if "天气" in goal or "weather" in goal_lower:
        if "weather" not in tool_outputs:
            missing_info.append("weather forecast")
    if "预算" in goal or "budget" in goal_lower:
        if "budget" not in tool_outputs:
            missing_info.append("trip budget")
    if "路线" in goal or "route" in goal_lower or "map" in goal_lower:
        if "map" not in tool_outputs:
            missing_info.append("route plan")

    incomplete_steps = [
        s for s in step_summaries if s.get("status") not in ("completed", "skipped")
    ]
    if incomplete_steps:
        missing_info.append(f"{len(incomplete_steps)} step(s) not completed")

    has_failures = bool(failed_steps or skipped_steps or unfinished_steps)
    goal_completed = not missing_info and not has_failures
    need_replan = has_failures or bool(missing_info)

    completed_count = sum(1 for s in step_summaries if s.get("status") == "completed")
    total = max(len(step_summaries), 1)
    score = round(completed_count / total, 2)

    if missing_info:
        score = min(score, 0.6)
    if has_failures:
        score = min(score, 0.4)
    if goal_completed:
        score = max(score, 0.85)

    critique_parts = []
    if goal_completed:
        critique_parts.append("Execution satisfies the stated goal.")
    else:
        critique_parts.append("Execution does not fully satisfy the goal.")
    if missing_info:
        critique_parts.append(f"Missing: {', '.join(missing_info)}.")
    if has_failures:
        critique_parts.append("Some steps failed, were skipped, or remain unfinished.")

    return {
        "score": score,
        "critique": " ".join(critique_parts),
        "need_replan": need_replan,
        "goal_completed": goal_completed,
        "missing_info": missing_info,
    }
