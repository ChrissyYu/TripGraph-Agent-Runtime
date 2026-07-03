"""Domain-specific exceptions."""


class AgentError(Exception):
    """Base exception for agent-related failures."""


class ToolExecutionError(AgentError):
    """Raised when a tool call fails during execution."""


class ToolTimeoutError(ToolExecutionError):
    """Raised when a tool call exceeds its timeout."""


class WorkflowError(AgentError):
    """Raised when the LangGraph workflow encounters an unrecoverable error."""


class MemoryError(AgentError):
    """Raised when memory read/write operations fail."""


class StreamingError(AgentError):
    """Raised when SSE streaming fails."""


class AgentLoopError(AgentError):
    """Raised when the agent tool-calling loop fails or exceeds limits."""


class PlanValidationError(AgentError):
    """Raised when a generated plan fails validation."""

    def __init__(self, message: str, *, errors: list[str] | None = None) -> None:
        self.errors: list[str] = errors or []
        super().__init__(message)


class LLMClientError(AgentError):
    """Raised when an LLM provider call fails after retries."""
