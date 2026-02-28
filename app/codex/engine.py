"""
Mission Control — Codex Engine (Phase 1 Stub)
===============================================
Interface for querying the Codex before task execution and registering
failure candidates after execution.

Phase 1 behaviour:
  - query()              → FTS5 search over master_codex + project_codex
  - register_candidate() → writes to codex_candidates table
  - promote()            → stub (Phase 3)

Phase 3 will add:
  - Confidence-weighted routing overrides (see architecture-decisions.md)
  - Escalation rate tracking per issue signature
  - Auto-promotion pipeline with threshold enforcement
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.core.logging import get_logger
from app.database.init import get_connection
from app.models.schemas import CodexCandidate, CodexSearchResult, ModelSource

log = get_logger("codex")


class CodexEngine:
    """
    Codex query + candidate registration interface.

    Usage:
        codex = CodexEngine()
        guidelines = codex.query("null pointer dereference in parser.py")
        # inject guidelines into prompt before model execution

        codex.register_candidate(
            task_id="01J...",
            issue_signature="null_ptr_parser",
            proposed_root_cause="Missing None check before attribute access",
            proposed_resolution="Add `if obj is None: return` guard",
        )
    """

    # ------------------------------------------------------------------
    # Query — pre-task injection
    # ------------------------------------------------------------------

    def query(
        self,
        issue_text: str,
        project_id: Optional[str] = None,
        limit: int = 5,
    ) -> list[CodexSearchResult]:
        """
        FTS5 search over master_codex (and project_codex if project_id given).
        Returns prevention guidelines to inject into the task prompt.

        Phase 3: will also apply confidence-score filtering and routing hints.
        """
        results: list[CodexSearchResult] = []
        conn = get_connection()
        try:
            # Search master_codex via FTS5
            rows = conn.execute(
                """
                SELECT mc.id, mc.root_cause, mc.prevention_guideline,
                       mc.category, mc.scope, mc.confidence_score
                FROM master_codex_fts fts
                JOIN master_codex mc ON mc.rowid = fts.rowid
                WHERE master_codex_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (self._fts_query(issue_text), limit),
            ).fetchall()

            for row in rows:
                results.append(CodexSearchResult(
                    id=row["id"],
                    root_cause=row["root_cause"],
                    prevention_guideline=row["prevention_guideline"],
                    category=row["category"],
                    scope=row["scope"],
                    confidence_score=row["confidence_score"],
                ))

            # Also search project_codex if project_id provided
            if project_id:
                proj_rows = conn.execute(
                    """
                    SELECT pc.id, pc.root_cause, pc.resolution AS prevention_guideline,
                           NULL AS category, 'project' AS scope, 0.7 AS confidence_score
                    FROM project_codex_fts fts
                    JOIN project_codex pc ON pc.rowid = fts.rowid
                    WHERE project_codex_fts MATCH ?
                      AND pc.project_id = ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (self._fts_query(issue_text), project_id, limit),
                ).fetchall()

                for row in proj_rows:
                    results.append(CodexSearchResult(
                        id=row["id"],
                        root_cause=row["root_cause"],
                        prevention_guideline=row["prevention_guideline"],
                        category=row["category"],
                        scope=row["scope"],
                        confidence_score=row["confidence_score"],
                    ))

        except Exception as exc:
            # Never block execution on a Codex query failure
            log.warning("Codex query failed — continuing without guidelines", exc=str(exc))
        finally:
            conn.close()

        log.info(
            "Codex queried",
            issue_text=issue_text[:80],
            results=len(results),
            project_id=project_id,
        )
        return results

    # ------------------------------------------------------------------
    # Candidate registration — post-task
    # ------------------------------------------------------------------

    def register_candidate(
        self,
        task_id: str,
        issue_signature: str,
        proposed_root_cause: Optional[str] = None,
        proposed_resolution: Optional[str] = None,
    ) -> str:
        """
        Write a codex_candidates row for human review / auto-promotion.
        Called when a task fails (MaxRetriesExceeded or human_intervention=True).
        Returns the new candidate id (UUID).
        """
        candidate_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO codex_candidates
                    (id, task_id, issue_signature,
                     proposed_root_cause, proposed_resolution,
                     human_verified, codex_promoted, created_at)
                VALUES (?, ?, ?, ?, ?, 0, 0, ?)
                """,
                (
                    candidate_id,
                    task_id,
                    issue_signature,
                    proposed_root_cause,
                    proposed_resolution,
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        log.info(
            "Codex candidate registered",
            candidate_id=candidate_id,
            task_id=task_id,
            signature=issue_signature,
        )
        return candidate_id

    # ------------------------------------------------------------------
    # Promotion stub (Phase 3)
    # ------------------------------------------------------------------

    def promote(self, candidate_id: str, promoted_by: ModelSource = ModelSource.HUMAN) -> None:
        """
        Promote a codex_candidate to master_codex.
        Phase 1 stub — full pipeline in Phase 3.
        """
        log.warning(
            "Codex promotion not yet implemented (Phase 3)",
            candidate_id=candidate_id,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fts_query(text: str) -> str:
        """
        Sanitise input for FTS5 MATCH query.
        Wraps in quotes for phrase matching; strips FTS5 special chars.
        """
        sanitised = text.replace('"', ' ').replace("'", ' ')
        # Take first 10 words to avoid FTS5 query length issues
        words = sanitised.split()[:10]
        return " ".join(words)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_codex = CodexEngine()


def query_codex(issue_text: str, project_id: Optional[str] = None, limit: int = 5) -> list[CodexSearchResult]:
    """Convenience wrapper for CodexEngine.query()."""
    return _codex.query(issue_text, project_id=project_id, limit=limit)


def register_codex_candidate(task_id: str, issue_signature: str, **kwargs) -> str:
    """Convenience wrapper for CodexEngine.register_candidate()."""
    return _codex.register_candidate(task_id, issue_signature, **kwargs)
