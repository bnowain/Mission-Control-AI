"""
Mission Control — Router API
==============================
POST /router/select      → model selection decision
GET  /router/stats       → routing stats from DB
GET  /api/router/stats   → Atlas-exposed stats endpoint
"""

from fastapi import APIRouter

from app.database.async_helpers import run_in_thread
from app.database.init import get_connection
from app.models.schemas import (
    RouterSelectRequest,
    RouterStatsResponse,
    RouterStatsRow,
    RoutingDecision,
)
from app.router.adaptive import get_router

router = APIRouter(tags=["router"])


# ---------------------------------------------------------------------------
# Sync helpers
# ---------------------------------------------------------------------------

def _select_sync(req: RouterSelectRequest) -> RoutingDecision:
    r = get_router()
    return r.select(
        task_type=req.task_type,
        retry_count=req.retry_count,
        force_tier=req.force_tier,
        force_class=req.force_class,
    )


def _get_stats_sync() -> RouterStatsResponse:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, model_id, task_type, average_score, average_retries,
                   success_rate, sample_size, last_updated
            FROM routing_stats
            ORDER BY last_updated DESC
            """
        ).fetchall()
        stat_rows = [
            RouterStatsRow(
                model_id=r["model_id"],
                task_type=r["task_type"],
                average_score=r["average_score"],
                average_retries=r["average_retries"],
                success_rate=r["success_rate"],
                sample_size=r["sample_size"],
                last_updated=r["last_updated"],
            )
            for r in rows
        ]
        return RouterStatsResponse(rows=stat_rows, total=len(stat_rows))
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/router/select", response_model=RoutingDecision)
async def router_select(req: RouterSelectRequest) -> RoutingDecision:
    """Select the optimal model capability class and context tier for a task type."""
    return await run_in_thread(_select_sync, req)


@router.get("/router/stats", response_model=RouterStatsResponse)
async def router_stats() -> RouterStatsResponse:
    """Routing performance stats from routing_stats table."""
    return await run_in_thread(_get_stats_sync)


# ---------------------------------------------------------------------------
# Atlas-exposed endpoint
# GET /api/router/stats  (same data, Atlas-facing path)
# ---------------------------------------------------------------------------

@router.get("/api/router/stats", response_model=RouterStatsResponse)
async def atlas_router_stats() -> RouterStatsResponse:
    """
    Atlas-exposed router stats endpoint.
    Read-only summary of model routing performance.
    """
    return await run_in_thread(_get_stats_sync)
