"""
Mission Control — Artifact Registry (Phase 4)
=============================================
Three-layer artifact lifecycle management:
  Layer 1: artifacts_raw       (ingest + state machine)
  Layer 2: artifacts_extracted (pipeline extraction results)
  Layer 3: artifacts_analysis  (LLM analysis outputs)

State machine transitions:
  RECEIVED → PROCESSING → PROCESSED → AVAILABLE_FOR_EXPORT → EXPORTED → ARCHIVED
  Rollbacks allowed: PROCESSING → RECEIVED, PROCESSED → PROCESSING,
                     AVAILABLE_FOR_EXPORT → PROCESSING

Pattern: sync business logic + run_in_thread() wrappers (Phases 1-3 pattern).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.core.exceptions import MissionControlError
from app.core.logging import get_logger
from app.database.init import get_connection
from app.models.schemas import ArtifactState

log = get_logger("processing.registry")


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[str, list[str]] = {
    ArtifactState.RECEIVED.value:             [ArtifactState.PROCESSING.value],
    ArtifactState.PROCESSING.value:           [ArtifactState.PROCESSED.value, ArtifactState.RECEIVED.value],
    ArtifactState.PROCESSED.value:            [ArtifactState.AVAILABLE_FOR_EXPORT.value, ArtifactState.PROCESSING.value],
    ArtifactState.AVAILABLE_FOR_EXPORT.value: [ArtifactState.EXPORTED.value, ArtifactState.PROCESSING.value],
    ArtifactState.EXPORTED.value:             [ArtifactState.ARCHIVED.value],
    ArtifactState.ARCHIVED.value:             [],
}


class InvalidStateTransitionError(MissionControlError):
    """Raised when a requested state transition is not in VALID_TRANSITIONS."""


class ArtifactNotFoundError(MissionControlError):
    """Raised when an artifact_id does not exist in artifacts_raw."""


# ---------------------------------------------------------------------------
# Registry class
# ---------------------------------------------------------------------------

class ArtifactRegistry:
    """
    Core artifact CRUD + state machine logic.
    All methods are synchronous; wrap with run_in_thread() at API layer.
    """

    # ── Create ──────────────────────────────────────────────────────────────

    def create(
        self,
        source_type: Optional[str] = None,
        source_hash: Optional[str] = None,
        file_path: Optional[str] = None,
        file_size_bytes: Optional[int] = None,
        mime_type: Optional[str] = None,
        page_url: Optional[str] = None,
        pipeline_version: Optional[str] = None,
    ) -> dict:
        """
        Insert a new artifact or return an existing one (dedup by source_hash).
        Returns the artifact row dict.
        """
        # Dedup by source_hash if provided
        if source_hash:
            conn = get_connection()
            try:
                existing = conn.execute(
                    "SELECT * FROM artifacts_raw WHERE source_hash = ?",
                    (source_hash,),
                ).fetchone()
                if existing:
                    log.info("Artifact dedup hit", source_hash=source_hash, artifact_id=existing["id"])
                    return dict(existing)
            finally:
                conn.close()

        artifact_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO artifacts_raw
                    (id, artifact_version, pipeline_version, processing_state,
                     source_type, source_hash, file_path, file_size_bytes,
                     mime_type, page_url, ingest_at)
                VALUES (?, 1, ?, 'RECEIVED', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    pipeline_version,
                    source_type,
                    source_hash,
                    file_path,
                    file_size_bytes,
                    mime_type,
                    page_url,
                    now,
                ),
            )
            conn.commit()

            row = conn.execute(
                "SELECT * FROM artifacts_raw WHERE id = ?", (artifact_id,)
            ).fetchone()
            log.info("Artifact created", artifact_id=artifact_id, source_type=source_type)
            return dict(row)
        finally:
            conn.close()

    # ── Get ─────────────────────────────────────────────────────────────────

    def get(self, artifact_id: str) -> dict:
        """Fetch a single artifact. Raises ArtifactNotFoundError if absent."""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM artifacts_raw WHERE id = ?", (artifact_id,)
            ).fetchone()
            if row is None:
                raise ArtifactNotFoundError(f"Artifact '{artifact_id}' not found")
            return dict(row)
        finally:
            conn.close()

    # ── List ────────────────────────────────────────────────────────────────

    def list_artifacts(
        self,
        limit: int = 20,
        offset: int = 0,
        processing_state: Optional[str] = None,
        source_type: Optional[str] = None,
    ) -> tuple[list[dict], int]:
        """
        Return (rows, total_count) with optional filters.
        """
        filters = []
        params: list = []

        if processing_state:
            filters.append("processing_state = ?")
            params.append(processing_state)
        if source_type:
            filters.append("source_type = ?")
            params.append(source_type)

        where = ("WHERE " + " AND ".join(filters)) if filters else ""

        conn = get_connection()
        try:
            total = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM artifacts_raw {where}", params
            ).fetchone()["cnt"]

            rows = conn.execute(
                f"SELECT * FROM artifacts_raw {where} ORDER BY ingest_at DESC LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()
            return [dict(r) for r in rows], total
        finally:
            conn.close()

    # ── State transition ────────────────────────────────────────────────────

    def transition(self, artifact_id: str, new_state: str) -> dict:
        """
        Validate and apply a state transition.
        Raises InvalidStateTransitionError on invalid transitions.
        Raises ArtifactNotFoundError if artifact absent.
        """
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM artifacts_raw WHERE id = ?", (artifact_id,)
            ).fetchone()
            if row is None:
                raise ArtifactNotFoundError(f"Artifact '{artifact_id}' not found")

            current = row["processing_state"]
            allowed = VALID_TRANSITIONS.get(current, [])
            if new_state not in allowed:
                raise InvalidStateTransitionError(
                    f"Cannot transition from {current!r} to {new_state!r}. "
                    f"Allowed: {allowed}"
                )

            conn.execute(
                "UPDATE artifacts_raw SET processing_state = ? WHERE id = ?",
                (new_state, artifact_id),
            )
            conn.commit()

            updated = conn.execute(
                "SELECT * FROM artifacts_raw WHERE id = ?", (artifact_id,)
            ).fetchone()
            log.info(
                "Artifact state transition",
                artifact_id=artifact_id,
                from_state=current,
                to_state=new_state,
            )
            return dict(updated)
        finally:
            conn.close()

    # ── Add extracted (Layer 2) ─────────────────────────────────────────────

    def add_extracted(
        self,
        artifact_id: str,
        pipeline_name: str,
        pipeline_version: str,
        extraction_data: dict,
        confidence_score: Optional[float] = None,
        model_version: Optional[str] = None,
        engine_version: str = "1.0",
        gpu_used: Optional[str] = None,
        processing_ms: Optional[int] = None,
        retry_count: int = 0,
    ) -> dict:
        """Insert a Layer-2 extraction record."""
        # Verify artifact exists
        self.get(artifact_id)

        record_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO artifacts_extracted
                    (id, artifact_id, pipeline_name, pipeline_version, model_version,
                     engine_version, extraction_data, confidence_score, retry_count,
                     gpu_used, processing_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    artifact_id,
                    pipeline_name,
                    pipeline_version,
                    model_version,
                    engine_version,
                    json.dumps(extraction_data),
                    confidence_score,
                    retry_count,
                    gpu_used,
                    processing_ms,
                    now,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM artifacts_extracted WHERE id = ?", (record_id,)
            ).fetchone()
            return dict(row)
        finally:
            conn.close()

    # ── Add analysis (Layer 3) ──────────────────────────────────────────────

    def add_analysis(
        self,
        artifact_id: str,
        summary_text: Optional[str] = None,
        tags: Optional[list[str]] = None,
        reasoning_text: Optional[str] = None,
        validation_score: Optional[float] = None,
        routing_decision: Optional[dict] = None,
        model_id: Optional[str] = None,
        prompt_id: Optional[str] = None,
        prompt_version: Optional[str] = None,
        engine_version: str = "1.0",
        processing_ms: Optional[int] = None,
    ) -> dict:
        """Insert a Layer-3 analysis record."""
        self.get(artifact_id)

        record_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO artifacts_analysis
                    (id, artifact_id, model_id, prompt_id, prompt_version,
                     engine_version, summary_text, tags_json, reasoning_text,
                     validation_score, routing_decision_json, processing_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    artifact_id,
                    model_id,
                    prompt_id,
                    prompt_version,
                    engine_version,
                    summary_text,
                    json.dumps(tags or []),
                    reasoning_text,
                    validation_score,
                    json.dumps(routing_decision or {}),
                    processing_ms,
                    now,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM artifacts_analysis WHERE id = ?", (record_id,)
            ).fetchone()
            return dict(row)
        finally:
            conn.close()

    # ── Export (3-layer) ────────────────────────────────────────────────────

    def export(self, artifact_id: str) -> dict:
        """Return canonical 3-layer JSON for an artifact."""
        raw = self.get(artifact_id)

        conn = get_connection()
        try:
            extracted = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM artifacts_extracted WHERE artifact_id = ? ORDER BY created_at",
                    (artifact_id,),
                ).fetchall()
            ]
            analysis = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM artifacts_analysis WHERE artifact_id = ? ORDER BY created_at",
                    (artifact_id,),
                ).fetchall()
            ]
        finally:
            conn.close()

        return {"raw": raw, "extracted": extracted, "analysis": analysis}


# ---------------------------------------------------------------------------
# Module-level singleton + convenience wrappers
# ---------------------------------------------------------------------------

_registry = ArtifactRegistry()


def create_artifact(**kwargs) -> dict:
    return _registry.create(**kwargs)


def get_artifact(artifact_id: str) -> dict:
    return _registry.get(artifact_id)


def list_artifacts(**kwargs) -> tuple[list[dict], int]:
    return _registry.list_artifacts(**kwargs)


def transition_artifact(artifact_id: str, new_state: str) -> dict:
    return _registry.transition(artifact_id, new_state)


def add_extracted(artifact_id: str, **kwargs) -> dict:
    return _registry.add_extracted(artifact_id, **kwargs)


def add_analysis(artifact_id: str, **kwargs) -> dict:
    return _registry.add_analysis(artifact_id, **kwargs)


def export_artifact(artifact_id: str) -> dict:
    return _registry.export(artifact_id)
