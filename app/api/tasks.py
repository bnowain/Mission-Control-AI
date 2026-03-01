"""
Mission Control — Task API
============================
POST /tasks             → create task row (ULID + SHA256 signature)
GET  /tasks/{id}        → fetch task
POST /tasks/{id}/execute → run ExecutionLoop in thread pool
POST /tasks/{id}/cancel  → set task_status=cancelled
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from ulid import ULID

from app.core.exceptions import FatalError, MaxLoopsExceeded
from app.core.execution_loop import ExecutionContext, run_task
from app.database.async_helpers import run_in_thread
from app.database.init import get_connection
from app.models.schemas import (
    CapabilityClass,
    ContextTier,
    RoutingDecision,
    TaskCreate,
    TaskExecuteRequest,
    TaskExecuteResponse,
    TaskResponse,
    TaskStatus,
    TaskType,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])


# ---------------------------------------------------------------------------
# Sync helpers
# ---------------------------------------------------------------------------

def _create_task_sync(req: TaskCreate) -> TaskResponse:
    task_id = str(ULID())
    now = datetime.now(timezone.utc).isoformat()

    # SHA256 signature of the task content fingerprint
    sig_content = f"{req.project_id}:{req.task_type}:{req.relevant_files}:{req.constraints}"
    signature = hashlib.sha256(sig_content.encode("utf-8")).hexdigest()

    conn = get_connection()
    try:
        # Auto-create project row if it doesn't exist (avoids FK violation from UI)
        conn.execute(
            "INSERT OR IGNORE INTO projects (id, name, created_at) VALUES (?, ?, ?)",
            (req.project_id, req.project_id, now),
        )
        conn.execute(
            """
            INSERT INTO tasks
                (id, project_id, task_type, signature, task_status, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'pending', ?, ?)
            """,
            (task_id, req.project_id, req.task_type, signature, now, now),
        )
        conn.commit()
    finally:
        conn.close()

    return TaskResponse(
        id=task_id,
        project_id=req.project_id,
        task_type=req.task_type,
        signature=signature,
        task_status=TaskStatus.PENDING,
        created_at=now,
        updated_at=now,
    )


def _get_task_sync(task_id: str) -> Optional[TaskResponse]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, project_id, task_type, signature, task_status, "
            "plan_id, phase_id, step_id, created_at, updated_at "
            "FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            return None
        return TaskResponse(
            id=row["id"],
            project_id=row["project_id"],
            task_type=row["task_type"],
            signature=row["signature"],
            task_status=TaskStatus(row["task_status"]),
            plan_id=row["plan_id"],
            phase_id=row["phase_id"],
            step_id=row["step_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
    finally:
        conn.close()


def _set_task_status_sync(task_id: str, status: TaskStatus) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tasks SET task_status = ?, updated_at = ? WHERE id = ?",
            (status.value, now, task_id),
        )
        conn.commit()
    finally:
        conn.close()


def _execute_task_sync(
    task_id: str,
    task_type: TaskType,
    project_id: str,
    signature: str,
    req: TaskExecuteRequest,
    on_event: Optional[Callable[[str, dict], None]] = None,
) -> TaskExecuteResponse:
    """Run the ExecutionLoop synchronously (called via run_in_thread or directly)."""
    _set_task_status_sync(task_id, TaskStatus.RUNNING)

    messages = [{"role": "user", "content": req.prompt}]

    ctx = ExecutionContext(
        task_id=task_id,
        project_id=project_id,
        task_type=task_type,
        messages=messages,
        signature=signature,
        force_class=req.force_model_class,
        force_tier=req.force_context_tier,
        on_event=on_event,
    )

    start = time.perf_counter()
    try:
        result = run_task(ctx)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        final_status = TaskStatus.COMPLETED if result.succeeded else TaskStatus.FAILED
        _set_task_status_sync(task_id, final_status)

        routing = result.decision or _null_routing()

        return TaskExecuteResponse(
            task_id=task_id,
            task_status=final_status,
            score=result.grading.score,
            passed=result.grading.passed,
            response_text=result.response_text,
            routing_decision=routing,
            duration_ms=elapsed_ms,
            retry_count=result.loop_count - 1,  # retries = total loops - 1
            loop_count=result.loop_count,
            tokens_generated=result.tokens_generated,
            tokens_per_second=result.tokens_per_second,
            thinking_text=result.thinking_text,
            compile_success=result.grading.compile_success,
            tests_passed=result.grading.tests_passed,
            lint_passed=result.grading.lint_passed,
            runtime_success=result.grading.runtime_success,
        )

    except MaxLoopsExceeded as exc:
        _set_task_status_sync(task_id, TaskStatus.FAILED)
        raise HTTPException(
            status_code=422,
            detail=f"Task failed: max loop limit hit after {exc.loop_count} iterations.",
        ) from exc

    except FatalError as exc:
        _set_task_status_sync(task_id, TaskStatus.FAILED)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _null_routing() -> RoutingDecision:
    return RoutingDecision(
        selected_model="unknown",
        context_size=0,
        context_tier=ContextTier.EXECUTION,
        temperature=0.0,
        routing_reason="see execution_logs for routing detail",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=TaskResponse, status_code=201)
async def create_task(req: TaskCreate) -> TaskResponse:
    """Create a new task row. Returns ULID id and SHA256 signature."""
    return await run_in_thread(_create_task_sync, req)


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str) -> TaskResponse:
    """Fetch a task by ULID id."""
    task = await run_in_thread(_get_task_sync, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")
    return task


@router.post("/{task_id}/execute", response_model=TaskExecuteResponse)
async def execute_task(task_id: str, req: TaskExecuteRequest) -> TaskExecuteResponse:
    """
    Execute a task via the full ExecutionLoop (codex inject → model → grade → log).
    Runs synchronously in a thread pool to avoid blocking the event loop.
    """
    task = await run_in_thread(_get_task_sync, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")
    if task.task_status == TaskStatus.RUNNING:
        raise HTTPException(status_code=409, detail="Task is already running.")
    if task.task_status == TaskStatus.CANCELLED:
        raise HTTPException(status_code=409, detail="Task has been cancelled.")

    project_id = req.project_id or task.project_id

    return await run_in_thread(
        _execute_task_sync,
        task_id,
        TaskType(task.task_type),
        project_id,
        task.signature,
        req,
    )


@router.post("/{task_id}/execute/stream")
async def execute_task_stream(
    task_id: str, req: TaskExecuteRequest, request: Request
) -> StreamingResponse:
    """
    Stream task execution events via SSE.
    Emits: started, loop_start, model_response, grading, done, error.
    """
    task = await run_in_thread(_get_task_sync, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")
    if task.task_status == TaskStatus.RUNNING:
        raise HTTPException(status_code=409, detail="Task is already running.")
    if task.task_status == TaskStatus.CANCELLED:
        raise HTTPException(status_code=409, detail="Task has been cancelled.")

    project_id = req.project_id or task.project_id
    task_type  = TaskType(task.task_type)
    signature  = task.signature

    event_queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def _on_event(event_type: str, data: dict) -> None:
        loop.call_soon_threadsafe(event_queue.put_nowait, (event_type, data))

    def _run_in_bg() -> None:
        try:
            result = _execute_task_sync(
                task_id, task_type, project_id, signature, req, on_event=_on_event
            )
            # Convert result to a plain dict for the done event
            done_data = {
                "task_id":          result.task_id,
                "task_status":      result.task_status.value,
                "score":            result.score,
                "passed":           result.passed,
                "response_text":    result.response_text,
                "thinking_text":    result.thinking_text,
                "duration_ms":      result.duration_ms,
                "loop_count":       result.loop_count,
                "retry_count":      result.retry_count,
                "tokens_generated": result.tokens_generated,
                "tokens_per_second": result.tokens_per_second,
                "compile_success":  result.compile_success,
                "tests_passed":     result.tests_passed,
                "lint_passed":      result.lint_passed,
                "runtime_success":  result.runtime_success,
                "model":            result.routing_decision.selected_model,
                "tier":             result.routing_decision.context_tier,
                "context_size":     result.routing_decision.context_size,
                "routing_reason":   result.routing_decision.routing_reason,
            }
            loop.call_soon_threadsafe(event_queue.put_nowait, ("done", done_data))
        except HTTPException as exc:
            loop.call_soon_threadsafe(
                event_queue.put_nowait, ("error", {"content": exc.detail})
            )
        except Exception as exc:
            loop.call_soon_threadsafe(
                event_queue.put_nowait, ("error", {"content": str(exc)})
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


@router.post("/{task_id}/cancel", response_model=TaskResponse)
async def cancel_task(task_id: str) -> TaskResponse:
    """Set task_status to cancelled. No-op if already completed/failed."""
    task = await run_in_thread(_get_task_sync, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")
    if task.task_status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
        raise HTTPException(
            status_code=409,
            detail=f"Task is already {task.task_status.value} — cannot cancel.",
        )
    await run_in_thread(_set_task_status_sync, task_id, TaskStatus.CANCELLED)
    task.task_status = TaskStatus.CANCELLED
    return task
