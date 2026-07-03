"""Integration test: agent loop with weather → budget → final answer."""

from __future__ import annotations

import json
from typing import Any

import pytest

from agents.loop import AgentLoop
from schemas.agent import AgentLoopResult, AgentMessage, AgentRole
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry

USER_QUERY = "查询上海天气并计算3天旅行预算"


class TripPlannerMockLLM:
    """Context-aware mock LLM that drives weather → budget → final."""

    def __init__(self) -> None:
        self.call_log: list[list[AgentMessage]] = []

    async def generate(self, messages: list[AgentMessage]) -> dict[str, Any]:
        self.call_log.append(list(messages))

        tool_messages = [m for m in messages if m.role == AgentRole.TOOL]
        tool_names = [m.name for m in tool_messages]

        if "weather" not in tool_names:
            return {"tool": "weather", "args": {"city": "上海", "date": "today"}}

        if "budget" not in tool_names:
            return {
                "tool": "budget",
                "args": {"days": 3, "daily_food": 200.0, "currency": "CNY"},
            }

        weather_meta = next(m.metadata["observation"] for m in tool_messages if m.name == "weather")
        budget_meta = next(m.metadata["observation"] for m in tool_messages if m.name == "budget")

        return {
            "final": (
                f"上海天气：{weather_meta['output']['condition']}，"
                f"气温 {weather_meta['output']['temp_c']}°C；"
                f"3天旅行预算总计 {budget_meta['output']['total']} {budget_meta['output']['currency']}。"
            ),
        }


@pytest.fixture
def tool_registry() -> ToolRegistry:
    return ToolRegistry.default()


@pytest.fixture
def executor(tool_registry: ToolRegistry) -> ToolExecutor:
    return ToolExecutor(tool_registry)


@pytest.fixture
def mock_llm() -> TripPlannerMockLLM:
    return TripPlannerMockLLM()


@pytest.fixture
def agent_loop(executor: ToolExecutor, mock_llm: TripPlannerMockLLM) -> AgentLoop:
    return AgentLoop(executor=executor, llm=mock_llm, max_iterations=5)


def _tool_messages(result: AgentLoopResult) -> list[AgentMessage]:
    return [m for m in result.messages if m.role == AgentRole.TOOL]


@pytest.mark.asyncio
async def test_agent_loop_weather_then_budget_then_final(
    agent_loop: AgentLoop,
    mock_llm: TripPlannerMockLLM,
) -> None:
    result = await agent_loop.run(USER_QUERY, session_id="trip-001")

    # --- loop terminated with final answer ---
    assert isinstance(result, AgentLoopResult)
    assert result.terminated is True
    assert result.iterations == 3
    assert result.session_id == "trip-001"
    assert "上海" in result.final_answer
    assert "预算" in result.final_answer or "CNY" in result.final_answer

    # --- tool call order ---
    assert result.tool_call_order == ["weather", "budget"]

    # --- observations entered context ---
    tool_msgs = _tool_messages(result)
    assert len(tool_msgs) == 2
    assert [m.name for m in tool_msgs] == ["weather", "budget"]

    weather_obs = tool_msgs[0].metadata["observation"]
    budget_obs = tool_msgs[1].metadata["observation"]
    assert weather_obs["success"] is True
    assert weather_obs["output"]["city"] == "上海"
    assert "temp_c" in weather_obs["output"]
    assert budget_obs["success"] is True
    assert budget_obs["output"]["days"] == 3
    assert budget_obs["output"]["total"] > 0

    # observation text is present in TOOL role messages
    assert "weather" in tool_msgs[0].content
    assert "budget" in tool_msgs[1].content

    # --- LLM saw observations before subsequent steps ---
    assert len(mock_llm.call_log) == 3

    # 1st LLM call: only user message
    assert len(mock_llm.call_log[0]) == 1
    assert mock_llm.call_log[0][0].role == AgentRole.USER

    # 2nd LLM call: user + weather tool_call assistant + weather observation
    assert any(m.role == AgentRole.TOOL and m.name == "weather" for m in mock_llm.call_log[1])
    assert not any(m.name == "budget" for m in mock_llm.call_log[1])

    # 3rd LLM call: context includes both weather and budget observations
    third_call_tools = [m.name for m in mock_llm.call_log[2] if m.role == AgentRole.TOOL]
    assert third_call_tools == ["weather", "budget"]

    # --- message transcript structure ---
    roles = [m.role for m in result.messages]
    assert roles[0] == AgentRole.USER
    assert roles[-1] == AgentRole.ASSISTANT
    assert roles.count(AgentRole.TOOL) == 2

    # final assistant message matches final_answer
    assert result.messages[-1].content == result.final_answer

    # final answer incorporates observation data
    assert str(weather_obs["output"]["temp_c"]) in result.final_answer
    assert str(budget_obs["output"]["total"]) in result.final_answer


@pytest.mark.asyncio
async def test_agent_loop_observation_payload_is_valid_json(
    agent_loop: AgentLoop,
) -> None:
    result = await agent_loop.run(USER_QUERY)

    for tool_msg in _tool_messages(result):
        obs = tool_msg.metadata["observation"]
        restored = json.loads(json.dumps(obs, ensure_ascii=False))
        assert restored["tool"] == tool_msg.name
        assert restored["success"] is True
        assert restored["output"] is not None
