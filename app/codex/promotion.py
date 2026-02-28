"""
Mission Control — Codex Promotion Pipeline (Phase 3)
======================================================
Promotes codex_candidates to master_codex after threshold enforcement.

Promotion thresholds (ANY one triggers eligibility):
  - human_verified = 1
  - The issue_signature has appeared >= 3 times in failure_events
  - The candidate's task had downstream_impact = 1

Promotion rules:
  - If issue_signature already exists in master_codex → increment occurrence_count
  - If new → INSERT new entry
  - Old entries are NEVER deleted — mark superseded via codex_supersessions
  - Always set codex_promoted = 1 on the candidate after promoting

model_source is required on all Codex entries (Rule from schema-decisions.md).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from app.core.logging import get_logger
from app.database.init import get_connection
from app.models.schemas import ModelSource

log = get_logger("codex.promotion")

# Minimum occurrence count before auto-promotion is allowed
AUTO_PROMOTE_THRESHOLD = 3


class CodexPromoter:
    """
    Promotes codex_candidates to master_codex with full threshold enforcement.

    Usage:
        promoter = CodexPromoter()
        result = promoter.promote(candidate_id, promoted_by=ModelSource.HUMAN)
    """

    def check_eligible(self, candidate_id: str) -> tuple[bool, str]:
        """
        Return (is_eligible, reason) for a given candidate.
        Checks: human_verified, occurrence_count, downstream_impact.
        """
        conn = get_connection()
        try:
            cand = conn.execute(
                "SELECT * FROM codex_candidates WHERE id = ?",
                (candidate_id,),
            ).fetchone()

            if cand is None:
                return False, "candidate not found"

            if cand["codex_promoted"]:
                return False, "already promoted"

            if cand["human_verified"]:
                return True, "human_verified=1"

            # Count occurrences of this issue_signature in failure_events
            occurrence_count = conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM failure_events fe
                JOIN tasks t ON fe.task_id = t.id
                WHERE t.signature = ?
                """,
                (cand["issue_signature"],),
            ).fetchone()["cnt"]

            if occurrence_count >= AUTO_PROMOTE_THRESHOLD:
                return True, f"occurrence_count={occurrence_count} >= {AUTO_PROMOTE_THRESHOLD}"

            # Check if linked task had downstream_impact
            downstream = conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM execution_logs el
                WHERE el.task_id = ? AND el.downstream_impact = 1
                """,
                (cand["task_id"],),
            ).fetchone()["cnt"]

            if downstream > 0:
                return True, "downstream_impact=1 on linked task"

            return False, f"occurrence_count={occurrence_count} < {AUTO_PROMOTE_THRESHOLD}, not human-verified"

        finally:
            conn.close()

    def promote(
        self,
        candidate_id: str,
        promoted_by: ModelSource = ModelSource.HUMAN,
        category: Optional[str] = None,
        scope: str = "global",
        confidence_score: float = 0.7,
    ) -> tuple[str, str]:
        """
        Promote a codex_candidate to master_codex.

        Returns (master_codex_id, action) where action is "created" or "updated".
        Raises ValueError if candidate not found.
        """
        now = datetime.now(timezone.utc).isoformat()

        conn = get_connection()
        try:
            cand = conn.execute(
                "SELECT * FROM codex_candidates WHERE id = ?",
                (candidate_id,),
            ).fetchone()

            if cand is None:
                raise ValueError(f"Candidate '{candidate_id}' not found.")

            issue_sig = cand["issue_signature"]
            root_cause = cand["proposed_root_cause"] or "Unknown root cause"
            resolution = cand["proposed_resolution"] or "Unknown resolution"
            prevention = resolution  # Use resolution as prevention guideline when not specified

            # Check if master_codex already has this issue_signature
            existing = conn.execute(
                "SELECT id, occurrence_count FROM master_codex WHERE issue_signature = ?",
                (issue_sig,),
            ).fetchone()

            if existing:
                # Update — increment occurrence_count
                master_id = existing["id"]
                conn.execute(
                    """
                    UPDATE master_codex
                    SET occurrence_count = occurrence_count + 1,
                        last_seen_at = ?,
                        confidence_score = MIN(confidence_score + 0.05, 1.0)
                    WHERE id = ?
                    """,
                    (now, master_id),
                )
                action = "updated"
                log.info(
                    "Codex entry updated (occurrence++)",
                    master_id=master_id,
                    issue_signature=issue_sig,
                    candidate_id=candidate_id,
                )
            else:
                # Insert new entry
                master_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO master_codex
                        (id, issue_signature, category, root_cause, resolution,
                         prevention_guideline, occurrence_count, confidence_score,
                         verified, model_source, scope, first_seen_at, last_seen_at)
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?, 1, ?, ?, ?, ?)
                    """,
                    (
                        master_id,
                        issue_sig,
                        category,
                        root_cause,
                        resolution,
                        prevention,
                        confidence_score,
                        promoted_by.value,
                        scope,
                        now,
                        now,
                    ),
                )
                action = "created"
                log.info(
                    "Codex entry created",
                    master_id=master_id,
                    issue_signature=issue_sig,
                    candidate_id=candidate_id,
                    promoted_by=promoted_by.value,
                )

            # Mark candidate as promoted
            conn.execute(
                "UPDATE codex_candidates SET codex_promoted = 1 WHERE id = ?",
                (candidate_id,),
            )

            conn.commit()
            return master_id, action

        finally:
            conn.close()

    def auto_promote_pending(self) -> list[tuple[str, str, str]]:
        """
        Check all unverified, unpromoted candidates for auto-promotion eligibility.
        Promotes all eligible ones.
        Returns list of (candidate_id, master_id, action) tuples.
        """
        conn = get_connection()
        try:
            candidates = conn.execute(
                "SELECT id FROM codex_candidates WHERE codex_promoted = 0 AND human_verified = 0"
            ).fetchall()
        finally:
            conn.close()

        results = []
        for row in candidates:
            cid = row["id"]
            eligible, reason = self.check_eligible(cid)
            if eligible:
                try:
                    master_id, action = self.promote(
                        cid,
                        promoted_by=ModelSource.LOCAL_OLLAMA,  # auto-promoted by system
                        confidence_score=0.6,
                    )
                    results.append((cid, master_id, action))
                    log.info(
                        "Auto-promotion succeeded",
                        candidate_id=cid,
                        master_id=master_id,
                        reason=reason,
                    )
                except Exception as exc:
                    log.warning(
                        "Auto-promotion failed",
                        candidate_id=cid,
                        exc=str(exc),
                    )

        return results


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_promoter = CodexPromoter()


def promote_candidate(
    candidate_id: str,
    promoted_by: ModelSource = ModelSource.HUMAN,
    **kwargs,
) -> tuple[str, str]:
    """Convenience wrapper for CodexPromoter.promote()."""
    return _promoter.promote(candidate_id, promoted_by=promoted_by, **kwargs)


def check_promotion_eligibility(candidate_id: str) -> tuple[bool, str]:
    """Convenience wrapper for CodexPromoter.check_eligible()."""
    return _promoter.check_eligible(candidate_id)
