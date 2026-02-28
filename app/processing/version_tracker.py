"""
Mission Control — Pipeline Version Tracker (Phase 4)
=====================================================
Registers pipeline versions and provides backfill eligibility checks.
Version records are used to detect when artifacts need reprocessing.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from app.core.logging import get_logger
from app.database.init import get_connection

log = get_logger("processing.version_tracker")


class VersionTracker:
    """Manages pipeline_versions table."""

    def register_version(
        self,
        pipeline_name: str,
        engine_version: str,
        model_version: Optional[str] = None,
        prompt_template_version: Optional[str] = None,
        chunking_version: Optional[str] = None,
        diarization_version: Optional[str] = None,
    ) -> dict:
        """
        INSERT OR IGNORE a pipeline version record.
        Returns the existing or newly created row.
        """
        record_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        conn = get_connection()
        try:
            # Try insert; if UNIQUE constraint fires, fetch existing
            try:
                conn.execute(
                    """
                    INSERT INTO pipeline_versions
                        (id, pipeline_name, engine_version, model_version,
                         prompt_template_version, chunking_version, diarization_version,
                         active, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                    """,
                    (
                        record_id,
                        pipeline_name,
                        engine_version,
                        model_version,
                        prompt_template_version,
                        chunking_version,
                        diarization_version,
                        now,
                    ),
                )
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM pipeline_versions WHERE id = ?", (record_id,)
                ).fetchone()
                log.info(
                    "Pipeline version registered",
                    pipeline_name=pipeline_name,
                    engine_version=engine_version,
                )
                return dict(row)
            except Exception:
                # Already exists — return existing row
                conn.rollback()
                row = conn.execute(
                    "SELECT * FROM pipeline_versions WHERE pipeline_name = ? AND engine_version = ?",
                    (pipeline_name, engine_version),
                ).fetchone()
                if row:
                    return dict(row)
                raise
        finally:
            conn.close()

    def get_current(self, pipeline_name: str) -> Optional[dict]:
        """Return the latest active version for a pipeline, or None."""
        conn = get_connection()
        try:
            row = conn.execute(
                """
                SELECT * FROM pipeline_versions
                WHERE pipeline_name = ? AND active = 1
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (pipeline_name,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def list_versions(self, pipeline_name: Optional[str] = None) -> list[dict]:
        """Return all pipeline version records, optionally filtered by name."""
        conn = get_connection()
        try:
            if pipeline_name:
                rows = conn.execute(
                    "SELECT * FROM pipeline_versions WHERE pipeline_name = ? ORDER BY created_at DESC",
                    (pipeline_name,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM pipeline_versions ORDER BY pipeline_name, created_at DESC"
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def check_backfill_eligible(self, artifact_id: str) -> list[dict]:
        """
        Compare artifact's extraction versions against current pipeline versions.
        Returns list of {pipeline_name, current_version, target_version} for
        pipelines that have a newer version available.
        """
        conn = get_connection()
        try:
            # Get all extracted records for this artifact
            extracted = conn.execute(
                """
                SELECT pipeline_name, pipeline_version
                FROM artifacts_extracted
                WHERE artifact_id = ?
                ORDER BY created_at DESC
                """,
                (artifact_id,),
            ).fetchall()

            eligible = []
            seen_pipelines: set[str] = set()

            for row in extracted:
                pname = row["pipeline_name"]
                if pname in seen_pipelines:
                    continue
                seen_pipelines.add(pname)

                current_version = conn.execute(
                    """
                    SELECT engine_version FROM pipeline_versions
                    WHERE pipeline_name = ? AND active = 1
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (pname,),
                ).fetchone()

                if current_version and current_version["engine_version"] != row["pipeline_version"]:
                    eligible.append({
                        "pipeline_name": pname,
                        "current_version": row["pipeline_version"],
                        "target_version": current_version["engine_version"],
                    })

            return eligible
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Module-level singleton + convenience wrappers
# ---------------------------------------------------------------------------

_tracker = VersionTracker()


def register_version(pipeline_name: str, engine_version: str, **kwargs) -> dict:
    return _tracker.register_version(pipeline_name, engine_version, **kwargs)


def get_current_version(pipeline_name: str) -> Optional[dict]:
    return _tracker.get_current(pipeline_name)


def list_versions(pipeline_name: Optional[str] = None) -> list[dict]:
    return _tracker.list_versions(pipeline_name)


def check_backfill_eligible(artifact_id: str) -> list[dict]:
    return _tracker.check_backfill_eligible(artifact_id)
