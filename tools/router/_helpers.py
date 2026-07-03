"""Shared helpers for tool selection strategies."""

from __future__ import annotations

import math
import re
from collections import Counter

from schemas.tool import ToolDefinition
from schemas.tool_router import ToolAlternative
from tools.registry import ToolRegistry


def rank_to_result(
    task: str,
    ranked: list[tuple[str, float]],
    *,
    strategy: str,
) -> dict:
    from schemas.tool_router import ToolRouterStrategy

    if not ranked:
        return {
            "task": task,
            "best_tool": None,
            "confidence": 0.0,
            "alternatives": [],
            "strategy": ToolRouterStrategy(strategy),
        }

    best_tool, best_score = ranked[0]
    alternatives = [
        ToolAlternative(tool=tool, confidence=round(score, 4))
        for tool, score in ranked[1:]
        if score > 0
    ]
    return {
        "task": task,
        "best_tool": best_tool,
        "confidence": round(best_score, 4),
        "alternatives": alternatives,
        "strategy": ToolRouterStrategy(strategy),
    }


def tool_catalog(registry: ToolRegistry) -> list[ToolDefinition]:
    return sorted(registry.get_definitions(), key=lambda item: item.name)


def tool_text(defn: ToolDefinition) -> str:
    return f"{defn.name} {defn.description}"


def tokenize(text: str) -> list[str]:
    lowered = text.lower()
    return re.findall(r"[\u4e00-\u9fff]|[a-z0-9]+", lowered)


def cosine_similarity(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    if not vec_a or not vec_b:
        return 0.0
    common = set(vec_a) & set(vec_b)
    dot = sum(vec_a[token] * vec_b[token] for token in common)
    norm_a = math.sqrt(sum(value * value for value in vec_a.values()))
    norm_b = math.sqrt(sum(value * value for value in vec_b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def tfidf_vector(text: str, idf: dict[str, float]) -> dict[str, float]:
    counts = Counter(tokenize(text))
    total = sum(counts.values()) or 1
    return {token: (count / total) * idf.get(token, 0.0) for token, count in counts.items()}


def build_idf(documents: list[str]) -> dict[str, float]:
    doc_count = len(documents) or 1
    df: Counter[str] = Counter()
    for document in documents:
        for token in set(tokenize(document)):
            df[token] += 1
    return {token: math.log((doc_count + 1) / (freq + 1)) + 1.0 for token, freq in df.items()}
