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
from typing import Callable, Optional

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
        # Agent tool-use parameters (all optional — None = standard non-agent mode)
        tools: Optional[list] = None,
        working_dir: Optional[str] = None,
        max_tool_iterations: int = 50,
        agent_session_id: Optional[str] = None,
        on_tool_call: Optional[Callable] = None,
        on_tool_result: Optional[Callable] = None,
        on_decision_required: Optional[Callable] = None,
        repo_map_tokens: int = 1024,
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

        # ── Agent mode: tools + working_dir provided ──────────────────────
        if tools and working_dir:
            return self._run_agent(
                task_id=task_id,
                task_type=task_type,
                messages=messages,
                retry_count=retry_count,
                force_tier=force_tier,
                force_class=force_class,
                tools=tools,
                working_dir=working_dir,
                max_tool_iterations=max_tool_iterations,
                agent_session_id=agent_session_id,
                on_tool_call=on_tool_call,
                on_tool_result=on_tool_result,
                on_decision_required=on_decision_required,
                repo_map_tokens=repo_map_tokens,
                router=router,
            )

        # ── Standard mode: single model call with retry + escalation ─────
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
    # Agent mode
    # ------------------------------------------------------------------

    def _run_agent(
        self,
        task_id: str,
        task_type: TaskType,
        messages: list[dict],
        retry_count: int,
        force_tier: Optional[ContextTier],
        force_class: Optional[CapabilityClass],
        tools: list,
        working_dir: str,
        max_tool_iterations: int,
        agent_session_id: Optional[str],
        on_tool_call: Optional[Callable],
        on_tool_result: Optional[Callable],
        on_decision_required: Optional[Callable],
        repo_map_tokens: int,
        router: "AdaptiveRouter",
    ) -> "ExecutionResult":
        """
        Run the model in tool-call loop mode.
        Uses the agent system prompt + AGENT_TOOLS.
        No retry/escalation wrapper — each router.complete() call in the loop
        is a direct call. Context escalation is not supported in agent mode.
        """
        from app.tools.definitions import AGENT_SYSTEM_PROMPT
        from app.tools.executor import ToolExecutor
        from app.tools.loop import run_agent_loop

        # Prepend agent system prompt
        has_system = any(m.get("role") == "system" for m in messages)
        agent_messages = list(messages)
        if not has_system:
            agent_messages = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}] + agent_messages

        # Inject repo map context (graceful degradation on any failure)
        if repo_map_tokens > 0:
            try:
                from app.tools.repomap import generate_repo_map
                repo_map = generate_repo_map(working_dir, max_tokens=repo_map_tokens)
                if repo_map:
                    # Insert user/assistant pair after system message, before user prompt.
                    # This pattern gives better model attention than appending to system.
                    insert_idx = 1 if has_system or not messages else 1
                    agent_messages.insert(
                        insert_idx,
                        {"role": "user", "content": f"Here is a map of the workspace:\n\n{repo_map}"},
                    )
                    agent_messages.insert(
                        insert_idx + 1,
                        {"role": "assistant", "content": "Thank you, I'll use this to navigate the codebase efficiently."},
                    )
                    log.debug("Repo map injected", task_id=task_id, tokens_approx=repo_map_tokens)
            except Exception as exc:
                log.warning("Repo map generation failed — continuing without it", exc=str(exc))

        # Select routing decision
        decision = router.select(
            task_type=task_type,
            retry_count=retry_count,
            force_tier=force_tier,
            force_class=force_class,
        )

        # Set up sandbox executor
        try:
            tool_executor = ToolExecutor(working_dir)
        except ValueError as exc:
            raise FatalError(
                f"Cannot create agent executor: {exc}", original_exc=exc
            )

        start = time.perf_counter()

        loop_result = run_agent_loop(
            router=router,
            decision=decision,
            messages=agent_messages,
            tools=tools,
            tool_executor=tool_executor,
            max_iterations=max_tool_iterations,
            on_tool_call=on_tool_call,
            on_tool_result=on_tool_result,
            on_decision_required=on_decision_required,
            session_id=agent_session_id,
        )

        elapsed_ms = int((time.perf_counter() - start) * 1000)

        log.info(
            "Agent loop complete",
            task_id=task_id,
            tool_calls=loop_result.tool_calls_made,
            iterations=loop_result.iterations,
            duration_ms=elapsed_ms,
        )

        return ExecutionResult(
            decision=decision,
            response_text=loop_result.response_text,
            thinking_text=loop_result.thinking_text,
            tokens_in=None,
            tokens_generated=None,
            tokens_per_second=None,
            duration_ms=elapsed_ms,
            retry_count=retry_count,
            escalation_count=0,
            tool_calls_made=loop_result.tool_calls_made,
            agent_iterations=loop_result.iterations,
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
    actual_model: str | None = None

    if hasattr(response, "choices") and response.choices:
        msg = response.choices[0].message
        response_text = (msg.content or "") if hasattr(msg, "content") else ""

        # Check for reasoning_content (DeepSeek-R1 via LiteLLM)
        if hasattr(msg, "reasoning_content") and msg.reasoning_content:
            thinking_text = msg.reasoning_content

    # Capture actual model name from LiteLLM response (guard against mock objects)
    if hasattr(response, "model") and isinstance(response.model, str) and response.model:
        actual_model = response.model

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
        tool_calls_made=0,
        agent_iterations=0,
        actual_model=actual_model,
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
