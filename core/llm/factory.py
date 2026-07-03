"""LLM client factory and runtime routing."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from config.settings import Settings, get_settings
from core.exceptions import LLMClientError
from core.llm.base import LLMMessage
from core.llm.caller import detect_caller_from_messages
from core.llm.fallback_trace import classify_llm_error, record_fallback_event
from core.llm.rule_based import RuleBasedLLMClient
from core.llm.usage import LLMCompletion, estimate_token_usage

logger = logging.getLogger(__name__)


def is_deterministic_eval(settings: Settings) -> bool:
    return settings.eval_mode == "deterministic_eval"


def should_use_qwen(settings: Settings) -> bool:
    return (
        settings.llm_provider == "qwen"
        and bool(settings.qwen_api_key)
        and not is_deterministic_eval(settings)
    )


def should_use_openai(settings: Settings) -> bool:
    if is_deterministic_eval(settings):
        return False
    if settings.llm_provider == "qwen":
        return False
    if settings.llm_provider == "openai":
        return bool(settings.openai_api_key)
    return False


def unwrap_llm_client(client: Any) -> Any:
    """Return the innermost LLM client, skipping instrumentation wrappers."""
    seen: set[int] = set()
    current = client
    while hasattr(current, "_inner"):
        object_id = id(current)
        if object_id in seen:
            break
        seen.add(object_id)
        current = current._inner
    return current


def create_llm_client(settings: Settings | None = None, *, caller: str | None = None) -> Any:
    """Create a single-provider LLM client for the given settings and caller."""
    cfg = settings or get_settings()
    if is_deterministic_eval(cfg):
        return RuleBasedLLMClient()
    if should_use_qwen(cfg):
        from core.llm.qwen_client import QwenLLMClient

        return QwenLLMClient(cfg, caller=caller)
    if should_use_openai(cfg):
        from core.llm.openai_client import OpenAILLMClient

        return OpenAILLMClient(cfg)
    return RuleBasedLLMClient()


class AdaptiveLLMClient:
    """Routes LLM calls to Qwen/OpenAI/RuleBased based on settings and caller."""

    provider: str = "rule_based"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._rule_based = RuleBasedLLMClient()
        self._qwen_clients: dict[str, Any] = {}
        self._openai_client: Any | None = None
        self.provider = self._resolve_provider_label()

    def _resolve_provider_label(self) -> str:
        if is_deterministic_eval(self._settings):
            return "rule_based"
        if should_use_qwen(self._settings):
            return "qwen"
        if should_use_openai(self._settings):
            return "openai"
        return "rule_based"

    def _qwen_client(self, caller: str) -> Any:
        if caller not in self._qwen_clients:
            from core.llm.qwen_client import QwenLLMClient

            self._qwen_clients[caller] = QwenLLMClient(self._settings, caller=caller)
        return self._qwen_clients[caller]

    def _openai_client_instance(self) -> Any:
        if self._openai_client is None:
            from core.llm.openai_client import OpenAILLMClient

            self._openai_client = OpenAILLMClient(self._settings)
        return self._openai_client

    def _resolve_backend(self, messages: list[LLMMessage]) -> tuple[Any, str, str]:
        if is_deterministic_eval(self._settings):
            return self._rule_based, "rule_based", "rule_based"
        caller = detect_caller_from_messages(messages)
        if should_use_qwen(self._settings):
            client = self._qwen_client(caller)
            return client, "qwen", client.model
        if should_use_openai(self._settings):
            client = self._openai_client_instance()
            return client, "openai", self._settings.openai_model
        return self._rule_based, "rule_based", "rule_based"

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        response_json: bool = False,
    ) -> str:
        return (
            await self.complete_with_usage(
                messages,
                temperature=temperature,
                response_json=response_json,
            )
        ).text

    async def complete_with_usage(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        response_json: bool = False,
    ) -> LLMCompletion:
        client, provider, model = self._resolve_backend(messages)
        try:
            if hasattr(client, "complete_with_usage"):
                result = await client.complete_with_usage(
                    messages,
                    temperature=temperature,
                    response_json=response_json,
                )
            else:
                text = await client.complete(
                    messages,
                    temperature=temperature,
                    response_json=response_json,
                )
                result = LLMCompletion(
                    text=text,
                    usage=estimate_token_usage(messages, text),
                )
            if not result.model:
                result.model = model
            if not result.provider:
                result.provider = provider
            return result
        except (LLMClientError, ValueError, httpx.TimeoutException, httpx.HTTPError) as exc:
            if isinstance(client, RuleBasedLLMClient):
                raise
            caller = detect_caller_from_messages(messages)
            record_fallback_event(
                caller=caller,
                from_provider=provider,
                reason=str(exc),
                error=exc,
            )
            logger.warning(
                "LLM call failed (provider=%s model=%s caller=%s), falling back to RuleBased: %s",
                provider,
                model,
                caller,
                exc,
            )
            text = await self._rule_based.complete(
                messages,
                temperature=temperature,
                response_json=response_json,
            )
            return LLMCompletion(
                text=text,
                usage=estimate_token_usage(messages, text),
                model="rule_based",
                provider="rule_based",
            )


def create_runtime_llm(settings: Settings, observability: Any):
    """Create the instrumented adaptive LLM client used at runtime."""
    from observability.bootstrap import wrap_llm_client

    inner = AdaptiveLLMClient(settings)
    return wrap_llm_client(inner, observability, settings=settings)
