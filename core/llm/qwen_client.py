"""Qwen (DashScope OpenAI-compatible) LLM client."""

from __future__ import annotations

import asyncio
import json
import logging

import httpx

from config.settings import Settings, get_settings
from core.exceptions import LLMClientError
from core.llm.base import LLMMessage
from core.llm.usage import LLMCompletion, LLMUsage, estimate_token_usage

logger = logging.getLogger(__name__)


class QwenLLMClient:
    """Calls Alibaba Cloud Bailian OpenAI-compatible Chat Completions API."""

    provider: str = "qwen"

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        caller: str | None = None,
        model: str | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        if not self._settings.qwen_api_key:
            raise ValueError("QWEN_API_KEY is required for QwenLLMClient")
        self._caller = caller
        self._model_override = model

    @property
    def model(self) -> str:
        if self._model_override:
            return self._model_override
        return self._settings.resolve_qwen_model(self._caller)

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        response_json: bool = False,
        max_tokens: int | None = None,
    ) -> str:
        return (
            await self.complete_with_usage(
                messages,
                temperature=temperature,
                response_json=response_json,
                max_tokens=max_tokens,
            )
        ).text

    async def complete_with_usage(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        response_json: bool = False,
        max_tokens: int | None = None,
    ) -> LLMCompletion:
        temp = self._settings.qwen_temperature if temperature is None else temperature
        tokens = self._settings.qwen_max_tokens if max_tokens is None else max_tokens
        payload: dict = {
            "model": self.model,
            "messages": [m.model_dump() for m in messages],
            "temperature": temp,
            "max_tokens": tokens,
        }
        if response_json:
            payload["response_format"] = {"type": "json_object"}

        last_error: Exception | None = None
        retries = max(0, self._settings.qwen_max_retries)
        for attempt in range(retries + 1):
            try:
                return await self._post_completion(payload, messages)
            except (httpx.HTTPError, LLMClientError) as exc:
                last_error = exc
                if attempt < retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    logger.warning(
                        "Qwen API attempt %s failed, retrying: %s",
                        attempt + 1,
                        exc,
                    )
                    continue
                break

        raise LLMClientError(
            f"Qwen API call failed after {retries + 1} attempt(s): {last_error}",
        ) from last_error

    async def _post_completion(
        self,
        payload: dict,
        messages: list[LLMMessage],
    ) -> LLMCompletion:
        base_url = self._settings.qwen_base_url.rstrip("/")
        url = f"{base_url}/chat/completions"
        timeout = httpx.Timeout(self._settings.qwen_timeout_sec)

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {self._settings.qwen_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if response.status_code >= 400:
                raise LLMClientError(
                    f"Qwen API error {response.status_code}: {response.text[:500]}",
                )
            data = response.json()

        choices = data.get("choices") or []
        if not choices:
            raise LLMClientError("Qwen API returned no choices")

        content = choices[0].get("message", {}).get("content")
        if content is None:
            raise LLMClientError("Qwen API returned empty content")
        if not isinstance(content, str):
            content = json.dumps(content)

        usage_data = data.get("usage") or {}
        if usage_data:
            usage = LLMUsage(
                prompt_tokens=int(usage_data.get("prompt_tokens", 0)),
                completion_tokens=int(usage_data.get("completion_tokens", 0)),
                total_tokens=int(usage_data.get("total_tokens", 0)),
                estimated=False,
            )
        else:
            usage = estimate_token_usage(messages, content)

        return LLMCompletion(text=content, usage=usage, model=self.model, provider=self.provider)
