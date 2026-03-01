"""
Mission Control — Telemetry Logger
=====================================
Writes structured execution records to the execution_logs table.
Stack trace hashing from: kb-execution-validation-telemetry.md → n8n pattern

Every execution — success or failure — produces one row in execution_logs.
The row captures everything needed for:
  - Router learning (model performance per task_type)
  - Exact replay (prompt_version + injected_chunk_hashes)
  - Failure clustering (stack_trace_hash)
  - Codex candidate promotion (human_intervention flag)
"""

from __future__ import annotations

import hashlib
import json
import traceback
from datetime import datetime, timezone
from typing import Optional

from ulid import ULID

from app.core.logging import get_logger
from app.database.init import get_connection
from app.models.schemas import GradingResult, RoutingDecision

log = get_logger("telemetry")

_MAX_DETAIL_CHARS = 2000


# ---------------------------------------------------------------------------
# Stack trace hashing (n8n pattern)
# ---------------------------------------------------------------------------

def hash_stack_trace(exc: Exception) -> str:
    """
    Normalise and hash a stack trace for deduplication.
    Strips line numbers (change too often) — keeps filename:function.
    Same bug across different code versions → same hash.
    """
    frames = traceback.extract_tb(exc.__traceback__) if exc.__traceback__ else []
    normalized = [
        f"{frame.filename.split('/')[-1].split(chr(92))[-1]}:{frame.name}"
        for frame in frames
    ]
    key = "|".join(normalized) + f"|{type(exc).__name__}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Telemetry logger
# ---------------------------------------------------------------------------

