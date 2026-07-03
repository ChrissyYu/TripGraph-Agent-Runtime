"""Embedding-style tool selection via TF-IDF cosine similarity."""

from __future__ import annotations

from tools.registry import ToolRegistry
from tools.router._helpers import (
    build_idf,
    cosine_similarity,
    rank_to_result,
    tfidf_vector,
    tool_catalog,
    tool_text,
)


class EmbeddingToolSelector:
    """Rank tools by TF-IDF cosine similarity between task and tool descriptions."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry
        definitions = tool_catalog(registry)
        documents = [tool_text(defn) for defn in definitions]
        self._tool_names = [defn.name for defn in definitions]
        self._idf = build_idf(documents + ["travel planning task"])
        self._tool_vectors = [tfidf_vector(document, self._idf) for document in documents]

    def select(self, task: str) -> dict:
        task_vector = tfidf_vector(task, self._idf)
        ranked: list[tuple[str, float]] = []
        for tool_name, tool_vector in zip(self._tool_names, self._tool_vectors, strict=True):
            score = cosine_similarity(task_vector, tool_vector)
            if score > 0:
                ranked.append((tool_name, min(1.0, score)))

        ranked.sort(key=lambda item: item[1], reverse=True)
        if ranked:
            top_score = ranked[0][1]
            if top_score < 0.05:
                ranked = []
            else:
                ranked = [(tool, score / top_score if top_score else score) for tool, score in ranked]

        return rank_to_result(task, ranked, strategy="embedding")
