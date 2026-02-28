"""
Mission Control — FastAPI Application Entry Point
==================================================
Start with:
    uvicorn app.main:app --host 0.0.0.0 --port 8860 --reload

Port 8860 is registered in root CLAUDE.md port registry.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
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

# ── Routers ──────────────────────────────────────────────────────────────────
app.include_router(health_router)
# Phase 2: task, plan, router, model, validation, codex, context, telemetry, sql, system routers


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8860, reload=True)
