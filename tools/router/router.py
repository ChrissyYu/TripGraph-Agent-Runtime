"""Tool selection router — decoupled from Planner."""

from __future__ import annotations

from config.settings import Settings, get_settings
from core.llm.base import LLMClient
from schemas.tool_router import ToolRouterStrategy, ToolSelectionResult
from tools.registry import ToolRegistry
from tools.router.embedding import EmbeddingToolSelector
from tools.router.llm import LLMToolSelector
from tools.router.rule_based import RuleBasedToolSelector


class ToolSelectionRouter:
    """Route a step task to the best registered tool."""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        strategy: ToolRouterStrategy | str | None = None,
        llm: LLMClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._registry = registry
        cfg = settings or get_settings()
        raw_strategy = strategy or cfg.tool_router_strategy
        self._strategy = ToolRouterStrategy(raw_strategy)

        self._rule_based = RuleBasedToolSelector(registry)
        self._embedding = EmbeddingToolSelector(registry)
        self._llm = LLMToolSelector(registry, llm)

    @property
    def strategy(self) -> ToolRouterStrategy:
        return self._strategy

    async def select(self, task: str) -> ToolSelectionResult:
        if self._strategy == ToolRouterStrategy.RULE_BASED:
            payload = self._rule_based.select(task)
        elif self._strategy == ToolRouterStrategy.EMBEDDING:
            payload = self._embedding.select(task)
        else:
            payload = await self._llm.select(task)

        return ToolSelectionResult.model_validate(payload)

    def select_sync(self, task: str) -> ToolSelectionResult:
        """Synchronous selection for rule-based and embedding strategies."""
        if self._strategy == ToolRouterStrategy.LLM:
            raise RuntimeError("LLM strategy requires async select(); use await router.select(task)")
        if self._strategy == ToolRouterStrategy.RULE_BASED:
            payload = self._rule_based.select(task)
        else:
            payload = self._embedding.select(task)
        return ToolSelectionResult.model_validate(payload)
