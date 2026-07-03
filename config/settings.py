"""Centralized application settings via pydantic-settings."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "TripPlan Multi-Agent"
    app_version: str = "0.8.0"
    debug: bool = False
    environment: Literal["development", "staging", "production"] = "development"

    api_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])

    # Server / deployment (Phase 8)
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1
    reload: bool = False

    # LLM / workflow
    llm_provider: Literal["rule_based", "openai", "qwen"] = "rule_based"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o"
    qwen_api_key: str | None = None
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_model: str = "qwen3.7-plus"
    qwen_planner_model: str = "qwen3.7-plus"
    qwen_critic_model: str = "qwen3.7-plus"
    qwen_replanner_model: str = "qwen3.7-plus"
    qwen_summarizer_model: str = "qwen3.6-flash"
    qwen_router_model: str = "qwen3.6-flash"
    qwen_temperature: float = 0.0
    qwen_max_tokens: int = 2048
    qwen_timeout_sec: float = 120.0
    qwen_max_retries: int = 1
    langgraph_enabled: bool = False

    # Smoke / manual validation (Phase 9A.3)
    smoke_max_replan_attempts: int | None = None

    # Memory
    short_term_max_messages: int = 50
    long_term_store_path: str = "./data/long_term_memory"

    # Streaming
    sse_retry_ms: int = 3000
    sse_heartbeat_interval_sec: int = 15

    # Tool tracing & reliability
    tool_trace_debug: bool = False
    tool_max_retries: int = 2
    tool_timeout_sec: float | None = 30.0
    tool_router_strategy: Literal["rule_based", "embedding", "llm"] = "rule_based"

    # MCP tools (Phase 9B)
    mcp_enabled: bool = False
    mcp_required: bool = False
    mcp_server_command: str = "python"
    mcp_server_args: list[str] = Field(
        default_factory=lambda: ["mcp_servers/trip_tools_server.py"],
    )
    mcp_tool_prefix: str = "mcp_"

    # Tool routing policy (Phase 9C)
    tool_policy_enabled: bool = True
    tool_policy_strategy: Literal[
        "planner_hint_first",
        "builtin_first",
        "mcp_first",
        "deterministic",
        "cost_aware",
        "reliability_aware",
    ] = "planner_hint_first"
    tool_policy_mcp_fallback_enabled: bool = True
    tool_policy_trace_enabled: bool = True
    tool_policy_default_provider: Literal["builtin", "mcp"] = "builtin"
    tool_policy_reliability_stats_path: str = "./data/eval/tool_routing/tool_reliability_stats.json"
    tool_policy_success_weight: float = 0.7
    tool_policy_latency_weight: float = 0.2
    tool_policy_fallback_weight: float = 0.1

    @field_validator("mcp_server_args", mode="before")
    @classmethod
    def _parse_mcp_server_args(cls, value: object) -> list[str]:
        if isinstance(value, str):
            parts = [part.strip() for part in value.split() if part.strip()]
            return parts or ["mcp_servers/trip_tools_server.py"]
        return value  # type: ignore[return-value]

    # Planner
    planner_max_retries: int = 2
    plan_failure_policy: Literal["retry", "skip", "replan"] = "retry"
    plan_step_max_retries: int = 2
    plan_max_replan_attempts: int = 1

    # Plan context compression
    plan_context_compression_enabled: bool = True
    plan_context_max_chars: int = 2000

    # Execution critic
    plan_execution_critic_enabled: bool = True
    plan_critic_replan_enabled: bool = True
    plan_critic_max_replan_attempts: int = 2

    # Graph runtime (Phase 4)
    graph_runtime_enabled: bool = True
    graph_max_iterations: int = 50

    # Persistence (Phase 5)
    persistence_enabled: bool = False
    persistence_db_path: str = "./data/persistence/executions.db"

    # Observability (Phase 6)
    metrics_enabled: bool = False
    log_json: bool = False
    enable_json_log: bool = False
    metrics_prompt_usd_per_1k: float = 0.005
    metrics_completion_usd_per_1k: float = 0.015

    # Evaluation (Phase 7)
    eval_enabled: bool = True
    eval_mode: Literal["deterministic_eval", "real_llm_eval", "auto"] = "deterministic_eval"
    eval_store_path: str = "./data/eval"
    eval_default_seed: int = 42
    eval_regression_threshold: float = -0.05
    eval_score_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "tool_accuracy": 0.30,
            "plan_quality": 0.25,
            "execution_success": 0.30,
            "cost_efficiency": 0.15,
        },
    )

    def resolve_tool_policy_strategy(self) -> str:
        """Effective tool policy strategy (deterministic_eval → builtin-first)."""
        if self.eval_mode == "deterministic_eval":
            if self.tool_policy_strategy in ("mcp_first", "cost_aware", "reliability_aware"):
                return "builtin_first"
            if self.tool_policy_strategy == "deterministic":
                return "builtin_first"
        if not self.mcp_enabled and self.tool_policy_strategy == "mcp_first":
            return "builtin_first"
        return self.tool_policy_strategy

    def resolve_qwen_model(self, caller: str | None = None) -> str:
        """Return the Qwen model name for a logical caller role."""
        mapping = {
            "planner": self.qwen_planner_model,
            "critic": self.qwen_critic_model,
            "replanner": self.qwen_replanner_model,
            "summarizer": self.qwen_summarizer_model,
            "router": self.qwen_router_model,
        }
        if caller and caller in mapping:
            return mapping[caller]
        return self.qwen_model


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton for dependency injection."""
    return Settings()
