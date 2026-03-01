"""
Mission Control — Planner SSE API
===================================
Streaming Server-Sent Events endpoints for interactive planning sessions.

Endpoints:
    POST /planner/claude   — Claude Code subprocess planning (claude -p --verbose)
    POST /planner/local    — Local reasoning model planning (LiteLLM stream)
    POST /planner/cancel   — Cancel a running session
    GET  /planner/status   — Check if a session is active

SSE event format:
    event: thinking
    data: {"content": "...", "timestamp": 1234567890.0}

    event: output
    data: {"content": "...", "timestamp": 1234567890.0}

    event: tool_use
    data: {"tool": "Read", "target": "...", "timestamp": 1234567890.0}

    event: done
    data: {"response_text": "...", "thinking_text": "...", "duration_ms": 123, "model_used": "claude"}

    event: error
    data: {"content": "...", "timestamp": 1234567890.0}
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.logging import get_logger

log = get_logger("planner_api")

router = APIRouter(prefix="/planner", tags=["planner"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class ClaudePlanRequest(BaseModel):
    prompt: str
    project_id: Optional[str] = None
    timeout_s: int = 300


class LocalPlanRequest(BaseModel):
    prompt: str
    project_id: Optional[str] = None
    model_class: str = "reasoning_model"
    timeout_s: int = 300


class CancelRequest(BaseModel):
    session_id: str


# ---------------------------------------------------------------------------
# Session registry — one active session at a time per process
# ---------------------------------------------------------------------------

_active_session_lock = threading.Lock()
_active_session_id: Optional[str] = None
_active_cancel_event: Optional[threading.Event] = None
_active_provider = None   # ClaudeCodeProvider instance for claude mode


def _register_session(session_id: str, cancel_event: threading.Event, provider=None) -> None:
    global _active_session_id, _active_cancel_event, _active_provider
    with _active_session_lock:
        _active_session_id = session_id
        _active_cancel_event = cancel_event
        _active_provider = provider


def _clear_session() -> None:
    global _active_session_id, _active_cancel_event, _active_provider
    with _active_session_lock:
        _active_session_id = None
        _active_cancel_event = None
        _active_provider = None


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------

def _sse_line(event_type: str, data: dict) -> str:
    """Format a single SSE event block."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def _ping() -> str:
    """SSE comment ping to keep connection alive."""
    return ": ping\n\n"


# ---------------------------------------------------------------------------
# POST /planner/claude
# ---------------------------------------------------------------------------

@router.post("/claude")
async def plan_claude(request: Request, body: ClaudePlanRequest) -> StreamingResponse:
    """
    Stream a Claude Code planning session via SSE.
    Spawns `claude -p --verbose` in a thread and forwards events.
    """
    from app.models.claude_code_provider import ClaudeCodeProvider, PlanEvent

    session_id = str(time.time())
    cancel_event = threading.Event()
    provider = ClaudeCodeProvider(timeout_s=body.timeout_s)
    _register_session(session_id, cancel_event, provider)

    # Queue for thread → async generator communication
    event_queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def _on_event(ev: PlanEvent) -> None:
        """Called from the planner thread; puts events onto the asyncio queue."""
        loop.call_soon_threadsafe(event_queue.put_nowait, ev)

    def _run_in_thread() -> None:
        from app.models.planner import plan_with_claude
        try:
            plan_with_claude(
                prompt=body.prompt,
                on_event=_on_event,
                timeout_s=body.timeout_s,
            )
        except Exception as exc:
            from app.models.claude_code_provider import PlanEvent as PE
            loop.call_soon_threadsafe(
                event_queue.put_nowait,
                PE(event_type="error", content=str(exc)),
            )
        finally:
            # Signal generator that we're done
            loop.call_soon_threadsafe(event_queue.put_nowait, None)

    thread = threading.Thread(target=_run_in_thread, daemon=True)
    thread.start()

    async def _generate():
        start = time.perf_counter()
        output_parts: list[str] = []
        thinking_parts: list[str] = []

        try:
            while True:
                # Check client disconnect
                if await request.is_disconnected():
                    cancel_event.set()
                    provider.cancel()
                    yield _sse_line("cancelled", {"content": "Client disconnected."})
                    break

                try:
                    ev = await asyncio.wait_for(event_queue.get(), timeout=5.0)
                except asyncio.TimeoutError:
                    yield _ping()
                    continue

                if ev is None:
                    # Thread finished
                    break

                if ev.event_type == "output":
                    output_parts.append(ev.content)
                    yield _sse_line("output", {
                        "content": ev.content,
                        "timestamp": ev.timestamp,
                    })

                elif ev.event_type == "thinking":
                    thinking_parts.append(ev.content)
                    yield _sse_line("thinking", {
                        "content": ev.content,
                        "timestamp": ev.timestamp,
                    })

                elif ev.event_type == "tool_use":
                    # Parse "Read src/main.py" style content
                    parts = ev.content.split(None, 1)
                    tool = parts[0] if parts else ev.content
                    target = parts[1] if len(parts) > 1 else ""
                    yield _sse_line("tool_use", {
                        "tool": tool,
                        "target": target,
                        "timestamp": ev.timestamp,
                    })

                elif ev.event_type == "file_diff":
                    yield _sse_line("file_diff", {
                        "content": ev.content,
                        "timestamp": ev.timestamp,
                    })

                elif ev.event_type == "error":
                    yield _sse_line("error", {
                        "content": ev.content,
                        "timestamp": ev.timestamp,
                    })

                elif ev.event_type in ("done", "cancelled"):
                    elapsed_ms = int((time.perf_counter() - start) * 1000)
                    yield _sse_line("done", {
                        "response_text": "\n".join(output_parts),
                        "thinking_text": "\n\n".join(thinking_parts) or None,
                        "duration_ms": elapsed_ms,
                        "model_used": "claude",
                        "cancelled": ev.event_type == "cancelled",
                    })
                    break

        finally:
            _clear_session()

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# POST /planner/local
# ---------------------------------------------------------------------------

