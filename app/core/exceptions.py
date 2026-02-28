"""
Mission Control — Custom Exceptions
=====================================
All exceptions raised by the execution engine.

Design rule: classify before retry.
  - ContextEscalationRequired  → do NOT retry; escalate context tier
  - MaxRetriesExceeded         → do NOT retry; log codex candidate
  - FatalError                 → do NOT retry; surface to user immediately
  - RetryableError             → safe to retry with backoff
"""


class MissionControlError(Exception):
    """Base class for all Mission Control exceptions."""


# ---------------------------------------------------------------------------
# Execution flow signals
# ---------------------------------------------------------------------------

class ContextEscalationRequired(MissionControlError):
    """
    Raised when the current context tier is insufficient.
    The execution loop catches this and escalates to the next tier
    rather than retrying at the same tier.
    """
    def __init__(self, original_exc: Exception, current_tier: str = "unknown"):
        self.original_exc = original_exc
        self.current_tier = current_tier
        super().__init__(
            f"Context window exceeded at tier '{current_tier}'. "
            f"Escalation required. Original: {original_exc}"
        )


class MaxRetriesExceeded(MissionControlError):
    """
    Raised when the retry limit is hit for a retryable error.
    The execution loop logs a codex candidate and marks the task failed.
    """
    def __init__(self, retry_count: int, original_exc: Exception):
        self.retry_count = retry_count
        self.original_exc = original_exc
        super().__init__(
            f"Max retries ({retry_count}) exceeded. "
            f"Last error: {type(original_exc).__name__}: {original_exc}"
        )


class MaxLoopsExceeded(MissionControlError):
    """Raised when MAX_EXECUTION_LOOPS is hit (hard loop limit)."""
    def __init__(self, loop_count: int):
        self.loop_count = loop_count
        super().__init__(f"Hard loop limit hit after {loop_count} iterations.")


class MaxReplansExceeded(MissionControlError):
    """Raised when MAX_REPLAN_CYCLES is hit."""
    def __init__(self, replan_count: int):
        self.replan_count = replan_count
        super().__init__(f"Max replan cycles ({replan_count}) exceeded.")


class FatalError(MissionControlError):
    """
    Non-retryable, non-escalatable error.
    Examples: auth failure, insufficient API credits, corrupt task definition.
    """
    def __init__(self, message: str, original_exc: Exception | None = None):
        self.original_exc = original_exc
        super().__init__(message)


# ---------------------------------------------------------------------------
# Provider / model errors
# ---------------------------------------------------------------------------

class ModelUnavailableError(MissionControlError):
    """The requested model or provider is unreachable."""
    def __init__(self, model_id: str, reason: str = ""):
        self.model_id = model_id
        super().__init__(f"Model '{model_id}' unavailable. {reason}".strip())


class StructuredOutputError(MissionControlError):
    """
    Instructor failed to extract a valid structured response after max_retries.
    The LLM response did not conform to the Pydantic schema.
    """


# ---------------------------------------------------------------------------
# Codex / validation errors
# ---------------------------------------------------------------------------

class CodexError(MissionControlError):
    """Base for Codex-related failures."""


class ValidationError(MissionControlError):
    """Deterministic validator (compile/test/lint) returned unexpected output."""
