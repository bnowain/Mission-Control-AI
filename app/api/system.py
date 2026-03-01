"""
Mission Control — System API
==============================
GET /system/status  → DB connectivity, schema version, active task count
GET /system/hardware → GPU/VRAM info from hardware_profiler
"""

import os
import signal
import threading

from fastapi import APIRouter
from fastapi.responses import JSONResponse

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


@router.get("/ollama/ps")
async def ollama_ps() -> JSONResponse:
    """
    Proxy Ollama's GET /api/ps — returns currently loaded models with size/VRAM.
    Returns empty list if Ollama is unreachable.
    """
    import urllib.request, json
    try:
        with urllib.request.urlopen("http://localhost:11434/api/ps", timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return JSONResponse(content=data)
    except Exception:
        return JSONResponse(content={"models": []})


@router.post("/shutdown")
async def shutdown() -> JSONResponse:
    """
    Gracefully shut down the Mission Control server.
    The response is sent first, then the process exits after a short delay.
    """
    def _do_shutdown():
        import time
        time.sleep(0.5)   # give the response time to flush
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=_do_shutdown, daemon=True).start()
    return JSONResponse(content={"status": "shutting_down"})


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
