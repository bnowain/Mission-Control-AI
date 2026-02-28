"""
Mission Control — Health Endpoint (Phase 8 enhanced)
=====================================================
GET /api/health  →  {"status": "ok|degraded", ...}

Required by Atlas (polls every 30 seconds).
Always returns 200 — even when subsystems are degraded.
Use status field to determine actual health.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class GPUStatus(BaseModel):
    available: bool
    vram_mb: Optional[int] = None
    utilization_percent: Optional[float] = None


class HealthResponse(BaseModel):
    status: str               # ok | degraded
    service: str = "mission-control"
    version: str = "0.1.0"
    db_connectivity: bool = True
    worker_status: str = "online"   # online | offline | degraded
    gpu_status: Optional[dict[str, Any]] = None


def _check_db() -> bool:
    """Return True if DB is reachable."""
    try:
        from app.database.init import get_connection
        conn = get_connection()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        return True
    except Exception:
        return False


def _check_workers() -> str:
    """Return worker status string."""
    try:
        from app.database.init import get_connection
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM processing_jobs WHERE job_status = 'RUNNING'"
            ).fetchone()
            running = row[0] if row else 0
            queued_row = conn.execute(
                "SELECT COUNT(*) FROM processing_jobs WHERE job_status = 'QUEUED'"
            ).fetchone()
            queued = queued_row[0] if queued_row else 0
        finally:
            conn.close()
        # Simple heuristic: many stuck RUNNING jobs = degraded
        if running > 50:
            return "degraded"
        return "online"
    except Exception:
        return "offline"


def _check_gpu() -> dict[str, Any]:
    """Return GPU status from hardware profile or torch probe."""
    result: dict[str, Any] = {"available": False}
    try:
        import torch
        if torch.cuda.is_available():
            result["available"] = True
            # VRAM in MB
            props = torch.cuda.get_device_properties(0)
            result["vram_mb"] = props.total_memory // (1024 * 1024)
            # Utilisation approximated via allocated vs total
            allocated = torch.cuda.memory_allocated(0)
            total = props.total_memory
            result["utilization_percent"] = round(allocated / total * 100, 1) if total else 0.0
    except Exception:
        pass
    return result


@router.get("/api/health", response_model=HealthResponse, tags=["system"])
async def health_check() -> HealthResponse:
    """
    Full health check. Always returns HTTP 200.
    Check `status` field for actual health: 'ok' | 'degraded'.
    Atlas polls this every 30 seconds.
    """
    db_ok = _check_db()
    worker_status = _check_workers()
    gpu_status = _check_gpu()

    overall = "ok"
    if not db_ok or worker_status == "offline":
        overall = "degraded"

    return HealthResponse(
        status=overall,
        db_connectivity=db_ok,
        worker_status=worker_status,
        gpu_status=gpu_status,
    )
