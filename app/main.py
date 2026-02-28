"""
Mission Control — FastAPI Application Entry Point
==================================================
Start with:
    uvicorn app.main:app --host 0.0.0.0 --port 8860 --reload

Port 8860 is registered in root CLAUDE.md port registry.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.health import router as health_router
from app.api.system import router as system_router
from app.api.sql import router as sql_router
from app.api.tasks import router as tasks_router
from app.api.codex import router as codex_router
from app.api.router_api import router as router_api_router
from app.api.models_api import router as models_router
from app.api.telemetry import router as telemetry_router
from app.api.plans import router as plans_router
from app.api.context import router as context_router
from app.api.validate_api import router as validate_router
from app.api.websocket import router as ws_router
from app.api.instructions import router as instructions_router
from app.api.artifacts import router as artifacts_router
from app.api.workers import router as workers_router
from app.api.backfill import router as backfill_router
from app.api.events_api import router as events_router
from app.api.rag import router as rag_router
from app.api.metrics import router as metrics_router
from app.api.governance import router as governance_router
from app.core.exceptions import MissionControlError
from app.core.logging import configure_logging, get_logger
from app.database.init import DB_PATH, init_db, run_migrations

log = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    configure_logging()
    log.info("Mission Control starting", port=8860)

    # Ensure DB is initialised and migrations are current
    init_db(DB_PATH)
    run_migrations(DB_PATH)

    log.info("Mission Control ready", port=8860)
    yield
    log.info("Mission Control shutting down")


app = FastAPI(
    title="Mission Control",
    description="Adaptive AI Execution Framework",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten in Phase 7
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Exception handler ────────────────────────────────────────────────────────

@app.exception_handler(MissionControlError)
async def mission_control_error_handler(
    request: Request, exc: MissionControlError
) -> JSONResponse:
    """
    Map MissionControlError subclasses to HTTP status codes.
    Error shape: {"error": "...", "detail": "..."} per master_codex.md §3.7.
    """
    from app.core.exceptions import (
        FatalError,
        MaxLoopsExceeded,
        MaxReplansExceeded,
        MaxRetriesExceeded,
        ModelUnavailableError,
        ContextEscalationRequired,
        CodexError,
        ValidationError,
    )

    status_map = {
        FatalError: 500,
        MaxLoopsExceeded: 422,
        MaxReplansExceeded: 422,
        MaxRetriesExceeded: 422,
        ModelUnavailableError: 503,
        ContextEscalationRequired: 422,
        CodexError: 500,
        ValidationError: 422,
    }

    status_code = status_map.get(type(exc), 500)
    error_name = type(exc).__name__

    log.warning(
        "MissionControlError raised",
        error_type=error_name,
        status_code=status_code,
        detail=str(exc),
        path=str(request.url),
    )

    return JSONResponse(
        status_code=status_code,
        content={"error": error_name, "detail": str(exc)},
    )


# ── Routers ──────────────────────────────────────────────────────────────────

app.include_router(health_router)          # GET /api/health
app.include_router(system_router)          # GET /system/status, /system/hardware
app.include_router(sql_router)             # POST /sql/query
app.include_router(tasks_router)           # POST /tasks, GET/POST /tasks/{id}/*
app.include_router(codex_router)           # POST /codex/*, GET /codex/stats, GET /api/codex/search
app.include_router(router_api_router)      # POST /router/select, GET /router/stats, GET /api/router/stats
app.include_router(models_router)          # GET /models, POST /models/run, POST /models/benchmark
app.include_router(telemetry_router)       # GET /telemetry/*
app.include_router(plans_router)           # POST /plans/* (stubs)
app.include_router(context_router)         # POST /context/* (stubs)
app.include_router(validate_router)        # POST /validate, POST /runs/{id}/replay (stubs)
app.include_router(ws_router)              # WS /ws/execution
app.include_router(instructions_router)    # POST/GET /instructions/*
app.include_router(artifacts_router)       # POST/GET /artifacts/*
app.include_router(workers_router)         # GET /workers/*
app.include_router(backfill_router)        # POST /backfill
app.include_router(events_router)          # GET/POST /events/*
app.include_router(rag_router)             # POST/GET/DELETE /rag/*, GET /api/rag/search
app.include_router(metrics_router)         # GET /metrics
app.include_router(governance_router)      # GET /audit, /feature-flags, /prompt-registry, /overrides/*, /lineage/*


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8860, reload=True)
