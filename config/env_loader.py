"""Environment loading helpers for deployment."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


def load_env(*, env_file: str | None = None, override: bool = False) -> Path | None:
    """Load `.env` from project root or explicit path."""
    if env_file:
        path = Path(env_file)
        if path.exists():
            load_dotenv(path, override=override)
            return path
        return None

    candidates = [
        Path(os.getenv("ENV_FILE", "")),
        Path(".env"),
        Path("/app/.env"),
    ]
    for candidate in candidates:
        if str(candidate) and candidate.exists():
            load_dotenv(candidate, override=override)
            return candidate
    return None


def bootstrap_environment(*, env_file: str | None = None, override: bool = False) -> None:
    """Load env files and reset cached settings."""
    load_env(env_file=env_file, override=override)
    from config.settings import get_settings

    get_settings.cache_clear()
