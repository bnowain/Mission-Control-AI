"""
Mission Control — Model API
==============================
GET  /models            → list registered models from DB
POST /models/run        → direct model call via router
POST /models/benchmark  → run benchmark_model() for a model
"""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException

from app.database.async_helpers import run_in_thread
from app.database.init import get_connection
from app.models.executor import _extract_thinking
from app.models.schemas import (
    Model,
    ModelBenchmarkRequest,
    ModelBenchmarkResponse,
    ModelRunRequest,
    ModelRunResponse,
)
from app.router.adaptive import get_router
from app.router.hardware_profiler import benchmark_model

router = APIRouter(tags=["models"])


# ---------------------------------------------------------------------------
# Sync helpers
# ---------------------------------------------------------------------------

def _list_models_sync() -> list[Model]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, display_name, provider, capability_class, quant, "
            "max_context, benchmark_tokens_per_sec, deprecated, created_at "
            "FROM models ORDER BY created_at DESC"
        ).fetchall()
        from app.models.schemas import CapabilityClass
        from datetime import datetime
        result = []
        for r in rows:
            result.append(Model(
                id=r["id"],
                display_name=r["display_name"],
                provider=r["provider"],
                capability_class=CapabilityClass(r["capability_class"]),
                quant=r["quant"],
                max_context=r["max_context"],
                benchmark_tokens_per_sec=r["benchmark_tokens_per_sec"],
                deprecated=bool(r["deprecated"]),
                created_at=datetime.fromisoformat(r["created_at"]),
            ))
        return result
    finally:
        conn.close()


def _run_model_sync(req: ModelRunRequest) -> ModelRunResponse:
    r = get_router()
    from app.models.schemas import ContextTier, RoutingDecision
    decision = RoutingDecision(
        # context_size is divided by 4 in complete() to get the output token budget,
        # so multiply by 4 here to ensure the LLM receives exactly req.max_tokens.
        selected_model=req.model_id,
        context_size=req.max_tokens * 4,
        context_tier=ContextTier.EXECUTION,
        temperature=req.temperature,
        routing_reason="direct /models/run call",
    )
    start = time.perf_counter()
    response = r.complete(decision, req.messages)
    elapsed_ms = int((time.perf_counter() - start) * 1000)

    text = ""
    thinking_text = None
    tokens_in = None
    tokens_generated = None
    if hasattr(response, "choices") and response.choices:
        msg = response.choices[0].message
        raw = msg.content or ""
        # DeepSeek-R1 and similar models put chain-of-thought in reasoning_content;
        # message.content may be empty when all output is in reasoning_content.
        if hasattr(msg, "reasoning_content") and msg.reasoning_content:
            thinking_text = msg.reasoning_content
        clean, think_block = _extract_thinking(raw)
        if think_block:
            thinking_text = (thinking_text + "\n\n" + think_block) if thinking_text else think_block
            raw = clean
        text = raw
    if hasattr(response, "usage") and response.usage:
        tokens_in = getattr(response.usage, "prompt_tokens", None)
        tokens_generated = getattr(response.usage, "completion_tokens", None)

    return ModelRunResponse(
        model_id=req.model_id,
        response_text=text,
        thinking_text=thinking_text,
        tokens_in=tokens_in,
        tokens_generated=tokens_generated,
        duration_ms=elapsed_ms,
    )


def _benchmark_model_sync(req: ModelBenchmarkRequest) -> ModelBenchmarkResponse:
    tps = benchmark_model(req.model_id, api_base=req.api_base)
    return ModelBenchmarkResponse(
        model_id=req.model_id,
        tokens_per_second=tps,
        success=tps is not None,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/models", response_model=list[Model])
async def list_models() -> list[Model]:
    """List all registered models from the models table."""
    return await run_in_thread(_list_models_sync)


@router.post("/models/run", response_model=ModelRunResponse)
async def run_model(req: ModelRunRequest) -> ModelRunResponse:
    """Direct model call bypassing the execution loop. Useful for testing."""
    try:
        return await run_in_thread(_run_model_sync, req)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/models/benchmark", response_model=ModelBenchmarkResponse)
async def benchmark_model_endpoint(req: ModelBenchmarkRequest) -> ModelBenchmarkResponse:
    """Run a short benchmark to measure tokens/sec for a model."""
    return await run_in_thread(_benchmark_model_sync, req)
