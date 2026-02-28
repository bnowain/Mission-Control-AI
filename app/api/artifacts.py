"""
Mission Control — Artifacts API (Phase 4)
==========================================
POST /artifacts              — ingest new artifact (dedup by source_hash)
GET  /artifacts              — paginated list
GET  /artifacts/{id}         — single artifact
GET  /artifacts/{id}/export  — 3-layer canonical export
POST /artifacts/{id}/state   — state machine transition
POST /artifacts/{id}/process — enqueue processing job
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.database.async_helpers import run_in_thread
from app.models.schemas import (
    ArtifactCreateRequest,
    ArtifactExportResponse,
    ArtifactListResponse,
    ArtifactResponse,
    ArtifactState,
    ArtifactStateTransitionRequest,
    ProcessArtifactRequest,
)
from app.processing.registry import (
    ArtifactNotFoundError,
    InvalidStateTransitionError,
    create_artifact,
    export_artifact,
    get_artifact,
    list_artifacts,
    transition_artifact,
)
from app.processing.worker import enqueue_job

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


def _row_to_response(row: dict) -> ArtifactResponse:
    return ArtifactResponse(
        id=row["id"],
        artifact_version=row.get("artifact_version", 1),
        pipeline_version=row.get("pipeline_version"),
        processing_state=ArtifactState(row["processing_state"]),
        source_type=row.get("source_type"),
        source_hash=row.get("source_hash"),
        file_path=row.get("file_path"),
        file_size_bytes=row.get("file_size_bytes"),
        mime_type=row.get("mime_type"),
        page_url=row.get("page_url"),
        ingest_at=str(row.get("ingest_at", "")),
    )


# ── POST /artifacts ──────────────────────────────────────────────────────────

@router.post("", status_code=201, response_model=ArtifactResponse)
async def ingest_artifact(req: ArtifactCreateRequest):
    """Ingest a new artifact. Deduplicates by source_hash."""
    row = await run_in_thread(
        create_artifact,
        source_type=req.source_type,
        source_hash=req.source_hash,
        file_path=req.file_path,
        file_size_bytes=req.file_size_bytes,
        mime_type=req.mime_type,
        page_url=req.page_url,
        pipeline_version=req.pipeline_version,
    )
    return _row_to_response(row)


# ── GET /artifacts ───────────────────────────────────────────────────────────

@router.get("", response_model=ArtifactListResponse)
async def get_artifacts(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    processing_state: Optional[str] = Query(default=None),
    source_type: Optional[str] = Query(default=None),
):
    """Paginated list of artifacts with optional filters."""
    rows, total = await run_in_thread(
        list_artifacts,
        limit=limit,
        offset=offset,
        processing_state=processing_state,
        source_type=source_type,
    )
    return ArtifactListResponse(
        artifacts=[_row_to_response(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


# ── GET /artifacts/{id} ──────────────────────────────────────────────────────

@router.get("/{artifact_id}", response_model=ArtifactResponse)
async def get_artifact_by_id(artifact_id: str):
    """Fetch a single artifact by ID."""
    try:
        row = await run_in_thread(get_artifact, artifact_id)
    except ArtifactNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _row_to_response(row)


# ── GET /artifacts/{id}/export ───────────────────────────────────────────────

@router.get("/{artifact_id}/export", response_model=ArtifactExportResponse)
async def export_artifact_layers(artifact_id: str):
    """Return canonical 3-layer export (raw + extracted + analysis)."""
    try:
        result = await run_in_thread(export_artifact, artifact_id)
    except ArtifactNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return ArtifactExportResponse(
        raw=result["raw"],
        extracted=result["extracted"],
        analysis=result["analysis"],
    )


# ── POST /artifacts/{id}/state ───────────────────────────────────────────────

@router.post("/{artifact_id}/state", response_model=ArtifactResponse)
async def transition_state(artifact_id: str, req: ArtifactStateTransitionRequest):
    """
    Apply a state machine transition.
    Returns 409 for invalid transitions.
    Returns 404 if artifact not found.
    """
    try:
        row = await run_in_thread(transition_artifact, artifact_id, req.new_state.value)
    except ArtifactNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except InvalidStateTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return _row_to_response(row)


# ── POST /artifacts/{id}/process ─────────────────────────────────────────────

@router.post("/{artifact_id}/process", status_code=202)
async def process_artifact(artifact_id: str, req: ProcessArtifactRequest):
    """Enqueue a processing job for an artifact."""
    try:
        await run_in_thread(get_artifact, artifact_id)
    except ArtifactNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    job = await run_in_thread(
        enqueue_job,
        req.pipeline_name.value,
        artifact_id=artifact_id,
        priority=req.priority,
        payload=req.payload,
    )
    return {"job_id": job["id"], "job_status": job["job_status"]}
