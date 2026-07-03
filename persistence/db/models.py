"""Persistence domain models and SQL schema."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ExecutionStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class NodeStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class GraphExecutionRecord(BaseModel):
    execution_id: str
    session_id: str
    query: str
    start_time: datetime
    end_time: datetime | None = None
    status: ExecutionStatus = ExecutionStatus.RUNNING
    graph_id: str | None = None
    final_result: str | None = None
    execution_graph_json: dict[str, Any] | None = None
    error_message: str | None = None


class NodeExecutionRecord(BaseModel):
    id: int | None = None
    execution_id: str
    node_id: str
    sequence: int = 0
    input_state: dict[str, Any] | None = None
    output_state: dict[str, Any] | None = None
    input_state_hash: str | None = None
    output_state_hash: str | None = None
    latency_ms: float | None = None
    status: NodeStatus = NodeStatus.COMPLETED
    parallel: bool = False


class ToolCallRecord(BaseModel):
    id: int | None = None
    execution_id: str | None = None
    session_id: str | None = None
    call_id: str
    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    result: Any = None
    success: bool = True
    latency_ms: float = 0.0
    error: str | None = None


class PersistedStateVersion(BaseModel):
    version_id: str
    execution_id: str
    node_id: str | None = None
    state_snapshot: dict[str, Any] = Field(default_factory=dict)
    parent_version_id: str | None = None
    state_hash: str
    branch_id: str = "main"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SessionRecord(BaseModel):
    session_id: str
    history: list[str] = Field(default_factory=list)
    last_execution_id: str | None = None
    last_state_snapshot: dict[str, Any] | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS graph_executions (
    execution_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    query TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT,
    status TEXT NOT NULL,
    graph_id TEXT,
    final_result TEXT,
    execution_graph_json TEXT,
    error_message TEXT
);
CREATE INDEX IF NOT EXISTS idx_graph_executions_session ON graph_executions(session_id);

CREATE TABLE IF NOT EXISTS node_executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    sequence INTEGER NOT NULL DEFAULT 0,
    input_state_json TEXT,
    output_state_json TEXT,
    input_state_hash TEXT,
    output_state_hash TEXT,
    latency_ms REAL,
    status TEXT NOT NULL,
    parallel INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (execution_id) REFERENCES graph_executions(execution_id)
);
CREATE INDEX IF NOT EXISTS idx_node_executions_execution ON node_executions(execution_id);

CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id TEXT,
    session_id TEXT,
    call_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    args_json TEXT NOT NULL,
    result_json TEXT,
    success INTEGER NOT NULL,
    latency_ms REAL NOT NULL,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_tool_calls_execution ON tool_calls(execution_id);

CREATE TABLE IF NOT EXISTS state_versions (
    version_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL,
    node_id TEXT,
    state_snapshot_json TEXT NOT NULL,
    parent_version_id TEXT,
    state_hash TEXT NOT NULL,
    branch_id TEXT NOT NULL DEFAULT 'main',
    created_at TEXT NOT NULL,
    FOREIGN KEY (execution_id) REFERENCES graph_executions(execution_id)
);
CREATE INDEX IF NOT EXISTS idx_state_versions_execution ON state_versions(execution_id);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    history_json TEXT NOT NULL DEFAULT '[]',
    last_execution_id TEXT,
    last_state_snapshot_json TEXT,
    updated_at TEXT NOT NULL
);
"""
