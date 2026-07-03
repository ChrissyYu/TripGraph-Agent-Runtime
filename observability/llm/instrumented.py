"""LLM client wrapper that records latency and token usage."""

from __future__ import annotations

import time
from typing import Any

from config.settings import Settings, get_settings
from core.llm.base import LLMMessage
from core.llm.caller import detect_caller_from_messages
from core.llm.usage import LLMCompletion, LLMUsage, estimate_token_usage
from observability.metrics.collector import MetricsCollector
from persistence.context import current_execution_id


class InstrumentedLLMClient:
    """Wraps an LLM client and records metrics without changing call sites."""

    def __init__(
        self,
        inner: Any,
        collector: MetricsCollector,
        *,
        settings: Settings | None = None,
        model: str | None = None,
    ) -> None:
        self._inner = inner
        self._collector = collector
        self._settings = settings or get_settings()
        self._model = model

    def _default_model(self) -> str:
        if self._model:
            return self._model
        if self._settings.llm_provider == "qwen":
            return self._settings.qwen_model
        return self._settings.openai_model

    def _default_provider(self) -> str:
        return getattr(self._inner, "provider", self._settings.llm_provider)

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        response_json: bool = False,
    ) -> str:
        return (await self.complete_with_usage(messages, temperature=temperature, response_json=response_json)).text

    async def complete_with_usage(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        response_json: bool = False,
    ) -> LLMCompletion:
        caller = _detect_caller(messages)
        started = time.perf_counter()

        if hasattr(self._inner, "complete_with_usage"):
            result = await self._inner.complete_with_usage(
                messages,
                temperature=temperature,
                response_json=response_json,
            )
        else:
            text = await self._inner.complete(
                messages,
                temperature=temperature,
                response_json=response_json,
            )
            result = LLMCompletion(
                text=text,
                usage=estimate_token_usage(messages, text),
            )

        latency_ms = (time.perf_counter() - started) * 1000
        execution_id = current_execution_id.get()
        if execution_id and self._collector.enabled:
            model = result.model or self._default_model()
            provider = result.provider or self._default_provider()
            self._collector.record_llm_call(
                execution_id,
                caller=caller,
                latency_ms=latency_ms,
                usage=result.usage,
                model=model,
                provider=provider,
            )

        return result


def _detect_caller(messages: list[LLMMessage]) -> str:
    system = " ".join(message.content for message in messages if message.role == "system").lower()
    if "execution critic" in system:
        return "critic"
    if "compress plan execution context" in system:
        return "summarizer"
    if "tool selection router" in system or "tool router" in system:
        return "tool_router"
    if "replacement steps" in system or "replan" in system:
        return "planner_replan"
    detected = detect_caller_from_messages(messages)
    if detected == "router":
        return "tool_router"
    if detected == "replanner":
        return "planner_replan"
    return detected