@router.post("/local")
async def plan_local(request: Request, body: LocalPlanRequest) -> StreamingResponse:
    """
    Stream a local reasoning model planning session via SSE.
    Uses LiteLLM with stream=True; detects <think> blocks in real-time.
    """
    from app.models.claude_code_provider import PlanEvent

    session_id = str(time.time())
    cancel_event = threading.Event()
    _register_session(session_id, cancel_event)

    event_queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def _on_event(ev: PlanEvent) -> None:
        loop.call_soon_threadsafe(event_queue.put_nowait, ev)

    def _run_in_thread() -> None:
        from app.models.planner import plan_with_local
        try:
            plan_with_local(
                prompt=body.prompt,
                on_event=_on_event,
                model_class=body.model_class,
                timeout_s=body.timeout_s,
            )
        except Exception as exc:
            loop.call_soon_threadsafe(
                event_queue.put_nowait,
                PlanEvent(event_type="error", content=str(exc)),
            )
        finally:
            loop.call_soon_threadsafe(event_queue.put_nowait, None)

    thread = threading.Thread(target=_run_in_thread, daemon=True)
    thread.start()

    async def _generate():
        start = time.perf_counter()
        output_parts: list[str] = []
        thinking_parts: list[str] = []
        model_used = body.model_class

        try:
            while True:
                if await request.is_disconnected():
                    cancel_event.set()
                    yield _sse_line("cancelled", {"content": "Client disconnected."})
                    break

                try:
                    ev = await asyncio.wait_for(event_queue.get(), timeout=5.0)
                except asyncio.TimeoutError:
                    yield _ping()
                    continue

                if ev is None:
                    break

                if ev.event_type == "output":
                    output_parts.append(ev.content)
                    yield _sse_line("output", {
                        "content": ev.content,
                        "timestamp": ev.timestamp,
                    })

                elif ev.event_type == "thinking":
                    thinking_parts.append(ev.content)
                    yield _sse_line("thinking", {
                        "content": ev.content,
                        "timestamp": ev.timestamp,
                    })

                elif ev.event_type == "error":
                    yield _sse_line("error", {
                        "content": ev.content,
                        "timestamp": ev.timestamp,
                    })

                elif ev.event_type in ("done", "cancelled"):
                    elapsed_ms = int((time.perf_counter() - start) * 1000)
                    yield _sse_line("done", {
                        "response_text": "".join(output_parts),
                        "thinking_text": "".join(thinking_parts) or None,
                        "duration_ms": elapsed_ms,
                        "model_used": model_used,
                        "cancelled": ev.event_type == "cancelled",
                    })
                    break

        finally:
            _clear_session()

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# POST /planner/cancel
# ---------------------------------------------------------------------------

@router.post("/cancel")
async def cancel_session(body: CancelRequest):
    """Cancel the currently active planning session."""
    with _active_session_lock:
        session_id = _active_session_id
        cancel_ev = _active_cancel_event
        provider = _active_provider

    if session_id is None:
        return {"cancelled": False, "reason": "No active session"}

    if cancel_ev:
        cancel_ev.set()
    if provider:
        provider.cancel()

    return {"cancelled": True, "session_id": session_id}


# ---------------------------------------------------------------------------
# GET /planner/status
# ---------------------------------------------------------------------------

@router.get("/status")
async def session_status():
    """Return whether a planning session is currently active."""
    with _active_session_lock:
        active = _active_session_id is not None
        session_id = _active_session_id

    return {
        "active": active,
        "session_id": session_id,
    }
