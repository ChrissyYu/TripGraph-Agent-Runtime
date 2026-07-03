"""Tool call execution with tracing and reliability (retry / timeout / fallback)."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from config.settings import Settings, get_settings
from core.exceptions import ToolExecutionError, ToolTimeoutError
from core.logging import get_logger
from schemas.tool import (
    LLMExecutionResult,
    LLMOutputKind,
    LLMOutputParser,
    LLMToolCall,
    ToolCall,
    ToolCallResult,
    ToolObservation,
)
from tools.base import BaseTool
from tools.registry import ToolRegistry
from tools.reliability import ToolReliabilityPolicy
from tools.tracing import ToolTracer

logger = get_logger(__name__)


class ToolExecutor:
    """Executes tool calls against a registry with tracing and reliability."""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        tracer: ToolTracer | None = None,
        debug_trace: bool | None = None,
        reliability: ToolReliabilityPolicy | None = None,
        max_retries: int | None = None,
        timeout_sec: float | None = None,
        fallback_tools: dict[str, str] | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._registry = registry
        cfg = settings or get_settings()
        trace_debug = debug_trace if debug_trace is not None else cfg.tool_trace_debug
        self._tracer = tracer or ToolTracer(debug=trace_debug)

        if reliability is not None:
            self._reliability = reliability
        else:
            self._reliability = ToolReliabilityPolicy(
                max_retries=max_retries if max_retries is not None else cfg.tool_max_retries,
                timeout_sec=timeout_sec if timeout_sec is not None else cfg.tool_timeout_sec,
                fallback_tools=fallback_tools or {},
            )

    @property
    def tracer(self) -> ToolTracer:
        return self._tracer

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    @property
    def reliability(self) -> ToolReliabilityPolicy:
        return self._reliability

    async def execute(self, call: ToolCall) -> ToolCallResult:
        observation = await self.execute_llm_call(
            LLMToolCall(tool=call.name, args=call.arguments),
            call_id=call.call_id,
        )
        return ToolCallResult(
            call_id=call.call_id,
            name=call.name,
            output=observation.output,
            success=observation.success,
            error=observation.error,
        )

    async def execute_llm_call(
        self,
        llm_call: LLMToolCall | dict[str, Any] | str,
        *,
        call_id: str | None = None,
        parent_id: str | None = None,
    ) -> ToolObservation:
        """Execute an LLM-formatted tool call and return an observation."""
        if not isinstance(llm_call, LLMToolCall):
            llm_call = LLMToolCall.parse(llm_call)

        call_id = call_id or str(uuid4())
        observation = await self._execute_with_reliability(
            tool_name=llm_call.tool,
            args=llm_call.args,
            call_id=call_id,
            parent_id=parent_id,
            requested_tool=llm_call.tool,
        )
        return observation

    async def _execute_with_reliability(
        self,
        *,
        tool_name: str,
        args: dict[str, Any],
        call_id: str,
        parent_id: str | None,
        requested_tool: str,
        is_fallback: bool = False,
    ) -> ToolObservation:
        observation = await self._try_with_retries(
            tool_name=tool_name,
            args=args,
            call_id=call_id,
            parent_id=parent_id,
            is_fallback=is_fallback,
            original_tool=requested_tool if is_fallback else None,
        )
        if observation.success:
            return observation.model_copy(update={"tool": requested_tool})

        if not is_fallback:
            fallback_name = self._reliability.fallback_tools.get(requested_tool)
            if fallback_name:
                logger.warning(
                    "Tool %s failed after retries; invoking fallback %s",
                    requested_tool,
                    fallback_name,
                )
                return await self._execute_with_reliability(
                    tool_name=fallback_name,
                    args=args,
                    call_id=f"{call_id}-fallback",
                    parent_id=parent_id,
                    requested_tool=requested_tool,
                    is_fallback=True,
                )

        return observation.model_copy(update={"tool": requested_tool})

    async def _try_with_retries(
        self,
        *,
        tool_name: str,
        args: dict[str, Any],
        call_id: str,
        parent_id: str | None,
        is_fallback: bool,
        original_tool: str | None,
    ) -> ToolObservation:
        max_attempts = self._reliability.max_attempts
        last_error: str | None = None

        for attempt in range(1, max_attempts + 1):
            attempt_id = call_id if attempt == 1 else f"{call_id}-retry-{attempt}"
            with self._tracer.trace_tool_call(
                call_id=attempt_id,
                tool_name=tool_name,
                input_args=args,
                parent_id=parent_id,
                attempt=attempt,
                max_attempts=max_attempts,
                is_fallback=is_fallback,
                original_tool=original_tool,
            ) as timer:
                try:
                    tool = self._registry.get(tool_name)
                    output = await self._run_with_timeout(tool, args)
                    timer.set_result(output=output, success=True)
                    logger.info(
                        "Tool %s executed successfully (call_id=%s, attempt=%d/%d)",
                        tool_name,
                        attempt_id,
                        attempt,
                        max_attempts,
                    )
                    return ToolObservation(
                        tool=tool_name,
                        args=args,
                        output=output,
                        success=True,
                    )
                except Exception as exc:
                    last_error = str(exc)
                    timer.set_result(output=None, success=False, error=last_error)
                    logger.warning(
                        "Tool %s attempt %d/%d failed: %s",
                        tool_name,
                        attempt,
                        max_attempts,
                        last_error,
                    )

        return ToolObservation(
            tool=tool_name,
            args=args,
            output=None,
            success=False,
            error=last_error,
        )

    async def _run_with_timeout(self, tool: BaseTool, args: dict[str, Any]) -> Any:
        timeout = self._reliability.timeout_sec
        if timeout is None:
            return await tool.run(args)

        try:
            return await asyncio.wait_for(tool.run(args), timeout=timeout)
        except TimeoutError as exc:
            raise ToolTimeoutError(
                f"Tool '{tool.name}' timed out after {timeout}s",
            ) from exc

    async def execute_batch(self, calls: list[ToolCall]) -> list[ToolCallResult]:
        batch_id = str(uuid4())
        results: list[ToolCallResult] = []

        with self._tracer.trace_tool_call(
            call_id=batch_id,
            tool_name="__batch__",
            input_args={"tools": [c.name for c in calls]},
            parent_id=None,
        ) as batch_timer:
            for call in calls:
                observation = await self.execute_llm_call(
                    LLMToolCall(tool=call.name, args=call.arguments),
                    call_id=call.call_id,
                    parent_id=batch_id,
                )
                result = ToolCallResult(
                    call_id=call.call_id,
                    name=call.name,
                    output=observation.output,
                    success=observation.success,
                    error=observation.error,
                )
                results.append(result)
                if not result.success:
                    batch_timer.set_result(
                        output=None,
                        success=False,
                        error=result.error or f"Tool {call.name} failed",
                    )
                    raise ToolExecutionError(result.error or f"Tool {call.name} failed")

            batch_timer.set_result(
                output={"results": [r.model_dump() for r in results]},
                success=True,
            )

        return results

    async def execute_llm_batch(
        self,
        calls: list[LLMToolCall | dict[str, Any] | str],
    ) -> list[ToolObservation]:
        batch_id = str(uuid4())
        observations: list[ToolObservation] = []

        with self._tracer.trace_tool_call(
            call_id=batch_id,
            tool_name="__batch__",
            input_args={"count": len(calls)},
            parent_id=None,
        ) as batch_timer:
            for call in calls:
                obs = await self.execute_llm_call(call, parent_id=batch_id)
                observations.append(obs)

            batch_timer.set_result(
                output={"observations": len(observations)},
                success=all(o.success for o in observations),
            )

        return observations

    def export_trace_json(self, *, indent: int = 2) -> str:
        """Export all trace records as a JSON log string."""
        return self._tracer.export_json(indent=indent)

    def print_trace_tree(self) -> str:
        """Print the full trace tree (debug mode helper)."""
        return self._tracer.print_trace_tree()

    async def process_llm_output(
        self,
        raw: str | dict[str, Any],
        *,
        call_id: str | None = None,
    ) -> LLMExecutionResult:
        """Parse and dispatch raw LLM output (tool call, final answer, or error)."""
        parsed = LLMOutputParser.parse(raw)

        if parsed.kind == LLMOutputKind.PARSE_ERROR:
            return parsed

        if parsed.kind == LLMOutputKind.FINAL:
            return parsed

        tool_call = LLMOutputParser.to_tool_call(parsed)
        observation = await self.execute_llm_call(tool_call, call_id=call_id)
        return LLMExecutionResult(
            kind=LLMOutputKind.TOOL_CALL,
            observation=observation,
            raw=raw,
        )
