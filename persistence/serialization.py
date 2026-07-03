"""JSON helpers for persistence."""

from __future__ import annotations

import json
from typing import Any


def dumps_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def loads_json(raw: str | None) -> Any:
    if raw is None:
        return None
    return json.loads(raw)