class TelemetryLogger:
    """
    Writes one execution_log row per task execution.
    Instantiate per-task or use the module-level log_execution() helper.
    """

    def log_execution(
        self,
        task_id: str,
        project_id: str,
        decision: RoutingDecision,
        grading: GradingResult,
        tokens_in: Optional[int] = None,
        tokens_generated: Optional[int] = None,
        tokens_per_second: Optional[float] = None,
        duration_ms: Optional[int] = None,
        human_intervention: bool = False,
        downstream_impact: bool = False,
        exc: Optional[Exception] = None,
        prompt_id: Optional[str] = None,
        prompt_version: Optional[str] = None,
        injected_chunk_hashes: Optional[list[str]] = None,
        rag_chunks_injected: int = 0,
        rag_source_ids: Optional[list[str]] = None,
        validator_details: Optional[dict] = None,
        actual_model: Optional[str] = None,
        task_type: Optional[str] = None,
        original_prompt: Optional[str] = None,
    ) -> str:
        """
        Write a telemetry record. Returns the new execution_log id (ULID).
        """
        log_id = str(ULID())
        stack_hash = hash_stack_trace(exc) if exc is not None else None

        # Truncate individual detail values before serialising
        validator_details_json: Optional[str] = None
        if validator_details:
            truncated = {
                k: v[:_MAX_DETAIL_CHARS] if isinstance(v, str) else v
                for k, v in validator_details.items()
            }
            validator_details_json = json.dumps(truncated)

        conn = get_connection()
        try:
            # Auto-register model if not already in models table (handles
            # capability-class names like "fast_model" when no real model
            # is configured, as well as any unregistered model strings).
            model_id = decision.selected_model
            _CAPABILITY_CLASSES = {
                "fast_model", "coder_model", "reasoning_model", "planner_model",
            }
            provider = model_id.split("/")[0] if "/" in model_id else "unknown"
            cap_class = (
                model_id if model_id in _CAPABILITY_CLASSES else "fast_model"
            )
            conn.execute(
                """INSERT OR IGNORE INTO models
                   (id, display_name, provider, capability_class)
                   VALUES (?, ?, ?, ?)""",
                (model_id, model_id, provider, cap_class),
            )

            conn.execute(
                """
                INSERT INTO execution_logs (
                    id, task_id, project_id, model_id,
                    context_size, context_tier, temperature,
                    tokens_in, tokens_generated, tokens_per_second, retries,
                    score, passed,
                    compile_success, tests_passed, lint_passed, runtime_success,
                    human_intervention, downstream_impact,
                    duration_ms, routing_reason, stack_trace_hash,
                    prompt_id, prompt_version, injected_chunk_hashes,
                    original_prompt,
                    rag_chunks_injected, rag_source_ids,
                    validator_details, actual_model,
                    created_at
                ) VALUES (
                    ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?,
                    ?, ?, ?, ?,
                    ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?,
                    ?, ?,
                    ?, ?,
                    ?
                )
                """,
                (
                    log_id,
                    task_id,
                    project_id,
                    model_id,
                    decision.context_size,
                    decision.context_tier.value,
                    decision.temperature,
                    tokens_in,
                    tokens_generated,
                    tokens_per_second,
                    grading.retry_count,
                    grading.score,
                    int(grading.passed),
                    int(grading.compile_success),
                    int(grading.tests_passed),
                    int(grading.lint_passed),
                    int(grading.runtime_success),
                    int(human_intervention),
                    int(downstream_impact),
                    duration_ms,
                    decision.routing_reason,
                    stack_hash,
                    prompt_id,
                    prompt_version,
                    json.dumps(injected_chunk_hashes) if injected_chunk_hashes else None,
                    original_prompt,
                    rag_chunks_injected,
                    json.dumps(rag_source_ids) if rag_source_ids else None,
                    validator_details_json,
                    actual_model,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

        log.info(
            "Execution logged",
            log_id=log_id,
            task_id=task_id,
            model=decision.selected_model,
            score=grading.score,
            passed=grading.passed,
            retries=grading.retry_count,
            duration_ms=duration_ms,
        )

        # Update routing_stats after logging (best-effort)
        if task_type:
            self._update_routing_stats(model_id=model_id, task_type=task_type)

        return log_id

    def _update_routing_stats(self, model_id: str, task_type: str) -> None:
        """Upsert routing_stats with latest aggregated data from execution_logs."""
        conn = get_connection()
        try:
            row = conn.execute(
                """
                SELECT AVG(e.score), AVG(e.retries),
                       AVG(CASE WHEN e.passed THEN 1.0 ELSE 0.0 END), COUNT(*)
                FROM execution_logs e
                JOIN tasks t ON e.task_id = t.id
                WHERE e.model_id = ? AND t.task_type = ?
                """,
                (model_id, task_type),
            ).fetchone()
            if row and row[3] > 0:
                conn.execute(
                    """
                    INSERT INTO routing_stats
                        (id, model_id, task_type,
                         average_score, average_retries, success_rate, sample_size, last_updated)
                    VALUES (hex(randomblob(16)), ?, ?, ?, ?, ?, ?, datetime('now'))
                    ON CONFLICT(model_id, task_type) DO UPDATE SET
                        average_score   = excluded.average_score,
                        average_retries = excluded.average_retries,
                        success_rate    = excluded.success_rate,
                        sample_size     = excluded.sample_size,
                        last_updated    = excluded.last_updated
                    """,
                    (model_id, task_type, row[0], row[1], row[2], row[3]),
                )
                conn.commit()
        except Exception as e:
            log.warning("routing_stats update failed", exc=str(e))
        finally:
            conn.close()

    def log_failure_event(
        self,
        task_id: str,
        exc: Exception,
        file_path: Optional[str] = None,
        diff_hash: Optional[str] = None,
    ) -> str:
        """
        Write a failure_events record for clustering and Codex candidate promotion.
        Returns the new failure_event id (ULID).
        """
        event_id     = str(ULID())
        stack_hash   = hash_stack_trace(exc)
        error_type   = type(exc).__name__

        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO failure_events
                    (id, task_id, error_type, stack_trace_hash, file_path, diff_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    task_id,
                    error_type,
                    stack_hash,
                    file_path,
                    diff_hash,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

        log.warning(
            "Failure event recorded",
            event_id=event_id,
            task_id=task_id,
            error_type=error_type,
            stack_hash=stack_hash,
        )
        return event_id


# Module-level singleton
_telemetry = TelemetryLogger()


def log_execution(**kwargs) -> str:
    """Convenience wrapper around TelemetryLogger.log_execution()."""
    return _telemetry.log_execution(**kwargs)


def log_failure(**kwargs) -> str:
    """Convenience wrapper around TelemetryLogger.log_failure_event()."""
    return _telemetry.log_failure_event(**kwargs)
