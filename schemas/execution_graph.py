"""Structured execution graph model for trace, replay, and visualization."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class GraphEdgeRecord(BaseModel):
    source: str
    target: str
    label: str | None = None
    kind: str | None = None
    sequence: int = 0


class NodeExecutionRecord(BaseModel):
    node_id: str
    sequence: int
    input_state_hash: str
    output_state_hash: str
    state_delta: dict[str, Any] = Field(default_factory=dict)
    input_state_snapshot: dict[str, Any] | None = None
    output_state_snapshot: dict[str, Any] | None = None
    replayed: bool = False
    status: str = "completed"


class ExecutionGraphModel(BaseModel):
    """Structured DAG of graph node executions."""

    graph_id: str
    session_id: str
    seed: int | None = None
    mode: str = "normal"
    node_records: list[NodeExecutionRecord] = Field(default_factory=list)
    edge_records: list[GraphEdgeRecord] = Field(default_factory=list)

    def add_node_record(self, record: NodeExecutionRecord) -> None:
        self.node_records.append(record)

    def add_edge_record(self, edge: GraphEdgeRecord) -> None:
        self.edge_records.append(edge)

    def to_dag_json(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "session_id": self.session_id,
            "seed": self.seed,
            "mode": self.mode,
            "nodes": [record.model_dump() for record in self.node_records],
            "edges": [edge.model_dump() for edge in self.edge_records],
        }

    def export_json(self, *, indent: int = 2) -> str:
        import json

        return json.dumps(self.to_dag_json(), ensure_ascii=False, indent=indent)

    def to_mermaid(self) -> str:
        lines = ["graph TD"]
        for edge in self.edge_records:
            label = f"|{edge.label}|" if edge.label else ""
            lines.append(f"  {self._mermaid_id(edge.source)}{label}--> {self._mermaid_id(edge.target)}")
        for record in self.node_records:
            node = self._mermaid_id(record.node_id)
            lines.append(
                f"  {node}[\"{record.node_id}\\n{record.input_state_hash[:8]}→"
                f"{record.output_state_hash[:8]}\"]",
            )
        return "\n".join(lines)

    def to_graphviz(self) -> str:
        lines = [
            "digraph ExecutionGraph {",
            '  rankdir=LR;',
            '  node [shape=box];',
        ]
        for record in self.node_records:
            label = (
                f"{record.node_id}\\n"
                f"in:{record.input_state_hash[:8]}\\n"
                f"out:{record.output_state_hash[:8]}"
            )
            lines.append(f'  "{record.node_id}" [label="{label}"];')
        for edge in self.edge_records:
            attrs = f' [label="{edge.label}"]' if edge.label else ""
            lines.append(f'  "{edge.source}" -> "{edge.target}"{attrs};')
        lines.append("}")
        return "\n".join(lines)

    def node_ids(self) -> list[str]:
        return [record.node_id for record in self.node_records]

    @staticmethod
    def _mermaid_id(node_id: str) -> str:
        return node_id.replace("-", "_").replace(" ", "_")

    @classmethod
    def from_dag_json(cls, payload: dict[str, Any]) -> ExecutionGraphModel:
        return cls(
            graph_id=payload["graph_id"],
            session_id=payload.get("session_id", "default"),
            seed=payload.get("seed"),
            mode=payload.get("mode", "normal"),
            node_records=[NodeExecutionRecord.model_validate(item) for item in payload.get("nodes", [])],
            edge_records=[GraphEdgeRecord.model_validate(item) for item in payload.get("edges", [])],
        )
