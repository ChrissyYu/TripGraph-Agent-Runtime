"""Structured logging configuration."""

from __future__ import annotations

import logging
import sys
from typing import Literal

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def setup_logging(level: LogLevel = "INFO", *, json_format: bool = False) -> None:
    """Configure root logger with plain text or structured JSON output."""
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(getattr(logging, level))

    handler = logging.StreamHandler(sys.stdout)
    if json_format:
        from observability.logging.json_logger import JsonLogFormatter
        from observability.logging.structured import OBSERVABILITY_LOGGER

        handler.setFormatter(JsonLogFormatter())
        logging.getLogger(OBSERVABILITY_LOGGER).setLevel(getattr(logging, level))
    else:
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            ),
        )
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Return a module-scoped logger."""
    return logging.getLogger(name)
