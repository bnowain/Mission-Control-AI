"""
Mission Control — Audit Log Helper (Phase 8)
=============================================
Append-only writes to the audit_log table.

All actions that modify state MUST call write_audit_log().
audit_log rows are NEVER updated or deleted — immutable record.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from ulid import ULID

from app.core.logging import get_logger
from app.database.init import get_connection

log = get_logger("audit")

# ── Canonical action type constants ──────────────────────────────────────────

ACTION_ARTIFACT_UPLOADED    = "artifact.uploaded"
ACTION_ARTIFACT_ARCHIVED    = "artifact.archived"
ACTION_TASK_CREATED         = "task.created"
ACTION_TASK_CANCELLED       = "task.cancelled"
ACTION_TASK_EXECUTED        = "task.executed"
ACTION_SQL_QUERY            = "sql.query.executed"
ACTION_BACKFILL_TRIGGERED   = "backfill.triggered"
ACTION_CODEX_PROMOTED       = "codex.promoted"
ACTION_PROMPT_REGISTERED    = "prompt.registered"
ACTION_FLAG_UPDATED         = "feature_flag.updated"
ACTION_OVERRIDE_CREATED     = "override.created"
ACTION_LINEAGE_RECORDED     = "lineage.recorded"


def write_audit_log(
    action_type: str,
    *,
    api_key_id: Optional[str] = None,
    artifact_id: Optional[str] = None,
    task_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    result: str = "success",
    metadata: Optional[dict[str, Any]] = None,
) -> str:
    """
    Append an immutable audit record.
    Returns the new audit record ID (ULID).
    Never raises — errors are logged but don't break callers.
    """
    record_id = str(ULID())
    timestamp = datetime.now(timezone.utc).isoformat()
    metadata_json = json.dumps(metadata) if metadata else None

    try:
        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO audit_log
                    (id, timestamp, api_key_id, action_type,
                     artifact_id, task_id, ip_address, result, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (record_id, timestamp, api_key_id, action_type,
                 artifact_id, task_id, ip_address, result, metadata_json),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        log.warning("Failed to write audit log", action=action_type, exc=str(exc))

    return record_id


def get_audit_log(
    limit: int = 50,
    offset: int = 0,
    action_type: Optional[str] = None,
    artifact_id: Optional[str] = None,
    task_id: Optional[str] = None,
) -> tuple[list[dict], int]:
    """
    Query audit log with optional filters.
    Returns (rows, total_count).
    """
    filters: list[str] = []
    params: list[Any] = []

    if action_type:
        filters.append("action_type = ?")
        params.append(action_type)
    if artifact_id:
        filters.append("artifact_id = ?")
        params.append(artifact_id)
    if task_id:
        filters.append("task_id = ?")
        params.append(task_id)

    where = f"WHERE {' AND '.join(filters)}" if filters else ""

    conn = get_connection()
    try:
        total = conn.execute(
            f"SELECT COUNT(*) FROM audit_log {where}", params
        ).fetchone()[0]

        rows = conn.execute(
            f"""
            SELECT id, timestamp, api_key_id, action_type,
                   artifact_id, task_id, ip_address, result, metadata_json
            FROM audit_log
            {where}
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ).fetchall()

        return [dict(r) for r in rows], total
    finally:
        conn.close()
