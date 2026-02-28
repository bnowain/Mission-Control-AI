"""
Mission Control — Health Endpoint
===================================
GET /api/health  →  {"status": "ok"}

Required by Atlas (polls every 30 seconds).
Must respond even if subsystems are degraded — use liveness check only.
Full system status is at GET /system/status (Phase 2).
"""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    service: str = "mission-control"
    version: str = "0.1.0"


@router.get("/api/health", response_model=HealthResponse, tags=["system"])
async def health_check() -> HealthResponse:
    """
    Liveness check. Returns 200 + {"status": "ok"} if the process is running.
    Atlas polls this every 30 seconds.
    """
    return HealthResponse(status="ok")
