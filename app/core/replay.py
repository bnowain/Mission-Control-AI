"""
Mission Control — Replay System (Phase 3)
==========================================
Exact replay of a previous execution run using logged metadata.

Replay uses:
  - execution_log.model_id           → which model to call
  - execution_log.context_size       → context window size
  - execution_log.context_tier       → context tier
  - execution_log.temperature        → temperature
  - execution_log.prompt_id          → which prompt template was used
  - execution_log.prompt_version     → which version
  - execution_log.injected_chunk_hashes → which chunks were in context

Replay behaviour (Phase 3):
  1. Load the original execution_log row
  2. Load the prompt template from prompt_registry (if prompt_id exists)
  3. Re-run the model with the same parameters
  4. Grade and log the new result
  5. Return comparison (original score vs replay score)

"Exact" means: same model, same context size, same temperature, same prompt.
Stochasticity from the LLM means the output may differ — that's expected.
"""

from __future__ import annotations

import json
import time
from typing import Optional

from app.core.logging import get_logger
from app.database.init import get_connection
from app.grading.engine import GradingEngine
from app.grading.validators import run_validators
from app.models.schemas import ContextTier, ReplayResponse, RoutingDecision, TaskType
from app.router.adaptive import get_router
from app.telemetry.logger import log_execution

log = get_logger("core.replay")


class ReplayEngine:
    """
    Replays a previous execution run with the same model and context configuration.
    """

    def replay(self, run_id: str) -> ReplayResponse:
        """
        Replay an execution_log entry. Returns ReplayResponse with both scores.
        Raises ValueError if the run_id is not found.
        """
        original = self._load_log(run_id)
        if original is None:
            raise ValueError(f"Execution log '{run_id}' not found.")

        # Build the replay prompt
        prompt_text = self._load_prompt(original)

        # Reconstruct the routing decision from the log
        decision = RoutingDecision(
            selected_model=original["model_id"],
            context_size=original["context_size"],
            context_tier=ContextTier(original["context_tier"]) if original["context_tier"] else ContextTier.EXECUTION,
            temperature=original["temperature"] or 0.1,
            routing_reason=f"replay of {run_id}",
        )

        messages = [{"role": "user", "content": prompt_text}]

        # Run the model
        router = get_router()
        start = time.perf_counter()
        try:
            response = router.complete(decision, messages)
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            response_text = ""
            tokens_in = None
            tokens_generated = None
            if hasattr(response, "choices") and response.choices:
                response_text = response.choices[0].message.content or ""
            if hasattr(response, "usage") and response.usage:
                tokens_in = getattr(response.usage, "prompt_tokens", None)
                tokens_generated = getattr(response.usage, "completion_tokens", None)
        except Exception as exc:
            log.warning("Replay model call failed", run_id=run_id, exc=str(exc))
            raise

        # Grade the replay result
        grader = GradingEngine()
        task_type = original.get("task_type", "generic")
        validation = run_validators(response_text, task_type or "generic")
        grading = grader.grade(
            compile_result=validation.compile_success,
            test_result=validation.tests_passed,
            lint_result=validation.lint_passed,
            runtime_result=validation.runtime_success,
            retry_count=0,
        )

        # Determine pass/fail booleans
        original_passed = bool(original.get("passed")) if original.get("passed") is not None else None
        task_type_str = original.get("task_type") or "generic"

        # Log the replay as a new execution_log row
        new_log_id = log_execution(
            task_id=original["task_id"],
            project_id=original["project_id"],
            decision=decision,
            grading=grading,
            tokens_in=tokens_in,
            tokens_generated=tokens_generated,
            duration_ms=elapsed_ms,
            prompt_id=original.get("prompt_id"),
            prompt_version=original.get("prompt_version"),
            original_prompt=prompt_text,
            task_type=task_type_str,
            validator_details=validation.details if validation.details else None,
        )

        log.info(
            "Replay completed",
            original_run_id=run_id,
            new_run_id=new_log_id,
            original_score=original.get("score"),
            replay_score=grading.score,
        )

        return ReplayResponse(
            original_run_id=run_id,
            new_run_id=new_log_id,
            model_id=original["model_id"],
            context_size=original["context_size"],
            original_score=original.get("score"),
            new_score=grading.score,
            original_passed=original_passed,
            new_passed=grading.passed,
            task_type=task_type_str,
            response_text=response_text,
            duration_ms=elapsed_ms,
            validator_details=validation.details if validation.details else None,
        )

    def _load_log(self, run_id: str) -> Optional[dict]:
        """Fetch execution_log row joined with tasks for task_type."""
        conn = get_connection()
        try:
            row = conn.execute(
                """
                SELECT e.*, t.task_type
                FROM execution_logs e
                JOIN tasks t ON e.task_id = t.id
                WHERE e.id = ?
                """,
                (run_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def _load_prompt(self, log_row: dict) -> str:
        """
        Load the original prompt text using three-tier priority:
        1. original_prompt stored in the log row (v10+)
        2. prompt_registry lookup via prompt_id
        3. Generic fallback (logged as warning)
        """
        # Tier 1: stored original prompt (schema v10)
        stored = log_row.get("original_prompt")
        if stored:
            return stored

        # Tier 2: prompt_registry lookup
        prompt_id = log_row.get("prompt_id")
        if prompt_id:
            conn = get_connection()
            try:
                row = conn.execute(
                    "SELECT template_text FROM prompt_registry WHERE id = ?",
                    (prompt_id,),
                ).fetchone()
                if row:
                    return row["template_text"]
            finally:
                conn.close()

        # Tier 3: generic fallback
        log.warning(
            "Replay prompt not found; using generic fallback",
            run_id=log_row.get("id"),
            prompt_id=prompt_id,
        )
        return (
            f"[Replay of execution {log_row['id']}]\n"
            f"Task type: {log_row.get('task_type', 'unknown')}\n"
            f"Original score: {log_row.get('score', 'unknown')}\n"
            f"Please produce the best possible output for this task."
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_replay_engine = ReplayEngine()


def replay_run(run_id: str) -> ReplayResponse:
    """Convenience wrapper for ReplayEngine.replay()."""
    return _replay_engine.replay(run_id)
