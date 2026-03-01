"""
Mission Control — Execution Loop
==================================
The main execution loop: pre-task → model call → validate → grade → log → repeat.

Hard limits (from build-roadmap.md):
  MAX_EXECUTION_LOOPS = 10   — total attempts per task before giving up
  MAX_REPLAN_CYCLES   = 3    — replan triggers before aborting (Phase 3)

Flow per loop iteration:
  1. Query Codex for prevention guidelines (inject into prompt)
  2. Call ModelExecutor.run() with retry + escalation handling
  3. Run ValidatorSuite (Phase 1: stubs — all pass)
  4. Grade result with GradingEngine
  5. Log to execution_logs via TelemetryLogger
  6. If passed → return result
  7. If failed and loops remain → increment retry_count, continue
  8. If failed and loop limit hit → register Codex candidate, raise MaxLoopsExceeded
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from app.codex.engine import register_codex_candidate, query_codex
from app.core.exceptions import (
    FatalError,
    MaxLoopsExceeded,
    MaxRetriesExceeded,
)
from app.core.logging import get_logger
from app.grading.engine import GradingEngine
from app.grading.validators import run_validators
from app.models.executor import ModelExecutor, get_executor
from app.models.schemas import (
    CapabilityClass,
    ContextTier,
    GradingResult,
    GradingWeights,
    RoutingDecision,
    TaskType,
)
from app.telemetry.logger import log_execution, log_failure

log = get_logger("execution_loop")

_MAX_PROMPT_CHARS = 10_000  # truncation limit for stored original_prompt

MAX_EXECUTION_LOOPS: int = 10
MAX_REPLAN_CYCLES:   int = 3


@dataclass
class ExecutionContext:
    """
    Everything the execution loop needs to run a task.
    Passed in by the caller — the loop does not fetch from DB itself.
    """
    task_id:      str
    project_id:   str
    task_type:    TaskType
    messages:     list[dict]          # OpenAI-format prompt messages
    signature:    str = ""            # SHA256 fingerprint for Codex lookup
    working_dir:  Optional[str] = None
    grading_weights: Optional[GradingWeights] = None
    human_intervention:  bool = False
    downstream_impact:   bool = False
    prompt_id:           Optional[str] = None
    prompt_version:      Optional[str] = None
    injected_chunk_hashes: list[str] = field(default_factory=list)
    # Phase 7 RAG telemetry (populated by _inject_rag_context)
    rag_chunks_injected: int = 0
    rag_source_ids: list[str] = field(default_factory=list)
    # Optional overrides — map to ModelExecutor force_class / force_tier
    force_class: Optional[CapabilityClass] = None
    force_tier: Optional[ContextTier] = None
    # Optional streaming callback: on_event(event_type, data) called at each step
    on_event: Optional[Callable[[str, dict], None]] = None
    # Agent tool-use fields
    tools: Optional[list] = None          # AGENT_TOOLS list; None = no tool use
    agent_max_iterations: int = 50        # max tool-call rounds per executor call
    agent_session_id: Optional[str] = None  # for ask_user / guardrail pause/resume
    repo_map_tokens: int = 1024           # max tokens for repo map context injection (0 = disabled)


@dataclass
class LoopResult:
    """Outcome of a completed execution loop."""
    task_id:        str
    execution_log_id: str
    grading:        GradingResult
    response_text:  str
    tokens_in:      Optional[int]
    tokens_generated: Optional[int]
    tokens_per_second: Optional[float]
    duration_ms:    Optional[int]
    loop_count:     int
    succeeded:      bool
    decision:       Optional[RoutingDecision] = None
    thinking_text:  Optional[str] = None
    tool_calls_made: int = 0
    agent_iterations: int = 0


def _extract_user_prompt(messages: list[dict]) -> Optional[str]:
    """Return the first user-role message content, truncated to _MAX_PROMPT_CHARS."""
    for msg in messages:
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                return content[:_MAX_PROMPT_CHARS]
            # Handle structured content blocks (list of dicts with "text")
            if isinstance(content, list):
                parts = [
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                ]
                return "".join(parts)[:_MAX_PROMPT_CHARS]
    return None


def _emit(ctx: "ExecutionContext", event_type: str, data: dict) -> None:
    """Fire on_event callback if set. Never raises."""
    if ctx.on_event is None:
        return
    try:
        ctx.on_event(event_type, {"timestamp": time.time(), **data})
    except Exception:
        pass  # never let callback errors kill the execution loop


class ExecutionLoop:
    """
    Orchestrates the full pre→execute→validate→grade→log cycle.

    Usage:
        loop = ExecutionLoop()
        result = loop.run(context)
        if result.succeeded:
            print(result.response_text)
    """

    def __init__(
        self,
        executor: Optional[ModelExecutor] = None,
        grading_engine: Optional[GradingEngine] = None,
    ) -> None:
        self._executor = executor or get_executor()
        self._default_grader = grading_engine or GradingEngine()

    def run(self, ctx: ExecutionContext) -> LoopResult:
        """
        Run the execution loop for a single task.

        Raises:
            MaxLoopsExceeded  — if MAX_EXECUTION_LOOPS is hit without passing
            FatalError        — on unrecoverable error (auth, credits)
        """
        grader = (
            GradingEngine(weights=ctx.grading_weights)
            if ctx.grading_weights
            else self._default_grader
        )

        retry_count    = 0
        loop_count     = 0
        last_exc: Optional[Exception] = None
        messages       = self._inject_rag_context(ctx)
        messages       = self._inject_codex_guidelines_into(ctx, messages)

        _emit(ctx, "started", {
            "task_id":    ctx.task_id,
            "task_type":  ctx.task_type.value,
            "project_id": ctx.project_id,
            "session_id": ctx.agent_session_id,
        })

        while loop_count < MAX_EXECUTION_LOOPS:
            loop_count += 1
            log.info(
                "Execution loop iteration",
                task_id=ctx.task_id,
                loop=loop_count,
                max_loops=MAX_EXECUTION_LOOPS,
                retry_count=retry_count,
            )
            _emit(ctx, "loop_start", {
                "loop":        loop_count,
                "retry_count": retry_count,
            })

            # ── Step 1: Model execution ──────────────────────────────
            exc: Optional[Exception] = None
            result = None

            try:
                result = self._executor.run(
                    task_id=ctx.task_id,
                    task_type=ctx.task_type,
                    messages=messages,
                    retry_count=retry_count,
                    force_class=ctx.force_class,
                    force_tier=ctx.force_tier,
                    tools=ctx.tools if ctx.tools else None,
                    working_dir=ctx.working_dir,
                    max_tool_iterations=ctx.agent_max_iterations,
                    agent_session_id=ctx.agent_session_id,
                    repo_map_tokens=ctx.repo_map_tokens,
                    on_tool_call=lambda name, args, itr: _emit(ctx, "tool_call", {
                        "tool_name": name, "tool_args": args, "iteration": itr,
                    }),
                    on_tool_result=lambda name, content, is_error, itr: _emit(ctx, "tool_result", {
                        "tool_name": name, "content": content[:2000],
                        "is_error": is_error, "iteration": itr,
                    }),
                    on_decision_required=lambda sid, payload, dtype, itr: _emit(ctx, "decision_required", {
                        "session_id": sid, "payload": payload,
                        "decision_type": dtype, "iteration": itr,
                    }),
                )
                retry_count = result.retry_count
                _emit(ctx, "model_response", {
                    "loop":             loop_count,
                    "model":            result.decision.selected_model,
                    "tier":             result.decision.context_tier.value,
                    "tokens_generated": result.tokens_generated,
                    "tokens_per_second": result.tokens_per_second,
                    "duration_ms":      result.duration_ms,
                    "response_preview": (result.response_text or "")[:300],
                })

            except MaxRetriesExceeded as e:
                exc = e
                last_exc = e
                retry_count += e.retry_count
                log.warning(
                    "Max retries exceeded in executor",
                    task_id=ctx.task_id,
                    loop=loop_count,
                    retries=e.retry_count,
                )

            except FatalError:
                raise   # surface immediately — no loop recovery

            # ── Step 2: Validate ─────────────────────────────────────
            if result is not None:
                validation = run_validators(
                    response_text=result.response_text,
                    task_type=ctx.task_type.value,
                    working_dir=ctx.working_dir,
                )
            else:
                # Executor failed — treat as all validators failed
                from app.grading.validators import ValidationResult
                validation = ValidationResult(
                    compile_success=False,
                    tests_passed=False,
                    lint_passed=False,
                    runtime_success=False,
                )

            # ── Step 3: Grade ─────────────────────────────────────────
            grading = grader.grade(
                compile_result=validation.compile_success,
                test_result=validation.tests_passed,
                lint_result=validation.lint_passed,
                runtime_result=validation.runtime_success,
                retry_count=retry_count,
                human_intervention=ctx.human_intervention,
                downstream_impact=ctx.downstream_impact,
            )

            _emit(ctx, "grading", {
                "loop":            loop_count,
                "score":           grading.score,
                "passed":          grading.passed,
                "compile_success": validation.compile_success,
                "tests_passed":    validation.tests_passed,
                "lint_passed":     validation.lint_passed,
                "runtime_success": validation.runtime_success,
            })

            # ── Step 4: Log telemetry ─────────────────────────────────
            decision = result.decision if result else _null_decision(ctx.task_type)

            log_id = log_execution(
                task_id=ctx.task_id,
                project_id=ctx.project_id,
                decision=decision,
                grading=grading,
                tokens_in=result.tokens_in if result else None,
                tokens_generated=result.tokens_generated if result else None,
                tokens_per_second=result.tokens_per_second if result else None,
                duration_ms=result.duration_ms if result else None,
                human_intervention=ctx.human_intervention,
                downstream_impact=ctx.downstream_impact,
                exc=exc,
                prompt_id=ctx.prompt_id,
                prompt_version=ctx.prompt_version,
                injected_chunk_hashes=ctx.injected_chunk_hashes or None,
                rag_chunks_injected=ctx.rag_chunks_injected,
                rag_source_ids=ctx.rag_source_ids or None,
                validator_details=validation.details if validation.details else None,
                actual_model=result.actual_model if result else None,
                task_type=ctx.task_type.value,
                original_prompt=_extract_user_prompt(messages),
            )

            # ── Step 5: Check pass/fail ───────────────────────────────
            if grading.passed:
                log.info(
                    "Task passed",
                    task_id=ctx.task_id,
                    score=grading.score,
                    loop=loop_count,
                    log_id=log_id,
                )
                return LoopResult(
                    task_id=ctx.task_id,
                    execution_log_id=log_id,
                    grading=grading,
                    response_text=result.response_text if result else "",
                    tokens_in=result.tokens_in if result else None,
                    tokens_generated=result.tokens_generated if result else None,
                    tokens_per_second=result.tokens_per_second if result else None,
                    duration_ms=result.duration_ms if result else None,
                    loop_count=loop_count,
                    succeeded=True,
                    decision=result.decision if result else None,
                    thinking_text=result.thinking_text if result else None,
                    tool_calls_made=result.tool_calls_made if result else 0,
                    agent_iterations=result.agent_iterations if result else 0,
                )

            log.warning(
                "Task failed grading — retrying",
                task_id=ctx.task_id,
                score=grading.score,
                loop=loop_count,
                loops_remaining=MAX_EXECUTION_LOOPS - loop_count,
            )

            # ── Step 6: Inject validation feedback for next iteration ──
            _inject_validation_feedback(messages, validation, grading)

            retry_count += 1

        # ── Loop limit hit ────────────────────────────────────────────
        log.error(
            "Hard loop limit hit — task failed",
            task_id=ctx.task_id,
            max_loops=MAX_EXECUTION_LOOPS,
        )

        # Register a Codex candidate for human review
        if ctx.signature:
            try:
                register_codex_candidate(
                    task_id=ctx.task_id,
                    issue_signature=ctx.signature,
                    proposed_root_cause=(
                        f"Task failed after {MAX_EXECUTION_LOOPS} attempts. "
                        f"Last error: {last_exc}" if last_exc else
                        f"Task failed after {MAX_EXECUTION_LOOPS} attempts with low grading score."
                    ),
                )
            except Exception as e:
                log.warning("Failed to register Codex candidate", exc=str(e))

        if last_exc:
            log_failure(task_id=ctx.task_id, exc=last_exc)

        raise MaxLoopsExceeded(loop_count)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _inject_rag_context(self, ctx: ExecutionContext) -> list[dict]:
        """
        Phase 7: Query RAG embeddings and prepend a context block.
        Degrades silently if Ollama is unavailable.
        Returns the (potentially augmented) message list.
        """
        try:
            from app.rag.engine import get_rag_engine
            engine = get_rag_engine()
            augmented, count, source_ids = engine.inject_context(
                task_id=ctx.task_id,
                project_id=ctx.project_id,
                messages=ctx.messages,
            )
            ctx.rag_chunks_injected = count
            ctx.rag_source_ids = source_ids
            return augmented
        except Exception as exc:
            log.warning("RAG injection failed — continuing without RAG", exc=str(exc))
            return ctx.messages

    def _inject_codex_guidelines_into(
        self, ctx: ExecutionContext, messages: list[dict]
    ) -> list[dict]:
        """
        Query Codex for relevant prevention guidelines and prepend
        them as a system message if any are found.
        Operates on the provided messages (which may already have RAG context).
        """
        if not ctx.signature:
            return messages

        guidelines = query_codex(ctx.signature, project_id=ctx.project_id)
        if not guidelines:
            return messages

        lines = ["Relevant lessons from the Codex (apply these to avoid known failure patterns):"]
        for g in guidelines:
            lines.append(f"- [{g.category or 'general'}] {g.prevention_guideline}")

        codex_msg = {"role": "system", "content": "\n".join(lines)}

        # Prepend after any existing system messages, before user message
        system_msgs = [m for m in messages if m.get("role") == "system"]
        other_msgs  = [m for m in messages if m.get("role") != "system"]
        augmented   = system_msgs + [codex_msg] + other_msgs

        log.info(
            "Codex guidelines injected",
            task_id=ctx.task_id,
            count=len(guidelines),
        )
        ctx.injected_chunk_hashes = [g.id for g in guidelines]
        return augmented


# ---------------------------------------------------------------------------
# Validation feedback injection
# ---------------------------------------------------------------------------

def _inject_validation_feedback(
    messages: list[dict],
    validation,
    grading,
) -> None:
    """
    Append a user message describing which validators failed and their output.
    Called before the next retry so the model can self-correct on concrete errors.
    Only injects when there are actual details to report.
    """
    if not validation.details:
        return

    # Map detail key → ValidationResult attribute name
    _attr_map = {
        "compile":  "compile_success",
        "tests":    "tests_passed",
        "lint":     "lint_passed",
        "runtime":  "runtime_success",
    }

    failed_checks = []
    for check, output in validation.details.items():
        attr = _attr_map.get(check)
        passed = getattr(validation, attr, True) if attr else True
        if not passed:
            failed_checks.append((check, output))

    if not failed_checks:
        return  # Nothing actually failed — nothing to inject

    lines = ["Your previous attempt failed validation:"]
    for check, output in failed_checks:
        lines.append(f"- {check}: FAILED")
        if output and output != f"stub — {check} validation not yet implemented":
            lines.append(f"  Output: {output[:500]}")
    lines.append("Fix these specific issues in your next attempt.")

    messages.append({"role": "user", "content": "\n".join(lines)})
    log.info(
        "Validation feedback injected",
        failed_checks=[c for c, _ in failed_checks],
    )


# ---------------------------------------------------------------------------
# Null routing decision — used when executor fails before returning a decision
# ---------------------------------------------------------------------------

def _null_decision(task_type: TaskType):
    """Minimal RoutingDecision for telemetry when executor never returned."""
    from app.models.schemas import ContextTier, RoutingDecision
    return RoutingDecision(
        selected_model="unknown",
        context_size=0,
        context_tier=ContextTier.EXECUTION,
        temperature=0.0,
        routing_reason="executor_failed_before_decision",
    )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_loop: Optional[ExecutionLoop] = None


def get_execution_loop() -> ExecutionLoop:
    global _loop
    if _loop is None:
        _loop = ExecutionLoop()
    return _loop


def run_task(ctx: ExecutionContext) -> LoopResult:
    """Convenience wrapper for ExecutionLoop.run()."""
    return get_execution_loop().run(ctx)
