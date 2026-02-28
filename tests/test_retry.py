"""
Tests for retry logic and exception classification.

Pattern from: kb-execution-validation-telemetry.md → Aider pattern
Rules:
  - context_window_exceeded → ContextEscalationRequired (no retry)
  - insufficient_funds      → FatalError (no retry)
  - non-retryable           → re-raise immediately
  - retryable               → backoff up to max_retries → MaxRetriesExceeded
"""

import pytest

from app.core.exceptions import ContextEscalationRequired, FatalError, MaxRetriesExceeded
from app.core.retry import (
    EXCEPTION_REGISTRY,
    classify_exception,
    execute_with_retry,
    ExceptionInfo,
)


# ---------------------------------------------------------------------------
# Fake exception classes to simulate LiteLLM / provider exceptions
# ---------------------------------------------------------------------------

class FakeAPIConnectionError(Exception): pass
class FakeAPITimeoutError(Exception): pass
class FakeRateLimitError(Exception): pass
class FakeAuthenticationError(Exception): pass
class FakeContextWindowExceededError(Exception): pass
class FakeInsufficientCreditsError(Exception): pass
class FakeBadRequestError(Exception): pass


# ---------------------------------------------------------------------------
# classify_exception — name matching
# ---------------------------------------------------------------------------

def test_classify_api_connection_error():
    info = classify_exception(FakeAPIConnectionError("connection refused"))
    assert info.retryable is True
    assert info.context_window_exceeded is False


def test_classify_rate_limit_error():
    info = classify_exception(FakeRateLimitError("429"))
    assert info.retryable is True


def test_classify_auth_error():
    info = classify_exception(FakeAuthenticationError("invalid key"))
    assert info.retryable is False
    assert info.insufficient_funds is False


def test_classify_bad_request():
    info = classify_exception(FakeBadRequestError("bad request"))
    assert info.retryable is False


def test_classify_context_window():
    info = classify_exception(FakeContextWindowExceededError("too long"))
    assert info.context_window_exceeded is True
    assert info.retryable is False


def test_classify_insufficient_credits():
    info = classify_exception(FakeInsufficientCreditsError("no funds"))
    assert info.insufficient_funds is True
    assert info.retryable is False


# ---------------------------------------------------------------------------
# classify_exception — message-based heuristics
# ---------------------------------------------------------------------------

def test_heuristic_context_window_message():
    exc = Exception("the context window length is exceeded")
    info = classify_exception(exc)
    assert info.context_window_exceeded is True


def test_heuristic_context_too_long():
    # Heuristic requires "context" AND ("too long" | "window" | "length")
    exc = Exception("context is too long for this model")
    info = classify_exception(exc)
    assert info.context_window_exceeded is True


def test_heuristic_rate_limit_message():
    exc = Exception("rate limit exceeded, please slow down")
    info = classify_exception(exc)
    assert info.retryable is True


def test_heuristic_timeout_message():
    exc = Exception("read timeout after 60 seconds")
    info = classify_exception(exc)
    assert info.retryable is True


def test_heuristic_insufficient_credits():
    exc = Exception("you have insufficient quota remaining")
    info = classify_exception(exc)
    assert info.insufficient_funds is True


def test_unknown_exception_defaults_retryable():
    exc = Exception("something completely unexpected happened")
    info = classify_exception(exc)
    assert info.retryable is True


# ---------------------------------------------------------------------------
# execute_with_retry — success path
# ---------------------------------------------------------------------------

def test_execute_with_retry_success():
    """Succeeds on first call — no retries needed."""
    calls = []

    def fn():
        calls.append(1)
        return "ok"

    result = execute_with_retry(fn, max_retries=3)
    assert result == "ok"
    assert len(calls) == 1


def test_execute_with_retry_succeeds_after_retry():
    """Fails once with a retryable error, then succeeds."""
    calls = []

    def fn():
        calls.append(1)
        if len(calls) < 2:
            raise FakeRateLimitError("rate limited")
        return "ok"

    result = execute_with_retry(fn, max_retries=3)
    assert result == "ok"
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# execute_with_retry — context escalation
# ---------------------------------------------------------------------------

def test_execute_with_retry_context_window_raises_immediately():
    """ContextWindowExceededError must raise ContextEscalationRequired, not retry."""
    calls = []

    def fn():
        calls.append(1)
        raise FakeContextWindowExceededError("context too long")

    with pytest.raises(ContextEscalationRequired):
        execute_with_retry(fn, max_retries=5)

    # Must not retry — should be called exactly once
    assert len(calls) == 1


def test_execute_with_retry_context_window_message():
    """Message-based detection also triggers escalation without retry."""
    calls = []

    def fn():
        calls.append(1)
        raise Exception("prompt is too long for the context window")

    with pytest.raises(ContextEscalationRequired):
        execute_with_retry(fn, max_retries=5)

    assert len(calls) == 1


# ---------------------------------------------------------------------------
# execute_with_retry — fatal errors
# ---------------------------------------------------------------------------

def test_execute_with_retry_insufficient_funds_is_fatal():
    """InsufficientCreditsError must raise FatalError immediately."""
    calls = []

    def fn():
        calls.append(1)
        raise FakeInsufficientCreditsError("no credits")

    with pytest.raises(FatalError):
        execute_with_retry(fn, max_retries=5)

    assert len(calls) == 1


def test_execute_with_retry_auth_error_reraises():
    """Non-retryable errors other than special cases are re-raised as-is."""
    def fn():
        raise FakeAuthenticationError("invalid API key")

    with pytest.raises(FakeAuthenticationError):
        execute_with_retry(fn, max_retries=5)


# ---------------------------------------------------------------------------
# execute_with_retry — max retries exceeded
# ---------------------------------------------------------------------------

def test_execute_with_retry_exceeds_max():
    """Retryable errors that persist past max_retries raise MaxRetriesExceeded."""
    calls = []

    def fn():
        calls.append(1)
        raise FakeRateLimitError("always rate limited")

    with pytest.raises(MaxRetriesExceeded) as exc_info:
        execute_with_retry(fn, max_retries=2)

    assert exc_info.value.retry_count == 2
    # Called: initial + 2 retries = 3 total
    assert len(calls) == 3


def test_execute_with_retry_zero_retries():
    """max_retries=0 → no retries at all, raises MaxRetriesExceeded after first fail."""
    calls = []

    def fn():
        calls.append(1)
        raise FakeRateLimitError("rate limited")

    with pytest.raises(MaxRetriesExceeded):
        execute_with_retry(fn, max_retries=0)

    assert len(calls) == 1


# ---------------------------------------------------------------------------
# Exception registry completeness
# ---------------------------------------------------------------------------

def test_registry_has_all_expected_types():
    names = {info.exception_name for info in EXCEPTION_REGISTRY}
    assert "APIConnectionError" in names
    assert "RateLimitError" in names
    assert "AuthenticationError" in names
    assert "ContextWindowExceededError" in names
    assert "InsufficientCreditsError" in names
