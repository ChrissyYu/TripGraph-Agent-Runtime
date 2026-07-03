"""Compress plan global_context when it exceeds a size threshold."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from config.settings import Settings, get_settings
from core.llm.base import LLMClient, LLMMessage
from core.logging import get_logger
from plan.state import PlanState
from schemas.context_compression import ContextCompressionResult

logger = get_logger(__name__)

COMPRESSION_SYSTEM_PROMPT = """You compress plan execution context for a travel planning agent.
Summarize verbose history while preserving decision-relevant information.

Return JSON only with this schema:
{
  "compressed_context": "<concise narrative summary of execution so far>",
  "key_facts": ["<atomic fact 1>", "<atomic fact 2>"]
}

Rules:
- key_facts must be short, factual bullets (weather, routes, budget totals, cities, dates)
- Do not invent data not present in the input
- Output JSON only, no markdown fences
"""

# Keys required by StepToolResolver and downstream steps — never dropped.
PRESERVED_CONTEXT_KEYS = frozenset(
    {
        "user_query",
        "city",
        "days",
        "date",
        "destination",
        "origin",
        "transport_mode",
        "currency",
        "daily_food",
        "daily_transport",
        "daily_accommodation",
        "activities",
        "tool_args",
        "tool_outputs",
        "step_outputs",
    },
)


@dataclass(frozen=True)
class ContextCompressionConfig:
    enabled: bool = True
    max_chars: int = 2000


class RuleBasedContextSummarizer:
    """Deterministic summarizer for development and tests."""

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
            payload = {"raw": payload_text}

        goal = payload.get("goal", "")
        step_outputs = payload.get("step_outputs", {})
        tool_outputs = payload.get("tool_outputs", {})
        misc = payload.get("misc", {})

        facts: list[str] = []
        for tool_name, output in tool_outputs.items():
            if isinstance(output, dict):
                summary = ", ".join(f"{k}={v}" for k, v in list(output.items())[:4])
                facts.append(f"{tool_name}: {summary}")
            else:
                facts.append(f"{tool_name}: {output}")

        for step_id, output in step_outputs.items():
            if isinstance(output, dict) and len(facts) < 12:
                snippet = json.dumps(output, ensure_ascii=False)[:120]
                facts.append(f"step {step_id}: {snippet}")

        for key, value in misc.items():
            if len(facts) >= 12:
                break
            facts.append(f"{key}: {value}")

        compressed = (
            f"Goal: {goal}. "
            f"Compressed {len(step_outputs)} step output(s) and {len(tool_outputs)} tool output(s)."
        )
        if misc:
            compressed += f" Retained misc keys: {', '.join(sorted(misc.keys()))}."

        return json.dumps(
            {
                "compressed_context": compressed,
                "key_facts": facts or ["No structured outputs to summarize"],
            },
            ensure_ascii=False,
        )


class ContextCompressor:
    """Triggers LLM summarization when global_context exceeds threshold."""

    def __init__(
        self,
        summarizer: LLMClient | None = None,
        *,
        config: ContextCompressionConfig | None = None,
        settings: Settings | None = None,
    ) -> None:
        cfg = settings or get_settings()
        self._config = config or ContextCompressionConfig(
            enabled=cfg.plan_context_compression_enabled,
            max_chars=cfg.plan_context_max_chars,
        )
        self._summarizer = summarizer or RuleBasedContextSummarizer()

    @property
    def config(self) -> ContextCompressionConfig:
        return self._config

    def estimate_size(self, context: dict[str, Any]) -> int:
        return len(json.dumps(context, ensure_ascii=False))

    def should_compress(self, context: dict[str, Any]) -> bool:
        if not self._config.enabled:
            return False
        return self.estimate_size(context) > self._config.max_chars

    async def maybe_compress(self, state: PlanState) -> bool:
        if not self.should_compress(state.global_context):
            return False
        await self.compress(state)
        return True

    async def compress(self, state: PlanState) -> ContextCompressionResult:
        original_size = self.estimate_size(state.global_context)
        preserved = self._extract_preserved(state.global_context)
        compressible = self._extract_compressible(state)

        summary = await self._summarize(state, compressible)
        state.global_context = self._build_replaced_context(
            state,
            preserved=preserved,
            summary=summary,
            original_size=original_size,
        )

        new_size = self.estimate_size(state.global_context)
        logger.info(
            "Context compressed: session=%s size %d -> %d (step=%s)",
            state.session_id,
            original_size,
            new_size,
            state.current_step,
        )
        return summary

    async def _summarize(self, state: PlanState, compressible: dict[str, Any]) -> ContextCompressionResult:
        payload = json.dumps(
            {
                "goal": state.plan.goal,
                **compressible,
            },
            ensure_ascii=False,
        )
        messages = [
            LLMMessage(role="system", content=COMPRESSION_SYSTEM_PROMPT),
            LLMMessage(role="user", content=payload),
        ]
        raw = await self._summarizer.complete(messages, response_json=True)
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\n?", "", text)
            text = re.sub(r"\n?```$", "", text).strip()
        return ContextCompressionResult.model_validate(json.loads(text))

    @staticmethod
    def _extract_preserved(context: dict[str, Any]) -> dict[str, Any]:
        preserved: dict[str, Any] = {}
        for key in PRESERVED_CONTEXT_KEYS:
            if key in context:
                preserved[key] = context[key]
        return preserved

    @staticmethod
    def _extract_compressible(state: PlanState) -> dict[str, Any]:
        context = state.global_context
        misc = {
            key: value
            for key, value in context.items()
            if key not in PRESERVED_CONTEXT_KEYS
            and not key.startswith("_")
            and key not in ("compressed_context", "key_facts")
        }
        return {
            "step_outputs": context.get("step_outputs", {}),
            "tool_outputs": context.get("tool_outputs", {}),
            "misc": misc,
            "step_status": {
                str(step_id): status.value for step_id, status in state._step_status.items()
            },
        }

    def _build_replaced_context(
        self,
        state: PlanState,
        *,
        preserved: dict[str, Any],
        summary: ContextCompressionResult,
        original_size: int,
    ) -> dict[str, Any]:
        prior_meta = state.global_context.get("_compression_meta", {})
        prior_count = int(prior_meta.get("compression_count", 0))

        new_context: dict[str, Any] = dict(preserved)
        new_context["compressed_context"] = summary.compressed_context
        new_context["key_facts"] = summary.key_facts
        new_context["_compression_meta"] = {
            "compression_count": prior_count + 1,
            "triggered_at_step": state.current_step,
            "size_before": original_size,
            "size_after": self.estimate_size(new_context),
        }
        return new_context
