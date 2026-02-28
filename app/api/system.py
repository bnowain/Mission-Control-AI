"""
Mission Control — System API
==============================
GET /system/status  → DB connectivity, schema version, active task count
GET /system/hardware → GPU/VRAM info from hardware_profiler
"""

from fastapi import APIRouter

from app.database.async_helpers import run_in_thread
from app.database.init import DB_PATH, SCHEMA_VERSION, get_connection
from app.models.schemas import SystemHardwareResponse, SystemStatusResponse
from app.router.hardware_profiler import available_capability_classes, detect_hardware

router = APIRouter(prefix="/system", tags=["system"])


def _get_status_sync() -> SystemStatusResponse:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT version FROM schema_version ORDER BY applied_at DESC LIMIT 1"
        ).fetchone()
        schema_ver = row["version"] if row else 0

        active = conn.execute(
            "SELECT COUNT(*) AS cnt FROM tasks WHERE task_status IN ('pending', 'running')"
        ).fetchone()["cnt"]
    finally:
        conn.close()

    return SystemStatusResponse(
        status="ok",
        schema_version=schema_ver,
        active_task_count=active,
        db_path=str(DB_PATH),
    )


@router.get("/status", response_model=SystemStatusResponse)
async def system_status() -> SystemStatusResponse:
    """DB connectivity, schema version, and active task count."""
    return await run_in_thread(_get_status_sync)


@router.get("/hardware", response_model=SystemHardwareResponse)
async def system_hardware() -> SystemHardwareResponse:
    """GPU/VRAM profile and available capability classes."""
    profile = await run_in_thread(detect_hardware)
    classes = available_capability_classes(profile)
    return SystemHardwareResponse(
        gpu_name=profile.gpu_name,
        vram_mb=profile.vram_mb,
        benchmark_tokens_per_sec=profile.benchmark_tokens_per_sec,
        available_capability_classes=[c.value for c in classes],
    )
