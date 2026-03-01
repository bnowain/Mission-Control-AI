"""
Mission Control — Model Executor
=====================================
Ties together AdaptiveRouter + execute_with_retry + context escalation
into the single entry point used by the execution loop.

Pattern from: kb-orchestration-frameworks.md → LangGraph / CrewAI pattern
Architecture: kb-execution-validation-telemetry.md → Aider retry + escalation

Responsibilities:
  - Call router.select() with task_type + retry_count
  - Run router.complete() inside execute_with_retry()
  - Catch ContextEscalationRequired → escalate context tier → re-select
  - Extract tokens/timing from LiteLLM response
  - Return ExecutionResult (ready for grading + telemetry)

Hard limits enforced here:
  MAX_CONTEXT_ESCALATIONS = 3  (Execution → Hybrid → Planning → raise)
"""

from __future__ import annotations

import re
import time
from typing import Optional

from app.core.exceptions import ContextEscalationRequired, FatalError
from app.core.logging import get_logger
from app.core.retry import DEFAULT_MAX_RETRIES, execute_with_retry, execute_with_retry_async
from app.models.schemas import (
    CapabilityClass,
    ContextTier,
    ExecutionResult,
    TaskType,
)
from app.router.adaptive import AdaptiveRouter, get_router

log = get_logger("executor")

# Maximum number of context tier escalations per execution attempt.
# Execution (16k) → Hybrid (24k) → Planning (32k) → raise FatalError
MAX_CONTEXT_ESCALATIONS: int = 3

# Escalation path: tier value → next tier
_TIER_NEXT: dict[str, ContextTier] = {
    ContextTier.EXECUTION.value: ContextTier.HYBRID,
    ContextTier.HYBRID.value:    ContextTier.PLANNING,
}


