"""
Mission Control — Feature Flags (Phase 8)
==========================================
Simple DB-backed feature flag system.

Usage:
    from app.core.feature_flags import is_feature_enabled

    if is_feature_enabled("adaptive_router_v2"):
        # use new router
"""

from __future__ import annotations

import random
from typing import Optional

from app.core.logging import get_logger
from app.database.init import get_connection

log = get_logger("feature_flags")


def is_feature_enabled(flag_name: str, project_id: Optional[str] = None) -> bool:
    """
    Check if a feature flag is enabled.

    - If the flag doesn't exist → False (fail closed).
    - If project_scope is set on the flag and doesn't match project_id → False.
    - Respects rollout_percentage (1–100) for gradual rollout.
    """
    try:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT enabled, rollout_percentage, project_scope "
                "FROM feature_flags WHERE flag_name = ?",
                (flag_name,),
            ).fetchone()
        finally:
            conn.close()
    except Exception as exc:
        log.warning("Feature flag lookup failed", flag=flag_name, exc=str(exc))
        return False

    if row is None or not row["enabled"]:
        return False

    # Project scope filter
    scope = row["project_scope"]
    if scope and scope != project_id:
        return False

    # Gradual rollout
    rollout = row["rollout_percentage"] or 100
    if rollout < 100:
        return random.randint(1, 100) <= rollout

    return True


def get_all_flags() -> list[dict]:
    """Return all feature flags as a list of dicts."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT flag_name, enabled, rollout_percentage, project_scope "
            "FROM feature_flags ORDER BY flag_name"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def set_flag(
    flag_name: str,
    enabled: bool,
    rollout_percentage: int = 100,
    project_scope: Optional[str] = None,
) -> None:
    """
    Create or update a feature flag.
    Uses INSERT OR REPLACE to handle both new and existing flags.
    """
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO feature_flags (flag_name, enabled, rollout_percentage, project_scope)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(flag_name) DO UPDATE SET
                enabled = excluded.enabled,
                rollout_percentage = excluded.rollout_percentage,
                project_scope = excluded.project_scope
            """,
            (flag_name, int(enabled), rollout_percentage, project_scope),
        )
        conn.commit()
    finally:
        conn.close()
