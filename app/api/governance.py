"""
Mission Control — Governance API (Phase 8)
===========================================
Endpoints for audit log, feature flags, prompt registry,
human overrides, and data lineage.

GET  /audit                              — query audit log
GET  /feature-flags                      — list all flags
PUT  /feature-flags/{flag_name}          — enable/disable a flag
GET  /prompt-registry                    — list prompt templates
POST /prompt-registry                    — register a new prompt version
GET  /prompt-registry/{name}/versions    — version history for a prompt
GET  /overrides/ocr/{artifact_id}        — OCR corrections for artifact
POST /overrides/ocr/{artifact_id}        — add OCR correction
GET  /overrides/summary/{artifact_id}    — summary corrections for artifact
POST /overrides/summary/{artifact_id}    — add summary correction
GET  /overrides/speaker/{artifact_id}    — speaker overrides for artifact
POST /overrides/speaker/{artifact_id}    — add speaker override
GET  /overrides/tags/{artifact_id}       — tag overrides for artifact
POST /overrides/tags/{artifact_id}       — add tag override
GET  /lineage/{artifact_id}              — data lineage for artifact
POST /lineage                            — record a lineage edge
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ulid import ULID

from app.core.audit import (
    ACTION_FLAG_UPDATED,
    ACTION_LINEAGE_RECORDED,
    ACTION_OVERRIDE_CREATED,
    ACTION_PROMPT_REGISTERED,
    get_audit_log,
    write_audit_log,
)
from app.core.feature_flags import get_all_flags, set_flag
from app.database.async_helpers import run_in_thread
from app.database.init import get_connection

router = APIRouter(tags=["governance"])


# ── Pydantic models ───────────────────────────────────────────────────────────

class AuditLogResponse(BaseModel):
    entries: list[dict[str, Any]]
    total: int
    limit: int
    offset: int


class FeatureFlagUpdate(BaseModel):
    enabled: bool
    rollout_percentage: int = 100
    project_scope: Optional[str] = None


class PromptRegistryCreate(BaseModel):
    name: str
    version: str
    template_text: str


class PromptRegistryResponse(BaseModel):
    id: str
    name: str
    version: str
    template_hash: str
    deprecated: bool
    created_at: str


class OverrideCreate(BaseModel):
    original_value: Optional[str] = None
    corrected_value: Optional[str] = None
    corrected_by: str
    reason: Optional[str] = None
    artifact_version: Optional[int] = None


class SpeakerOverrideCreate(BaseModel):
    segment_index: Optional[int] = None
    original_speaker: Optional[str] = None
    corrected_speaker: Optional[str] = None
    corrected_by: str
    reason: Optional[str] = None


class TagOverrideCreate(BaseModel):
    original_tags: Optional[list[str]] = None
    corrected_tags: Optional[list[str]] = None
    corrected_by: str
    reason: Optional[str] = None


class LineageCreate(BaseModel):
    artifact_id: str
    derived_from_artifact_id: Optional[str] = None
    pipeline_stage: str
    model_version: Optional[str] = None


# ── Audit log ─────────────────────────────────────────────────────────────────

@router.get("/audit", response_model=AuditLogResponse)
async def query_audit_log(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    action_type: Optional[str] = Query(default=None),
    artifact_id: Optional[str] = Query(default=None),
    task_id: Optional[str] = Query(default=None),
):
    """Query the immutable audit log with optional filters."""
    entries, total = await run_in_thread(
        get_audit_log,
        limit=limit,
        offset=offset,
        action_type=action_type,
        artifact_id=artifact_id,
        task_id=task_id,
    )
    return AuditLogResponse(entries=entries, total=total, limit=limit, offset=offset)


# ── Feature flags ─────────────────────────────────────────────────────────────

@router.get("/feature-flags")
async def list_feature_flags():
    """List all feature flags and their current state."""
    flags = await run_in_thread(get_all_flags)
    return {"flags": flags, "total": len(flags)}


@router.put("/feature-flags/{flag_name}")
async def update_feature_flag(flag_name: str, req: FeatureFlagUpdate):
    """Enable or disable a feature flag."""
    await run_in_thread(
        set_flag,
        flag_name,
        req.enabled,
        req.rollout_percentage,
        req.project_scope,
    )
    write_audit_log(
        ACTION_FLAG_UPDATED,
        metadata={"flag_name": flag_name, "enabled": req.enabled},
    )
    return {"flag_name": flag_name, "enabled": req.enabled, "updated": True}


# ── Prompt registry ───────────────────────────────────────────────────────────

def _list_prompts_db(name_filter: Optional[str] = None) -> list[dict]:
    conn = get_connection()
    try:
        if name_filter:
            rows = conn.execute(
                "SELECT id, name, version, template_hash, deprecated, created_at "
                "FROM prompt_registry WHERE name = ? ORDER BY created_at DESC",
                (name_filter,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, name, version, template_hash, deprecated, created_at "
                "FROM prompt_registry ORDER BY name, created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _register_prompt_db(name: str, version: str, template_text: str) -> dict:
    template_hash = hashlib.sha256(template_text.encode("utf-8")).hexdigest()
    record_id = str(__import__("uuid").uuid4())
    conn = get_connection()
    try:
        # Check for duplicate (name, version)
        existing = conn.execute(
            "SELECT id FROM prompt_registry WHERE name = ? AND version = ?",
            (name, version),
        ).fetchone()
        if existing:
            raise ValueError(f"Prompt '{name}' version '{version}' already exists")

        conn.execute(
            """
            INSERT INTO prompt_registry (id, name, version, template_text, template_hash)
            VALUES (?, ?, ?, ?, ?)
            """,
            (record_id, name, version, template_text, template_hash),
        )
        conn.commit()
        return {
            "id": record_id,
            "name": name,
            "version": version,
            "template_hash": template_hash,
            "deprecated": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        conn.close()


@router.get("/prompt-registry")
async def list_prompt_registry(name: Optional[str] = Query(default=None)):
    """List all registered prompt templates. Filter by name to see version history."""
    prompts = await run_in_thread(_list_prompts_db, name)
    return {"prompts": prompts, "total": len(prompts)}


@router.post("/prompt-registry", status_code=201)
async def register_prompt(req: PromptRegistryCreate):
    """Register a new versioned prompt template."""
    try:
        result = await run_in_thread(
            _register_prompt_db, req.name, req.version, req.template_text
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    write_audit_log(
        ACTION_PROMPT_REGISTERED,
        metadata={"name": req.name, "version": req.version},
    )
    return result


@router.get("/prompt-registry/{name}/versions")
async def get_prompt_versions(name: str):
    """Get all versions of a named prompt."""
    prompts = await run_in_thread(_list_prompts_db, name)
    if not prompts:
        raise HTTPException(status_code=404, detail=f"No prompt named '{name}'")
    return {"name": name, "versions": prompts}


# ── Human overrides — OCR ─────────────────────────────────────────────────────

def _get_overrides(table: str, artifact_id: str) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            f"SELECT * FROM {table} WHERE artifact_id = ? ORDER BY timestamp DESC",
            (artifact_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _add_ocr_correction(artifact_id: str, req: OverrideCreate) -> dict:
    record_id = str(ULID())
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO ocr_corrections
                (id, artifact_id, original_value, corrected_value,
                 corrected_by, artifact_version, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (record_id, artifact_id, req.original_value, req.corrected_value,
             req.corrected_by, req.artifact_version, req.reason),
        )
        conn.commit()
        return {"id": record_id, "artifact_id": artifact_id}
    finally:
        conn.close()


@router.get("/overrides/ocr/{artifact_id}")
async def get_ocr_corrections(artifact_id: str):
    rows = await run_in_thread(_get_overrides, "ocr_corrections", artifact_id)
    return {"artifact_id": artifact_id, "corrections": rows, "total": len(rows)}


@router.post("/overrides/ocr/{artifact_id}", status_code=201)
async def add_ocr_correction(artifact_id: str, req: OverrideCreate):
    result = await run_in_thread(_add_ocr_correction, artifact_id, req)
    write_audit_log(
        ACTION_OVERRIDE_CREATED,
        artifact_id=artifact_id,
        metadata={"override_type": "ocr", "corrected_by": req.corrected_by},
    )
    return result


# ── Human overrides — Summary ─────────────────────────────────────────────────

def _add_summary_correction(artifact_id: str, req: OverrideCreate) -> dict:
    record_id = str(ULID())
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO summary_corrections
                (id, artifact_id, original_summary, corrected_summary,
                 corrected_by, reason)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (record_id, artifact_id, req.original_value, req.corrected_value,
             req.corrected_by, req.reason),
        )
        conn.commit()
        return {"id": record_id, "artifact_id": artifact_id}
    finally:
        conn.close()


@router.get("/overrides/summary/{artifact_id}")
async def get_summary_corrections(artifact_id: str):
    rows = await run_in_thread(_get_overrides, "summary_corrections", artifact_id)
    return {"artifact_id": artifact_id, "corrections": rows, "total": len(rows)}


@router.post("/overrides/summary/{artifact_id}", status_code=201)
async def add_summary_correction(artifact_id: str, req: OverrideCreate):
    result = await run_in_thread(_add_summary_correction, artifact_id, req)
    write_audit_log(
        ACTION_OVERRIDE_CREATED,
        artifact_id=artifact_id,
        metadata={"override_type": "summary", "corrected_by": req.corrected_by},
    )
    return result


# ── Human overrides — Speaker ─────────────────────────────────────────────────

def _add_speaker_override(artifact_id: str, req: SpeakerOverrideCreate) -> dict:
    record_id = str(ULID())
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO speaker_resolution_overrides
                (id, artifact_id, segment_index, original_speaker,
                 corrected_speaker, corrected_by, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (record_id, artifact_id, req.segment_index, req.original_speaker,
             req.corrected_speaker, req.corrected_by, req.reason),
        )
        conn.commit()
        return {"id": record_id, "artifact_id": artifact_id}
    finally:
        conn.close()


@router.get("/overrides/speaker/{artifact_id}")
async def get_speaker_overrides(artifact_id: str):
    rows = await run_in_thread(_get_overrides, "speaker_resolution_overrides", artifact_id)
    return {"artifact_id": artifact_id, "overrides": rows, "total": len(rows)}


@router.post("/overrides/speaker/{artifact_id}", status_code=201)
async def add_speaker_override(artifact_id: str, req: SpeakerOverrideCreate):
    result = await run_in_thread(_add_speaker_override, artifact_id, req)
    write_audit_log(
        ACTION_OVERRIDE_CREATED,
        artifact_id=artifact_id,
        metadata={"override_type": "speaker", "corrected_by": req.corrected_by},
    )
    return result


# ── Human overrides — Tags ────────────────────────────────────────────────────

def _add_tag_override(artifact_id: str, req: TagOverrideCreate) -> dict:
    record_id = str(ULID())
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO tag_overrides
                (id, artifact_id, original_tags, corrected_tags, corrected_by, reason)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (record_id, artifact_id,
             json.dumps(req.original_tags) if req.original_tags else None,
             json.dumps(req.corrected_tags) if req.corrected_tags else None,
             req.corrected_by, req.reason),
        )
        conn.commit()
        return {"id": record_id, "artifact_id": artifact_id}
    finally:
        conn.close()


@router.get("/overrides/tags/{artifact_id}")
async def get_tag_overrides(artifact_id: str):
    rows = await run_in_thread(_get_overrides, "tag_overrides", artifact_id)
    return {"artifact_id": artifact_id, "overrides": rows, "total": len(rows)}


@router.post("/overrides/tags/{artifact_id}", status_code=201)
async def add_tag_override(artifact_id: str, req: TagOverrideCreate):
    result = await run_in_thread(_add_tag_override, artifact_id, req)
    write_audit_log(
        ACTION_OVERRIDE_CREATED,
        artifact_id=artifact_id,
        metadata={"override_type": "tags", "corrected_by": req.corrected_by},
    )
    return result


# ── Data lineage ──────────────────────────────────────────────────────────────

def _get_lineage_db(artifact_id: str) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, artifact_id, derived_from_artifact_id,
                   pipeline_stage, model_version, timestamp
            FROM data_lineage
            WHERE artifact_id = ?
            ORDER BY timestamp ASC
            """,
            (artifact_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _record_lineage_db(req: LineageCreate) -> dict:
    record_id = str(ULID())
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO data_lineage
                (id, artifact_id, derived_from_artifact_id, pipeline_stage, model_version)
            VALUES (?, ?, ?, ?, ?)
            """,
            (record_id, req.artifact_id, req.derived_from_artifact_id,
             req.pipeline_stage, req.model_version),
        )
        conn.commit()
        return {"id": record_id, "artifact_id": req.artifact_id}
    finally:
        conn.close()


@router.get("/lineage/{artifact_id}")
async def get_lineage(artifact_id: str):
    """Return data lineage graph for an artifact."""
    rows = await run_in_thread(_get_lineage_db, artifact_id)
    return {"artifact_id": artifact_id, "lineage": rows, "total": len(rows)}


@router.post("/lineage", status_code=201)
async def record_lineage(req: LineageCreate):
    """Record a lineage edge (e.g., Raw → OCR, Chunk → Summary)."""
    result = await run_in_thread(_record_lineage_db, req)
    write_audit_log(
        ACTION_LINEAGE_RECORDED,
        artifact_id=req.artifact_id,
        metadata={"pipeline_stage": req.pipeline_stage},
    )
    return result
