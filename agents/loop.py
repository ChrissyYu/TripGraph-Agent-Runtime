"""Agent tool-calling loop: LLM → tool → observation → context → repeat."""

from __future__ import annotations

import json
from typing import Any, Protocol

from core.exceptions import AgentLoopError
from core.logging import get_logger
from schemas.agent import AgentLoopResult, AgentMessage, AgentRole
from schemas.tool import LLMOutputKind
from tools.executor import ToolExecutor

logger = get_logger(__name__)


class LLMProvider(Protocol):
    """Protocol for LLM backends invoked by the agent loop."""

    async def generate(self, messages: list[AgentMessage]) -> str | dict[str, Any]:
        """Return raw LLM output (tool call dict or final response)."""


class AgentLoop:
    """ReAct-style loop: call LLM, execute tools, feed observations back into context."""

    def __init__(
        self,
        executor: ToolExecutor,
        llm: LLMProvider,
        *,
        max_iterations: int = 10,
    ) -> None:
        self._executor = executor
        self._llm = llm
        self._max_iterations = max_iterations

    async def run(
        self,
        user_input: str,
        *,
        session_id: str = "default",
    ) -> AgentLoopResult:
        messages: list[AgentMessage] = [
            AgentMessage(role=AgentRole.USER, content=user_input),
        ]
        tool_call_order: list[str] = []

        for iteration in range(1, self._max_iterations + 1):
            raw = await self._llm.generate(messages)
            result = await self._executor.process_llm_output(raw)

            if result.kind == LLMOutputKind.PARSE_ERROR:
                raise AgentLoopError(result.error or "Failed to parse LLM output")

            if result.kind == LLMOutputKind.FINAL:
                messages.append(
                    AgentMessage(role=AgentRole.ASSISTANT, content=result.final or ""),
                )
                logger.info("Agent loop terminated after %d iterations", iteration)
                return AgentLoopResult(
                    session_id=session_id,
                    final_answer=result.final or "",
                    messages=messages,
                    tool_call_order=tool_call_order,
                    iterations=iteration,
                    terminated=True,
                )

            observation = result.observation
            if observation is None:
                raise AgentLoopError("Tool call result missing observation")

            tool_call_order.append(observation.tool)

            messages.append(
                AgentMessage(
                    role=AgentRole.ASSISTANT,
                    content=json.dumps(result.raw, ensure_ascii=False)
                    if isinstance(result.raw, dict)
                    else str(result.raw),
                    metadata={"type": "tool_call", "tool": observation.tool},
                ),
            )
            messages.append(
                AgentMessage(
                    role=AgentRole.TOOL,
                    content=observation.to_message(),
                    name=observation.tool,
                    metadata={"observation": observation.model_dump()},
                ),
            )

            if not observation.success:
                raise AgentLoopError(
                    observation.error or f"Tool '{observation.tool}' execution failed",
                )

            logger.debug(
                "Iteration %d: tool=%s, observation appended to context",
                iteration,
                observation.tool,
            )

        raise AgentLoopError(
            f"Agent loop exceeded max iterations ({self._max_iterations})",
        )
