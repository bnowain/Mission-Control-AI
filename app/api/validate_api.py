"""
Mission Control — Validation + Replay API (Phase 3)
=====================================================
POST /validate         → run validators externally on a response
POST /runs/{id}/replay → exact replay of an execution run
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.exceptions import FatalError
from app.core.replay import replay_run
from app.database.async_helpers import run_in_thread
from app.grading.validators import ValidationResult, run_validators
from app.models.schemas import ReplayResponse

router = APIRouter(tags=["validation"])


# ---------------------------------------------------------------------------
# Validate request model
# ---------------------------------------------------------------------------

class ValidateRequest(BaseModel):
    response_text: str
    task_type: str = "generic"
    working_dir: str = None


class ValidateResponse(BaseModel):
    compile_success: bool
    tests_passed: bool
    lint_passed: bool
    runtime_success: bool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/validate", response_model=ValidateResponse)
async def validate(req: ValidateRequest) -> ValidateResponse:
    """
    Run the deterministic validator suite against a response text.
    Phase 3: validators remain stubs (all pass); Phase 4 replaces with real checks.
    """
    def _run() -> ValidationResult:
        return run_validators(
            response_text=req.response_text,
            task_type=req.task_type,
            working_dir=req.working_dir,
        )

    result = await run_in_thread(_run)
    return ValidateResponse(
        compile_success=result.compile_success,
        tests_passed=result.tests_passed,
        lint_passed=result.lint_passed,
        runtime_success=result.runtime_success,
    )


@router.post("/runs/{run_id}/replay", response_model=ReplayResponse)
async def replay_run_endpoint(run_id: str) -> ReplayResponse:
    """
    Exact replay of a previous execution run.
    Uses the same model, context size, temperature, and prompt from the original log.
    """
    def _replay() -> ReplayResponse:
        try:
            return replay_run(run_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FatalError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return await run_in_thread(_replay)
