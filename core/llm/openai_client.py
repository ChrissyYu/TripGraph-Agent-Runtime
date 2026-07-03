"""OpenAI-compatible LLM client."""

from __future__ import annotations

import json

import httpx

from config.settings import Settings, get_settings
from core.llm.base import LLMMessage
from core.llm.usage import LLMCompletion, LLMUsage, estimate_token_usage


class OpenAILLMClient:
    """Calls OpenAI Chat Completions API via httpx."""

    provider: str = "openai"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        if not self._settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAILLMClient")

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
        payload: dict = {
            "model": self._settings.openai_model,
            "messages": [m.model_dump() for m in messages],
            "temperature": temperature,
        }
        if response_json:
            payload["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        content = data["choices"][0]["message"]["content"]
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

        return LLMCompletion(
            text=content,
            usage=usage,
            model=self._settings.openai_model,
            provider=self.provider,
        )
