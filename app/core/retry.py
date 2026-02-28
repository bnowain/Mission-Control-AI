"""
Mission Control — Exception Classification + Exponential Backoff
=================================================================
Pattern from: kb-execution-validation-telemetry.md → Aider pattern

Rule: classify BEFORE retry.
  - context_window_exceeded → raise ContextEscalationRequired (do NOT retry)
  - insufficient_funds      → raise FatalError
  - not retryable           → re-raise immediately
  - retryable               → backoff and retry up to max_retries

Backoff parameters (from architecture-decisions.md):
  start=125ms, multiplier=2x, cap=60s, max_retries=5 (configurable)
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Optional, TypeVar

from app.core.exceptions import (
    ContextEscalationRequired,
    FatalError,
    MaxRetriesExceeded,
)
from app.core.logging import get_logger

log = get_logger("retry")

# ---------------------------------------------------------------------------
# Backoff constants
# ---------------------------------------------------------------------------

RETRY_START_DELAY: float = 0.125    # 125 ms
RETRY_MAX_DELAY:   float = 60.0     # 60 seconds cap
DEFAULT_MAX_RETRIES: int = 5

# ---------------------------------------------------------------------------
# Exception classification registry (Aider pattern)
# ---------------------------------------------------------------------------

@dataclass
class ExceptionInfo:
    exception_name: str
    retryable: bool
    context_window_exceeded: bool = False
    insufficient_funds: bool = False


EXCEPTION_REGISTRY: list[ExceptionInfo] = [
    # Retryable — transient provider issues
    ExceptionInfo("APIConnectionError",          retryable=True),
    ExceptionInfo("APITimeoutError",             retryable=True),
    ExceptionInfo("RateLimitError",              retryable=True),
    ExceptionInfo("InternalServerError",         retryable=True),
    ExceptionInfo("ServiceUnavailableError",     retryable=True),
    ExceptionInfo("Timeout",                     retryable=True),
    ExceptionInfo("ConnectionError",             retryable=True),

    # Non-retryable — configuration or auth problems
    ExceptionInfo("AuthenticationError",         retryable=False),
    ExceptionInfo("PermissionDeniedError",       retryable=False),
    ExceptionInfo("NotFoundError",               retryable=False),
    ExceptionInfo("BadRequestError",             retryable=False),

    # Special cases — handled outside normal retry loop
    ExceptionInfo(
        "ContextWindowExceededError",
        retryable=False,
        context_window_exceeded=True,
    ),
    ExceptionInfo(
        "InsufficientCreditsError",
        retryable=False,
        insufficient_funds=True,
    ),
]

_REGISTRY_MAP: dict[str, ExceptionInfo] = {
    info.exception_name: info for info in EXCEPTION_REGISTRY
}


def classify_exception(exc: Exception) -> ExceptionInfo:
    """
    Classify an exception using the registry.
    Falls back to retryable=True for unknowns (try once more, then give up).
    """
    exc_name = type(exc).__name__
    exc_msg  = str(exc).lower()

    # Direct name match
    if exc_name in _REGISTRY_MAP:
        return _REGISTRY_MAP[exc_name]

    # Substring match (handles subclasses and provider-wrapped names)
    for name, info in _REGISTRY_MAP.items():
        if name.lower() in exc_name.lower():
            return info

    # Message-based heuristics for providers that don't name exceptions well
    if "context" in exc_msg and ("window" in exc_msg or "length" in exc_msg or "too long" in exc_msg):
        return ExceptionInfo("ContextWindowExceededError", retryable=False, context_window_exceeded=True)
    if "insufficient" in exc_msg and ("credit" in exc_msg or "quota" in exc_msg or "fund" in exc_msg):
        return ExceptionInfo("InsufficientCreditsError", retryable=False, insufficient_funds=True)
    if "rate limit" in exc_msg or "too many requests" in exc_msg:
        return _REGISTRY_MAP["RateLimitError"]
    if "timeout" in exc_msg:
        return _REGISTRY_MAP["Timeout"]

    # Default: treat unknown as retryable (try once more)
    log.warning("Unknown exception type — defaulting to retryable", exc_type=exc_name)
    return ExceptionInfo("UnknownError", retryable=True)


# ---------------------------------------------------------------------------
# Retry executor
# ---------------------------------------------------------------------------

T = TypeVar("T")


def execute_with_retry(
    fn: Callable[[], T],
    max_retries: int = DEFAULT_MAX_RETRIES,
    task_id: Optional[str] = None,
    current_tier: str = "execution",
) -> T:
    """
    Execute fn() with exponential backoff and exception classification.

    Raises:
        ContextEscalationRequired  if context window is exceeded
        FatalError                 if insufficient credits or auth failure
        MaxRetriesExceeded         if retryable error persists past max_retries
        Exception                  (re-raised) if non-retryable and non-special
    """
    retry_delay = RETRY_START_DELAY
    retries = 0

    while True:
        try:
            return fn()

        except Exception as exc:
            info = classify_exception(exc)

            if info.context_window_exceeded:
                log.info(
                    "Context window exceeded — escalation required",
                    task_id=task_id,
                    tier=current_tier,
                    exc_type=type(exc).__name__,
                )
                raise ContextEscalationRequired(exc, current_tier=current_tier)

            if info.insufficient_funds:
                log.critical("Insufficient API credits — fatal", task_id=task_id)
                raise FatalError("Insufficient API credits.", exc)

            if not info.retryable:
                log.error(
                    "Non-retryable exception — aborting",
                    task_id=task_id,
                    exc_type=type(exc).__name__,
                    exc=exc,
                )
                raise

            if retries >= max_retries:
                log.error(
                    "Max retries exceeded",
                    task_id=task_id,
                    retries=retries,
                    exc_type=type(exc).__name__,
                )
                raise MaxRetriesExceeded(retries, exc)

            log.warning(
                "Retryable error — backing off",
                task_id=task_id,
                attempt=retries + 1,
                max_retries=max_retries,
                delay_s=round(retry_delay, 3),
                exc_type=type(exc).__name__,
            )

            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, RETRY_MAX_DELAY)
            retries += 1


async def execute_with_retry_async(
    fn: Callable[[], Any],
    max_retries: int = DEFAULT_MAX_RETRIES,
    task_id: Optional[str] = None,
    current_tier: str = "execution",
) -> Any:
    """
    Async version of execute_with_retry. fn must be a coroutine factory
    (a callable that returns a coroutine when called).
    """
    import asyncio

    retry_delay = RETRY_START_DELAY
    retries = 0

    while True:
        try:
            return await fn()

        except Exception as exc:
            info = classify_exception(exc)

            if info.context_window_exceeded:
                raise ContextEscalationRequired(exc, current_tier=current_tier)

            if info.insufficient_funds:
                raise FatalError("Insufficient API credits.", exc)

            if not info.retryable:
                raise

            if retries >= max_retries:
                raise MaxRetriesExceeded(retries, exc)

            log.warning(
                "Retryable error (async) — backing off",
                task_id=task_id,
                attempt=retries + 1,
                delay_s=round(retry_delay, 3),
                exc_type=type(exc).__name__,
            )

            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, RETRY_MAX_DELAY)
            retries += 1
