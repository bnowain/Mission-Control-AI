"""
Mission Control — Validation + Replay API (Phase 3)
=====================================================
POST /validate                  → run validators externally on a response
POST /runs/{id}/replay          → exact replay of an execution run
POST /runs/{id}/replay/stream   → SSE-streamed replay
"""

import asyncio
import json
import threading

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
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


@router.post("/runs/{run_id}/replay/stream")
async def replay_run_stream(run_id: str, request: Request) -> StreamingResponse:
    """
    SSE-streamed replay of a previous execution run.
    Emits: started, model_response, grading, done (or error).
    """
    event_queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def _run_in_bg() -> None:
        try:
            loop.call_soon_threadsafe(
                event_queue.put_nowait,
                ("started", {"run_id": run_id}),
            )
            result = replay_run(run_id)
            loop.call_soon_threadsafe(
                event_queue.put_nowait,
                ("model_response", {"response_preview": result.response_text[:300]}),
            )
            loop.call_soon_threadsafe(
                event_queue.put_nowait,
                ("grading", {
                    "original_score": result.original_score,
                    "new_score":      result.new_score,
                    "original_passed": result.original_passed,
                    "new_passed":     result.new_passed,
                }),
            )
            loop.call_soon_threadsafe(
                event_queue.put_nowait,
                ("done", {
                    "original_run_id":  result.original_run_id,
                    "new_run_id":       result.new_run_id,
                    "model_id":         result.model_id,
                    "context_size":     result.context_size,
                    "original_score":   result.original_score,
                    "new_score":        result.new_score,
                    "original_passed":  result.original_passed,
                    "new_passed":       result.new_passed,
                    "task_type":        result.task_type,
                    "response_text":    result.response_text,
                    "duration_ms":      result.duration_ms,
                }),
            )
        except ValueError as exc:
            loop.call_soon_threadsafe(
                event_queue.put_nowait,
                ("error", {"content": str(exc), "status_code": 404}),
            )
        except Exception as exc:
            loop.call_soon_threadsafe(
                event_queue.put_nowait,
                ("error", {"content": str(exc)}),
            )
        finally:
            loop.call_soon_threadsafe(event_queue.put_nowait, None)  # sentinel

    thread = threading.Thread(target=_run_in_bg, daemon=True)
    thread.start()

    def _sse(event_type: str, data: dict) -> str:
        return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

    async def _generate():
        try:
            while True:
                if await request.is_disconnected():
                    yield _sse("cancelled", {"content": "Client disconnected."})
                    break
                try:
                    item = await asyncio.wait_for(event_queue.get(), timeout=5.0)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                if item is None:
                    break
                event_type, data = item
                yield _sse(event_type, data)
                if event_type in ("done", "error", "cancelled"):
                    break
        except Exception:
            pass

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
