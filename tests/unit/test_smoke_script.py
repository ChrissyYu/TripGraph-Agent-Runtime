"""Smoke script safety checks."""

from __future__ import annotations

from pathlib import Path


def test_qwen_smoke_script_does_not_print_api_key() -> None:
    source = Path("scripts/smoke_qwen_llm.py").read_text(encoding="utf-8")

    assert "_redact_secrets" in source
    assert "_redact_secrets(str(exc)" in source or "_redact_secrets(response.final_result" in source
    assert 'print(f"  Message: {_redact_secrets' in source
