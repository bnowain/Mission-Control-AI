"""
Mission Control — Worker Scheduler (Phase 4)
=============================================
Job queue backed by processing_jobs DB table.
Uses ULID for job IDs (schema-decisions.md).

Job lifecycle:
  QUEUED → RUNNING → COMPLETED
                   → FAILED (if retry_count >= max_retries)
  RUNNING → RETRYING → QUEUED (retry loop)

Idempotency: same idempotency_key → same job returned, no duplicate insert.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from ulid import ULID

from app.core.logging import get_logger
from app.database.init import get_connection
from app.models.schemas import JobStatus

log = get_logger("processing.worker")


class WorkerScheduler:
    """
    Manages the processing_jobs table for job dispatch and tracking.
    All methods are synchronous; wrap with run_in_thread() at API layer.
    """

    # ── Enqueue ──────────────────────────────────────────────────────────────

    def enqueue(
        self,
        job_type: str,
        payload: Optional[dict] = None,
        priority: int = 5,
        artifact_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        max_retries: int = 3,
    ) -> dict:
        """
        Enqueue a new job. Returns existing job if idempotency_key already exists.
        """
        # Idempotency check
        if idempotency_key:
            conn = get_connection()
            try:
                existing = conn.execute(
                    "SELECT * FROM processing_jobs WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if existing:
                    log.info("Job idempotency hit", idempotency_key=idempotency_key)
                    return dict(existing)
            finally:
                conn.close()

        job_id = str(ULID())
        now = datetime.now(timezone.utc).isoformat()

        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO processing_jobs
                    (id, artifact_id, job_type, job_status, priority,
                     idempotency_key, retry_count, max_retries,
                     payload_json, created_at)
                VALUES (?, ?, ?, 'QUEUED', ?, ?, 0, ?, ?, ?)
                """,
                (
                    job_id,
                    artifact_id,
                    job_type,
                    priority,
                    idempotency_key,
                    max_retries,
                    json.dumps(payload or {}),
                    now,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM processing_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            log.info("Job enqueued", job_id=job_id, job_type=job_type, priority=priority)
            return dict(row)
        finally:
            conn.close()

    # ── Claim next ───────────────────────────────────────────────────────────

    def claim_next(self, worker_id: Optional[str] = None) -> Optional[dict]:
        """
        Atomically claim the next available QUEUED job (lowest priority number first).
        Returns the job dict or None if queue is empty.
        """
        conn = get_connection()
        try:
            row = conn.execute(
                """
                SELECT * FROM processing_jobs
                WHERE job_status = 'QUEUED'
                ORDER BY priority ASC, created_at ASC
                LIMIT 1
                """,
            ).fetchone()

            if row is None:
                return None

            job_id = row["id"]
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """
                UPDATE processing_jobs
                SET job_status = 'RUNNING', worker_id = ?, started_at = ?
                WHERE id = ?
                """,
                (worker_id or "default", now, job_id),
            )
            conn.commit()

            updated = conn.execute(
                "SELECT * FROM processing_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            log.info("Job claimed", job_id=job_id, worker_id=worker_id)
            return dict(updated)
        finally:
            conn.close()

    # ── Complete ─────────────────────────────────────────────────────────────

    def complete_job(self, job_id: str, result: Optional[dict] = None) -> dict:
        """Mark a job as COMPLETED with optional result payload."""
        now = datetime.now(timezone.utc).isoformat()
        conn = get_connection()
        try:
            conn.execute(
                """
                UPDATE processing_jobs
                SET job_status = 'COMPLETED', completed_at = ?, result_json = ?
                WHERE id = ?
                """,
                (now, json.dumps(result or {}), job_id),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM processing_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            log.info("Job completed", job_id=job_id)
            return dict(row)
        finally:
            conn.close()

    # ── Fail ─────────────────────────────────────────────────────────────────

    def fail_job(self, job_id: str, error_message: str) -> dict:
        """
        Mark job as FAILED or RETRYING depending on retry_count vs max_retries.
        If retry_count < max_retries: set RETRYING, increment retry_count.
        If retry_count >= max_retries: set FAILED.
        """
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM processing_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Job '{job_id}' not found")

            retry_count = (row["retry_count"] or 0) + 1
            max_retries = row["max_retries"] or 3

            if retry_count >= max_retries:
                new_status = "FAILED"
            else:
                new_status = "RETRYING"

            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """
                UPDATE processing_jobs
                SET job_status = ?, retry_count = ?, error_message = ?,
                    completed_at = CASE WHEN ? = 'FAILED' THEN ? ELSE completed_at END
                WHERE id = ?
                """,
                (new_status, retry_count, error_message, new_status, now, job_id),
            )
            conn.commit()

            updated = conn.execute(
                "SELECT * FROM processing_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            log.info("Job failed/retrying", job_id=job_id, new_status=new_status, retry_count=retry_count)
            return dict(updated)
        finally:
            conn.close()

    # ── Get / List ───────────────────────────────────────────────────────────

    def get_job(self, job_id: str) -> Optional[dict]:
        """Fetch a single job by ID. Returns None if not found."""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM processing_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def list_jobs(
        self,
        job_status: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """Return (jobs, total_count) with optional status filter."""
        where = "WHERE job_status = ?" if job_status else ""
        params: list = [job_status] if job_status else []

        conn = get_connection()
        try:
            total = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM processing_jobs {where}", params
            ).fetchone()["cnt"]

            rows = conn.execute(
                f"SELECT * FROM processing_jobs {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()
            return [dict(r) for r in rows], total
        finally:
            conn.close()

    # ── Stats ────────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Return job counts by status."""
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT job_status, COUNT(*) AS cnt FROM processing_jobs GROUP BY job_status"
            ).fetchall()
            counts: dict[str, int] = {r["job_status"]: r["cnt"] for r in rows}
        finally:
            conn.close()

        return {
            "queued":    counts.get("QUEUED", 0),
            "running":   counts.get("RUNNING", 0),
            "completed": counts.get("COMPLETED", 0),
            "failed":    counts.get("FAILED", 0),
            "retrying":  counts.get("RETRYING", 0),
            "total":     sum(counts.values()),
        }


# ---------------------------------------------------------------------------
# Module-level singleton + convenience wrappers
# ---------------------------------------------------------------------------

_scheduler = WorkerScheduler()


def enqueue_job(job_type: str, **kwargs) -> dict:
    return _scheduler.enqueue(job_type, **kwargs)


def claim_next_job(worker_id: Optional[str] = None) -> Optional[dict]:
    return _scheduler.claim_next(worker_id)


def complete_job(job_id: str, result: Optional[dict] = None) -> dict:
    return _scheduler.complete_job(job_id, result)


def fail_job(job_id: str, error_message: str) -> dict:
    return _scheduler.fail_job(job_id, error_message)


def get_job(job_id: str) -> Optional[dict]:
    return _scheduler.get_job(job_id)


def list_jobs(job_status: Optional[str] = None, limit: int = 20, offset: int = 0) -> tuple[list[dict], int]:
    return _scheduler.list_jobs(job_status=job_status, limit=limit, offset=offset)


def get_worker_stats() -> dict:
    return _scheduler.get_stats()
