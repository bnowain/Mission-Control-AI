"""
Mission Control — Codex API (Phase 3 — Full Implementation)
=============================================================
POST /codex/query         → FTS5 search, returns prevention guidelines
POST /codex/candidate     → register a promotion candidate
POST /codex/promote       → promote candidate to master_codex (Phase 3)
GET  /codex/stats         → aggregate counts
GET  /codex/clusters      → failure clusters by stack_trace_hash
GET  /codex/clusters/{h}  → single cluster by hash
GET  /api/codex/search    → Atlas-exposed endpoint (exact shape contract)
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from app.codex.clustering import get_failure_clusters, upsert_cluster, _clusterer
from app.codex.engine import CodexEngine
from app.codex.promotion import check_promotion_eligibility, promote_candidate
from app.database.async_helpers import run_in_thread
from app.database.init import get_connection
from app.models.schemas import (
    CodexCandidateRequest,
    CodexCandidateResponse,
    CodexPromoteRequest,
    CodexPromoteResponse,
    CodexQueryRequest,
    CodexSearchResponse,
    CodexSearchResult,
    CodexStatsResponse,
    FailureClustersResponse,
    ModelSource,
)

router = APIRouter(tags=["codex"])

_codex = CodexEngine()


# ---------------------------------------------------------------------------
# Sync helpers
# ---------------------------------------------------------------------------

def _query_sync(issue_text: str, project_id, limit: int) -> list[CodexSearchResult]:
    return _codex.query(issue_text, project_id=project_id, limit=limit)


def _register_candidate_sync(task_id: str, issue_signature: str, root_cause, resolution) -> str:
    return _codex.register_candidate(
        task_id=task_id,
        issue_signature=issue_signature,
        proposed_root_cause=root_cause,
        proposed_resolution=resolution,
    )


def _get_stats_sync() -> CodexStatsResponse:
    conn = get_connection()
    try:
        master = conn.execute("SELECT COUNT(*) AS cnt FROM master_codex").fetchone()["cnt"]
        project = conn.execute("SELECT COUNT(*) AS cnt FROM project_codex").fetchone()["cnt"]
        candidates = conn.execute("SELECT COUNT(*) AS cnt FROM codex_candidates").fetchone()["cnt"]
        promoted = conn.execute(
            "SELECT COUNT(*) AS cnt FROM codex_candidates WHERE codex_promoted = 1"
        ).fetchone()["cnt"]
        return CodexStatsResponse(
            master_codex_count=master,
            project_codex_count=project,
            candidate_count=candidates,
            promoted_count=promoted,
        )
    finally:
        conn.close()


def _atlas_search_sync(q: str, limit: int, offset: int) -> CodexSearchResponse:
    results = _codex.query(q, limit=limit + offset)
    paged = results[offset: offset + limit]
    return CodexSearchResponse(
        results=paged,
        total=len(results),
        limit=limit,
        offset=offset,
    )


def _promote_sync(req: CodexPromoteRequest) -> CodexPromoteResponse:
    try:
        master_id, action = promote_candidate(
            candidate_id=req.candidate_id,
            promoted_by=req.promoted_by,
            category=req.category,
            scope=req.scope,
            confidence_score=req.confidence_score,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return CodexPromoteResponse(
        candidate_id=req.candidate_id,
        master_codex_id=master_id,
        action=action,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/codex/query", response_model=list[CodexSearchResult])
async def codex_query(req: CodexQueryRequest) -> list[CodexSearchResult]:
    """FTS5 search over master_codex + project_codex. Returns prevention guidelines."""
    return await run_in_thread(_query_sync, req.issue_text, req.project_id, req.limit)


@router.post("/codex/candidate", response_model=CodexCandidateResponse)
async def codex_candidate(req: CodexCandidateRequest) -> CodexCandidateResponse:
    """Register a codex promotion candidate for human review."""
    candidate_id = await run_in_thread(
        _register_candidate_sync,
        req.task_id,
        req.issue_signature,
        req.proposed_root_cause,
        req.proposed_resolution,
    )
    return CodexCandidateResponse(
        candidate_id=candidate_id,
        task_id=req.task_id,
        issue_signature=req.issue_signature,
    )


@router.post("/codex/promote", response_model=CodexPromoteResponse)
async def codex_promote(req: CodexPromoteRequest) -> CodexPromoteResponse:
    """
    Promote a codex_candidate to master_codex.
    Creates a new master_codex entry or increments occurrence_count on an existing one.
    """
    return await run_in_thread(_promote_sync, req)


@router.get("/codex/promote/{candidate_id}/eligible")
async def codex_promote_eligible(candidate_id: str) -> dict:
    """Check whether a candidate meets the auto-promotion threshold."""
    def _check():
        eligible, reason = check_promotion_eligibility(candidate_id)
        return {"candidate_id": candidate_id, "eligible": eligible, "reason": reason}
    return await run_in_thread(_check)


@router.get("/codex/stats", response_model=CodexStatsResponse)
async def codex_stats() -> CodexStatsResponse:
    """Aggregate codex counts: master, project, candidates, promoted."""
    return await run_in_thread(_get_stats_sync)


# ---------------------------------------------------------------------------
# Failure clustering endpoints
# ---------------------------------------------------------------------------

@router.get("/codex/clusters", response_model=FailureClustersResponse)
async def codex_clusters(
    min_count: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> FailureClustersResponse:
    """Failure clusters grouped by stack_trace_hash. Filter by min_count."""
    return await run_in_thread(get_failure_clusters, min_count, limit, offset)


@router.get("/codex/clusters/{stack_trace_hash}")
async def codex_cluster_by_hash(stack_trace_hash: str) -> dict:
    """Fetch a single failure cluster by stack_trace_hash."""
    def _fetch():
        cluster = _clusterer.get_by_hash(stack_trace_hash)
        if cluster is None:
            raise HTTPException(status_code=404, detail=f"No cluster for hash '{stack_trace_hash}'.")
        return cluster.model_dump()
    return await run_in_thread(_fetch)


# ---------------------------------------------------------------------------
# Atlas-exposed endpoint — exact shape contract required
# GET /api/codex/search?q=&limit=&offset=
# ---------------------------------------------------------------------------

@router.get("/api/codex/search", response_model=CodexSearchResponse)
async def atlas_codex_search(
    q: str = Query(..., description="Search query"),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> CodexSearchResponse:
    """
    Atlas-exposed codex search endpoint.
    Returns CodexSearchResponse shape exactly as declared in CLAUDE.md.
    """
    return await run_in_thread(_atlas_search_sync, q, limit, offset)
