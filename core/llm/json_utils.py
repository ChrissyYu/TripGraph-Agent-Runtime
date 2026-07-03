"""JSON extraction helpers for LLM responses."""

from __future__ import annotations

import json
import re


def extract_json_text(raw: str) -> str:
    """Return parseable JSON text from raw LLM output.

    Supports plain JSON objects/arrays and ```json fenced blocks.
    """
    text = raw.strip()
    if not text:
        raise ValueError("empty LLM response")

    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, flags=re.IGNORECASE)
    if fence_match:
        text = fence_match.group(1).strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\n?", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\n?```$", "", text).strip()

    # If extra prose wraps JSON, take the outermost object/array.
    if not text.startswith("{") and not text.startswith("["):
        obj_start = text.find("{")
        arr_start = text.find("[")
        starts = [idx for idx in (obj_start, arr_start) if idx >= 0]
        if starts:
            start = min(starts)
            end = _find_json_end(text, start)
            if end > start:
                text = text[start:end]

    json.loads(text)  # validate
    return text


def _find_json_end(text: str, start: int) -> int:
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return index + 1
    return len(text)
