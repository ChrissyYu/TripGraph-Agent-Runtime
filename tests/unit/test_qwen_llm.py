"""Unit tests for Qwen LLM integration (no real API calls)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from agents.planner import PlannerAgent
from config.settings import Settings, get_settings
from core.llm.factory import (
    AdaptiveLLMClient,
    create_llm_client,
    is_deterministic_eval,
    should_use_qwen,
    unwrap_llm_client,
)
from core.llm.json_utils import extract_json_text
from core.llm.qwen_client import QwenLLMClient
from core.llm.rule_based import RuleBasedLLMClient
from core.llm.base import LLMMessage
from observability.bootstrap import build_observability, wrap_llm_client
from observability.llm.instrumented import InstrumentedLLMClient


PLAN_JSON = {
    "goal": "上海3日游",
    "steps": [{"id": 1, "task": "查天气", "tool_hint": "weather", "dependency": []}],
}


def _mock_qwen_response(*, content: str, usage: dict | None = "__default__") -> httpx.Response:
    payload: dict = {
        "choices": [{"message": {"content": content}}],
    }
    if usage != "__default__":
        if usage is not None:
            payload["usage"] = usage
    else:
        payload["usage"] = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
    request = httpx.Request("POST", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
    return httpx.Response(200, json=payload, request=request)


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_settings_load_qwen_env(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "qwen")
    monkeypatch.setenv("QWEN_API_KEY", "test-key")
    monkeypatch.setenv("QWEN_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("QWEN_MODEL", "qwen-test")
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.llm_provider == "qwen"
    assert settings.qwen_api_key == "test-key"
    assert settings.qwen_base_url == "https://example.com/v1"
    assert settings.qwen_model == "qwen-test"
    assert settings.resolve_qwen_model("planner") == settings.qwen_planner_model


def test_factory_returns_qwen_when_configured() -> None:
    settings = Settings(llm_provider="qwen", qwen_api_key="k", eval_mode="auto")
    client = create_llm_client(settings, caller="planner")
    assert isinstance(client, QwenLLMClient)
    assert client.model == settings.qwen_planner_model


def test_factory_fallback_without_qwen_key() -> None:
    settings = Settings(llm_provider="qwen", qwen_api_key=None, eval_mode="auto")
    client = create_llm_client(settings)
    assert isinstance(client, RuleBasedLLMClient)


def test_deterministic_eval_ignores_qwen_config() -> None:
    settings = Settings(llm_provider="qwen", qwen_api_key="k", eval_mode="deterministic_eval")
    assert is_deterministic_eval(settings)
    assert not should_use_qwen(settings)
    client = create_llm_client(settings, caller="planner")
    assert isinstance(client, RuleBasedLLMClient)


@pytest.mark.asyncio
async def test_qwen_client_mocked_response() -> None:
    settings = Settings(
        llm_provider="qwen",
        qwen_api_key="test-key",
        qwen_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        qwen_planner_model="qwen3.7-plus",
    )
    client = QwenLLMClient(settings, caller="planner")
    messages = [LLMMessage(role="user", content="hello")]

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = _mock_qwen_response(content='{"ok": true}')
        result = await client.complete_with_usage(messages, response_json=True)

    assert result.text == '{"ok": true}'
    assert result.model == "qwen3.7-plus"
    assert result.provider == "qwen"
    assert result.usage.prompt_tokens == 10
    assert result.usage.estimated is False


@pytest.mark.asyncio
async def test_qwen_client_estimates_tokens_without_usage() -> None:
    settings = Settings(llm_provider="qwen", qwen_api_key="test-key")
    client = QwenLLMClient(settings)
    messages = [LLMMessage(role="user", content="hello world")]

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = _mock_qwen_response(content="hi", usage=None)
        result = await client.complete_with_usage(messages)

    assert result.usage.estimated is True
    assert result.usage.total_tokens > 0


def test_extract_json_plain_and_markdown() -> None:
    plain = json.dumps(PLAN_JSON, ensure_ascii=False)
    assert json.loads(extract_json_text(plain)) == PLAN_JSON

    fenced = f"```json\n{plain}\n```"
    assert json.loads(extract_json_text(fenced)) == PLAN_JSON


@pytest.mark.asyncio
async def test_planner_parses_markdown_json() -> None:
    planner = PlannerAgent(RuleBasedLLMClient(), max_retries=0)
    raw = f"```json\n{json.dumps(PLAN_JSON, ensure_ascii=False)}\n```"
    plan = planner._parse_plan(raw)
    assert plan.goal == "上海3日游"
    assert len(plan.steps) == 1


@pytest.mark.asyncio
async def test_instrumented_records_qwen_provider_and_model() -> None:
    settings = Settings(
        metrics_enabled=True,
        llm_provider="qwen",
        qwen_api_key="k",
        qwen_model="qwen3.7-plus",
    )
    bundle = build_observability(settings)
    assert bundle.collector is not None
    await bundle.collector.start()

    class _StubQwen:
        provider = "qwen"

        async def complete_with_usage(self, messages, **kwargs):
            from core.llm.usage import LLMCompletion, LLMUsage

            return LLMCompletion(
                text='{"goal":"x","steps":[]}',
                usage=LLMUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
                model="qwen3.7-plus",
                provider="qwen",
            )

    instrumented = wrap_llm_client(_StubQwen(), bundle, settings=settings)
    assert isinstance(instrumented, InstrumentedLLMClient)

    from observability.metrics.models import ExecutionMetrics
    from persistence.context import current_execution_id

    bundle.collector.record_execution_start(
        ExecutionMetrics(
            execution_id="exec-qwen-test",
            session_id="sess",
            trace_id="trace",
        ),
    )
    token = current_execution_id.set("exec-qwen-test")
    try:
        await instrumented.complete(
            [
                LLMMessage(role="system", content="You are a travel planning assistant."),
                LLMMessage(role="user", content="plan"),
            ],
            response_json=True,
        )
        await bundle.collector.drain()
    finally:
        current_execution_id.reset(token)

    metrics = bundle.store.get("exec-qwen-test")
    assert metrics is not None
    assert metrics.llm_calls
    call = metrics.llm_calls[0]
    assert call.provider == "qwen"
    assert call.model == "qwen3.7-plus"
    assert call.caller == "planner"
    await bundle.collector.stop()


@pytest.mark.asyncio
async def test_adaptive_client_uses_rule_based_in_deterministic_eval() -> None:
    settings = Settings(
        llm_provider="qwen",
        qwen_api_key="k",
        eval_mode="deterministic_eval",
    )
    client = AdaptiveLLMClient(settings)
    messages = [
        LLMMessage(role="system", content="You are a travel planning assistant."),
        LLMMessage(role="user", content="规划上海3日游"),
    ]
    result = await client.complete_with_usage(messages, response_json=True)
    assert result.provider == "rule_based"
    assert "steps" in result.text


def test_unwrap_llm_client_skips_instrumentation() -> None:
    settings = Settings(metrics_enabled=True)
    bundle = build_observability(settings)
    inner = RuleBasedLLMClient()
    wrapped = wrap_llm_client(inner, bundle, settings=settings)
    assert isinstance(unwrap_llm_client(wrapped), RuleBasedLLMClient)
