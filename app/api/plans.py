"""
Mission Control — Plans API (Phase 3 — Full Implementation)
=============================================================
POST /plans                  → create plan DAG
GET  /plans/{id}             → fetch plan with phases + steps
POST /plans/{id}/execute     → advance the plan (run next step)
POST /plans/{id}/replan      → trigger replan cycle
GET  /plans/{id}/diff        → return plan_diff_history
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.core.plan_dag import (
    PlanEngine,
    complete_step,
    create_plan,
    execute_next_step,
    fail_step,
    get_plan,
    replan,
)
from app.database.async_helpers import run_in_thread
from app.models.schemas import (
    PlanCreate,
    PlanResponse,
    PlanStepResponse,
    ReplanRequest,
)

router = APIRouter(prefix="/plans", tags=["plans"])

_engine = PlanEngine()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=PlanResponse, status_code=201)
async def create_plan_endpoint(req: PlanCreate) -> PlanResponse:
    """
    Create a new plan DAG with phases and steps.
    Returns the full plan including all phase/step IDs.
    """
    return await run_in_thread(create_plan, req)


@router.get("/{plan_id}", response_model=PlanResponse)
async def get_plan_endpoint(plan_id: str) -> PlanResponse:
    """Fetch a plan with all phases and steps."""
    plan = await run_in_thread(get_plan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Plan '{plan_id}' not found.")
    return plan


@router.post("/{plan_id}/execute", response_model=PlanStepResponse)
async def execute_plan_step(plan_id: str) -> PlanStepResponse:
    """
    Advance the plan by marking the next runnable step as 'running'.
    Returns the step to be executed, or 404 if no runnable step exists.

    The caller is responsible for:
    1. Using the returned step.step_prompt to run a task
    2. Calling POST /plans/{plan_id}/steps/{step_id}/complete or /fail
    """
    plan = await run_in_thread(get_plan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Plan '{plan_id}' not found.")

    step = await run_in_thread(execute_next_step, plan_id)
    if step is None:
        # Check if plan is complete
        plan = await run_in_thread(get_plan, plan_id)
        if plan and plan.plan_status.value == "completed":
            raise HTTPException(status_code=200, detail="Plan is already complete.")
        raise HTTPException(
            status_code=409,
            detail="No runnable steps available. All steps may be blocked or the plan is complete.",
        )
    return step


@router.post("/{plan_id}/replan", response_model=PlanResponse)
async def replan_endpoint(plan_id: str, req: ReplanRequest) -> PlanResponse:
    """
    Trigger a replan cycle: increments plan_version, resets failed steps,
    optionally adds new phases.
    """
    plan = await run_in_thread(get_plan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Plan '{plan_id}' not found.")

    return await run_in_thread(replan, plan_id, req.reason, req.new_phases)


@router.get("/{plan_id}/diff")
async def plan_diff(plan_id: str) -> dict:
    """Return the plan_diff_history — all replan events with reasons."""
    plan = await run_in_thread(get_plan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Plan '{plan_id}' not found.")

    return {
        "plan_id": plan_id,
        "plan_version": plan.plan_version,
        "diff_history": plan.plan_diff_history,
    }


# ---------------------------------------------------------------------------
# Step completion / failure (sub-routes)
# ---------------------------------------------------------------------------

@router.post("/{plan_id}/steps/{step_id}/complete")
async def complete_step_endpoint(plan_id: str, step_id: str, result_summary: str = "") -> dict:
    """Mark a step as completed."""
    await run_in_thread(complete_step, step_id, result_summary or None)
    return {"step_id": step_id, "step_status": "completed"}


@router.post("/{plan_id}/steps/{step_id}/fail")
async def fail_step_endpoint(plan_id: str, step_id: str, reason: str = "") -> dict:
    """Mark a step as failed."""
    await run_in_thread(fail_step, step_id, reason or None)
    return {"step_id": step_id, "step_status": "failed"}
