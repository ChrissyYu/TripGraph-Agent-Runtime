#!/usr/bin/env python3
"""One-click application entrypoint."""

from __future__ import annotations

import uvicorn

from config.env_loader import bootstrap_environment
from config.settings import get_settings


def main() -> None:
    bootstrap_environment()
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        workers=settings.workers if not settings.reload else 1,
        log_level="debug" if settings.debug else "info",
    )


if __name__ == "__main__":
    main()
