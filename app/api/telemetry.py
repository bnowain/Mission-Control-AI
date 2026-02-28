"""
Mission Control — Telemetry API
=================================
GET /telemetry/runs          → paginated execution_logs
GET /telemetry/models        → per-model aggregates
GET /telemetry/performance   → system-wide metrics
GET /telemetry/hardware      → hardware_profiles
"""

from typing import Optional

from fastapi import APIRouter, Query

from app.database.async_helpers import run_in_thread
from app.database.init import get_connection
from app.models.schemas import (
    TelemetryHardwareResponse,
    TelemetryModelStats,
    TelemetryModelsResponse,
    TelemetryPerformanceResponse,
    TelemetryRunsResponse,
)

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


# ---------------------------------------------------------------------------
# Sync helpers
# ---------------------------------------------------------------------------

def _get_runs_sync(
    limit: int,
    offset: int,
    task_id: Optional[str],
    model_id: Optional[str],
) -> TelemetryRunsResponse:
    conn = get_connection()
    try:
        conditions = []
        params: list = []
        if task_id:
            conditions.append("task_id = ?")
            params.append(task_id)
        if model_id:
            conditions.append("model_id = ?")
            params.append(model_id)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        total = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM execution_logs {where}", params
        ).fetchone()["cnt"]

        rows = conn.execute(
            f"""
            SELECT *
            FROM execution_logs {where}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ).fetchall()

        return TelemetryRunsResponse(
            runs=[dict(r) for r in rows],
            total=total,
            limit=limit,
            offset=offset,
        )
    finally:
        conn.close()


def _get_model_stats_sync() -> TelemetryModelsResponse:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT model_id,
                   COUNT(*) AS run_count,
                   AVG(score) AS average_score,
                   AVG(duration_ms) AS average_duration_ms,
                   AVG(CAST(passed AS REAL)) AS pass_rate
            FROM execution_logs
            GROUP BY model_id
            ORDER BY run_count DESC
            """
        ).fetchall()

        return TelemetryModelsResponse(
            models=[
                TelemetryModelStats(
                    model_id=r["model_id"],
                    run_count=r["run_count"],
                    average_score=r["average_score"],
                    average_duration_ms=r["average_duration_ms"],
                    pass_rate=r["pass_rate"],
                )
                for r in rows
            ]
        )
    finally:
        conn.close()


def _get_performance_sync() -> TelemetryPerformanceResponse:
    conn = get_connection()
    try:
        stats = conn.execute(
            """
            SELECT COUNT(*) AS total_runs,
                   AVG(CAST(passed AS REAL)) AS overall_pass_rate,
                   AVG(score) AS average_score,
                   AVG(duration_ms) AS average_duration_ms
            FROM execution_logs
            """
        ).fetchone()

        task_count = conn.execute("SELECT COUNT(*) AS cnt FROM tasks").fetchone()["cnt"]

        return TelemetryPerformanceResponse(
            total_runs=stats["total_runs"] or 0,
            total_tasks=task_count,
            overall_pass_rate=stats["overall_pass_rate"],
            average_score=stats["average_score"],
            average_duration_ms=stats["average_duration_ms"],
        )
    finally:
        conn.close()


def _get_hardware_sync() -> TelemetryHardwareResponse:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, gpu_name, vram_mb, benchmark_tokens_per_sec, created_at "
            "FROM hardware_profiles ORDER BY created_at DESC"
        ).fetchall()
        return TelemetryHardwareResponse(profiles=[dict(r) for r in rows])
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/runs", response_model=TelemetryRunsResponse)
async def telemetry_runs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    task_id: Optional[str] = Query(None),
    model_id: Optional[str] = Query(None),
) -> TelemetryRunsResponse:
    """Paginated execution log — filter by task_id or model_id."""
    return await run_in_thread(_get_runs_sync, limit, offset, task_id, model_id)


@router.get("/models", response_model=TelemetryModelsResponse)
async def telemetry_models() -> TelemetryModelsResponse:
    """Per-model aggregate stats: run count, avg score, pass rate, avg duration."""
    return await run_in_thread(_get_model_stats_sync)


@router.get("/performance", response_model=TelemetryPerformanceResponse)
async def telemetry_performance() -> TelemetryPerformanceResponse:
    """System-wide metrics: total runs, tasks, pass rate, avg score."""
    return await run_in_thread(_get_performance_sync)


@router.get("/hardware", response_model=TelemetryHardwareResponse)
async def telemetry_hardware() -> TelemetryHardwareResponse:
    """Hardware profile history."""
    return await run_in_thread(_get_hardware_sync)
