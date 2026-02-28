"""
Mission Control — Workers API (Phase 4)
=========================================
GET /workers/pipelines   — list pipelines and availability
GET /workers/jobs        — paginated job list
GET /workers/jobs/{id}   — single job
GET /workers/stats       — job counts by status
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.database.async_helpers import run_in_thread
from app.models.schemas import (
    JobListResponse,
    JobResponse,
    JobStatus,
    PipelineAvailabilityResponse,
    WorkerStatsResponse,
)
from app.processing.pipeline_registry import list_pipelines
from app.processing.worker import get_job, get_worker_stats, list_jobs

router = APIRouter(prefix="/workers", tags=["workers"])


def _job_row_to_response(row: dict) -> JobResponse:
    return JobResponse(
        id=row["id"],
        artifact_id=row.get("artifact_id"),
        job_type=row["job_type"],
        job_status=JobStatus(row["job_status"]),
        priority=row["priority"],
        idempotency_key=row.get("idempotency_key"),
        worker_id=row.get("worker_id"),
        retry_count=row.get("retry_count", 0),
        max_retries=row.get("max_retries", 3),
        error_message=row.get("error_message"),
        payload_json=row.get("payload_json"),
        result_json=row.get("result_json"),
        created_at=str(row.get("created_at", "")),
        started_at=str(row["started_at"]) if row.get("started_at") else None,
        completed_at=str(row["completed_at"]) if row.get("completed_at") else None,
    )


# ── GET /workers/pipelines ───────────────────────────────────────────────────

@router.get("/pipelines", response_model=list[PipelineAvailabilityResponse])
async def get_pipelines():
    """List all registered pipelines with their availability status."""
    pipelines = await run_in_thread(list_pipelines)
    return [
        PipelineAvailabilityResponse(name=p["name"], available=p["available"])
        for p in pipelines
    ]


# ── GET /workers/jobs ────────────────────────────────────────────────────────

@router.get("/jobs", response_model=JobListResponse)
async def get_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    job_status: Optional[str] = Query(default=None),
):
    """Paginated list of processing jobs."""
    rows, total = await run_in_thread(
        list_jobs,
        job_status=job_status,
        limit=limit,
        offset=offset,
    )
    return JobListResponse(
        jobs=[_job_row_to_response(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


# ── GET /workers/jobs/{id} ───────────────────────────────────────────────────

@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job_by_id(job_id: str):
    """Fetch a single job by ID."""
    row = await run_in_thread(get_job, job_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return _job_row_to_response(row)


# ── GET /workers/stats ───────────────────────────────────────────────────────

@router.get("/stats", response_model=WorkerStatsResponse)
async def get_stats():
    """Job counts by status."""
    stats = await run_in_thread(get_worker_stats)
    return WorkerStatsResponse(**stats)
