"""
Mission Control — Structured Logger
=====================================
Subsystem-prefixed JSON logging.
Pattern from: kb-execution-validation-telemetry.md → OpenClaw pattern

Usage:
    from app.core.logging import get_logger
    log = get_logger("router")
    log.info("Model selected", model="reasoning_model", task_type="refactor_large")

Output:
    {"timestamp": "...", "level": "INFO", "subsystem": "mc.router",
     "message": "Model selected", "model": "reasoning_model", ...}
"""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any


class StructuredLogger:
    """
    Emits JSON log lines with a subsystem prefix.
    Each subsystem (router, codex, validator, telemetry, executor, ...) gets
    its own logger so log lines can be filtered by subsystem in any log
    aggregator.
    """

    def __init__(self, subsystem: str) -> None:
        self.subsystem = f"mc.{subsystem}"
        self._logger = logging.getLogger(self.subsystem)

    def _emit(self, level: str, message: str, **kwargs: Any) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "subsystem": self.subsystem,
            "message": message,
            **kwargs,
        }
        line = json.dumps(entry, default=str)

        if level == "DEBUG":
            self._logger.debug(line)
        elif level == "INFO":
            self._logger.info(line)
        elif level == "WARNING":
            self._logger.warning(line)
        elif level == "ERROR":
            self._logger.error(line)
        elif level == "CRITICAL":
            self._logger.critical(line)

    def debug(self, message: str, **kwargs: Any) -> None:
        self._emit("DEBUG", message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        self._emit("INFO", message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        self._emit("WARNING", message, **kwargs)

    def error(self, message: str, exc: Exception | None = None, **kwargs: Any) -> None:
        if exc is not None:
            kwargs["error"] = str(exc)
            kwargs["error_type"] = type(exc).__name__
        self._emit("ERROR", message, **kwargs)

    def critical(self, message: str, exc: Exception | None = None, **kwargs: Any) -> None:
        if exc is not None:
            kwargs["error"] = str(exc)
            kwargs["error_type"] = type(exc).__name__
        self._emit("CRITICAL", message, **kwargs)


def get_logger(subsystem: str) -> StructuredLogger:
    """Return a StructuredLogger for the given subsystem name."""
    return StructuredLogger(subsystem)


def configure_logging(level: str = "INFO") -> None:
    """
    Configure root logging for Mission Control.
    Call once at application startup (FastAPI lifespan or CLI entry).
    """
    numeric = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        stream=sys.stdout,
        level=numeric,
        format="%(message)s",   # JSON lines; no extra wrapper needed
    )
    # Silence noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("litellm").setLevel(logging.WARNING)
    logging.getLogger("instructor").setLevel(logging.WARNING)
