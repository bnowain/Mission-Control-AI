"""
Mission Control — Backfill API (Phase 4)
==========================================
POST /backfill — run or simulate a backfill for a given pipeline
"""

from __future__ import annotations

from fastapi import APIRouter

from app.database.async_helpers import run_in_thread
from app.models.schemas import BackfillRequest, BackfillResponse, BackfillArtifactInfo
from app.processing.backfill import run_backfill

router = APIRouter(prefix="/backfill", tags=["backfill"])


@router.post("", response_model=BackfillResponse)
async def trigger_backfill(req: BackfillRequest):
    """
    Find and enqueue backfill jobs for artifacts processed with an outdated
    pipeline version. If simulate=True, returns the plan without enqueuing.
    """
    result = await run_in_thread(run_backfill, req.pipeline_name, simulate=req.simulate)
    return BackfillResponse(
        pipeline_name=result["pipeline_name"],
        eligible_count=result["eligible_count"],
        jobs_enqueued=result["jobs_enqueued"],
        simulated=result["simulated"],
        artifacts=[
            BackfillArtifactInfo(
                id=a["artifact_id"],
                current_version=a.get("current_version"),
                target_version=a["target_version"],
            )
            for a in result["artifacts"]
        ],
    )