class ModelExecutor:
    """
    Hardware-aware, retry-safe model executor.

    Usage:
        executor = ModelExecutor()
        result = executor.run(
            task_id="01J...",
            task_type=TaskType.BUG_FIX,
            messages=[{"role": "user", "content": "Fix the null pointer at line 42."}],
        )
        # result.response_text — LLM output
        # result.decision      — RoutingDecision used
        # result.duration_ms   — wall-clock time in ms
    """

    def __init__(self, router: Optional[AdaptiveRouter] = None) -> None:
        # Lazy: if None, get_router() is called on first use (singleton)
        self._router = router

    def _get_router(self) -> AdaptiveRouter:
        if self._router is None:
            self._router = get_router()
        return self._router

    # ------------------------------------------------------------------
    # Sync
    # ------------------------------------------------------------------

    def run(
        self,
        task_id: str,
        task_type: TaskType,
        messages: list[dict],
        retry_count: int = 0,
        force_tier: Optional[ContextTier] = None,
        force_class: Optional[CapabilityClass] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> ExecutionResult:
        """
        Execute a model call with retry + context escalation.

        Args:
            task_id:      For logging and telemetry.
            task_type:    Determines base capability class.
            messages:     OpenAI-format message list.
            retry_count:  Retries already consumed by the execution loop
                          (used by router.select() for capability escalation).
            force_tier:   Override context tier (used after escalation).
            force_class:  Override capability class.
            max_retries:  Max retries inside execute_with_retry().

        Returns:
            ExecutionResult with response, timing, and token counts.

        Raises:
            FatalError              if escalation exhausted or auth fails.
            MaxRetriesExceeded      if retryable errors persist past max_retries.
        """
        router = self._get_router()
        escalation_count = 0
        current_tier = force_tier
        current_class = force_class

        while True:
            decision = router.select(
                task_type=task_type,
                retry_count=retry_count,
                force_tier=current_tier,
                force_class=current_class,
            )

            start = time.perf_counter()

            try:
                response = execute_with_retry(
                    fn=lambda: router.complete(decision, messages),
                    max_retries=max_retries,
                    task_id=task_id,
                    current_tier=decision.context_tier.value,
                )

            except ContextEscalationRequired as exc:
                escalation_count += 1
                if escalation_count >= MAX_CONTEXT_ESCALATIONS:
                    raise FatalError(
                        f"Context escalation exhausted after {escalation_count} attempts "
                        f"(last tier: {exc.current_tier}). Task cannot complete.",
                        original_exc=exc,
                    )

                next_tier = _TIER_NEXT.get(exc.current_tier)
                if next_tier is None:
                    raise FatalError(
                        f"No higher context tier available above '{exc.current_tier}'.",
                        original_exc=exc,
                    )

                log.info(
                    "Context escalation",
                    task_id=task_id,
                    from_tier=exc.current_tier,
                    to_tier=next_tier.value,
                    escalation_count=escalation_count,
                )
                current_tier = next_tier
                current_class = None   # re-derive from escalated tier
                continue

            elapsed_ms = int((time.perf_counter() - start) * 1000)

            return _build_result(
                response=response,
                decision=decision,
                elapsed_ms=elapsed_ms,
                retry_count=retry_count,
                escalation_count=escalation_count,
            )

    # ------------------------------------------------------------------
    # Async
    # ------------------------------------------------------------------

    async def arun(
        self,
        task_id: str,
        task_type: TaskType,
        messages: list[dict],
        retry_count: int = 0,
        force_tier: Optional[ContextTier] = None,
        force_class: Optional[CapabilityClass] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> ExecutionResult:
        """Async version of run(). fn must be a coroutine factory."""
        router = self._get_router()
        escalation_count = 0
        current_tier = force_tier
        current_class = force_class

        while True:
            decision = router.select(
                task_type=task_type,
                retry_count=retry_count,
                force_tier=current_tier,
                force_class=current_class,
            )

            start = time.perf_counter()

            try:
                response = await execute_with_retry_async(
                    fn=lambda: router.acomplete(decision, messages),
                    max_retries=max_retries,
                    task_id=task_id,
                    current_tier=decision.context_tier.value,
                )

            except ContextEscalationRequired as exc:
                escalation_count += 1
                if escalation_count >= MAX_CONTEXT_ESCALATIONS:
                    raise FatalError(
                        f"Context escalation exhausted after {escalation_count} attempts "
                        f"(last tier: {exc.current_tier}). Task cannot complete.",
                        original_exc=exc,
                    )

                next_tier = _TIER_NEXT.get(exc.current_tier)
                if next_tier is None:
                    raise FatalError(
                        f"No higher context tier available above '{exc.current_tier}'.",
                        original_exc=exc,
                    )

                log.info(
                    "Context escalation (async)",
                    task_id=task_id,
                    from_tier=exc.current_tier,
                    to_tier=next_tier.value,
                    escalation_count=escalation_count,
                )
                current_tier = next_tier
                current_class = None
                continue

            elapsed_ms = int((time.perf_counter() - start) * 1000)

            return _build_result(
                response=response,
                decision=decision,
                elapsed_ms=elapsed_ms,
                retry_count=retry_count,
                escalation_count=escalation_count,
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_THINK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL)


def _extract_thinking(text: str) -> tuple[str, str | None]:
    """Strip <think>...</think> blocks, return (clean_text, thinking_text)."""
    matches = _THINK_RE.findall(text)
    if not matches:
        return text, None
    thinking = "\n\n".join(m.strip() for m in matches)
    clean = _THINK_RE.sub("", text).strip()
    return clean, thinking


def _build_result(
    response: object,
    decision,
    elapsed_ms: int,
    retry_count: int,
    escalation_count: int,
) -> ExecutionResult:
    """Extract text + token counts from a LiteLLM response object."""
    response_text = ""
    tokens_in: int | None = None
    tokens_generated: int | None = None
    tokens_per_second: float | None = None
    thinking_text: str | None = None

    if hasattr(response, "choices") and response.choices:
        msg = response.choices[0].message
        response_text = (msg.content or "") if hasattr(msg, "content") else ""

        # Check for reasoning_content (DeepSeek-R1 via LiteLLM)
        if hasattr(msg, "reasoning_content") and msg.reasoning_content:
            thinking_text = msg.reasoning_content

    # Check for <think> blocks in response text
    clean_text, think_block = _extract_thinking(response_text)
    if think_block:
        if thinking_text:
            thinking_text = thinking_text + "\n\n" + think_block
        else:
            thinking_text = think_block
        response_text = clean_text

    if hasattr(response, "usage") and response.usage:
        usage = response.usage
        tokens_in        = getattr(usage, "prompt_tokens", None)
        tokens_generated = getattr(usage, "completion_tokens", None)
        if tokens_generated and elapsed_ms > 0:
            tokens_per_second = round(tokens_generated / (elapsed_ms / 1000), 1)

    return ExecutionResult(
        decision=decision,
        response_text=response_text,
        thinking_text=thinking_text,
        tokens_in=tokens_in,
        tokens_generated=tokens_generated,
        tokens_per_second=tokens_per_second,
        duration_ms=elapsed_ms,
        retry_count=retry_count,
        escalation_count=escalation_count,
    )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_executor: ModelExecutor | None = None


def get_executor() -> ModelExecutor:
    """Return the shared ModelExecutor singleton (lazy-initialised)."""
    global _executor
    if _executor is None:
        _executor = ModelExecutor()
    return _executor
