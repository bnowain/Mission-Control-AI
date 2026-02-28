"""
Mission Control — RAG API (Phase 7)
=====================================
POST   /rag/index              — index a codebase directory for a project
GET    /rag/search             — semantic search over embeddings
GET    /rag/stats              — embedding counts by source_type
DELETE /rag/index/{project_id} — remove codebase index for a project

Atlas-exposed:
GET /api/rag/search?q=&limit= — semantic search (artifact + web_page only)
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.database.async_helpers import run_in_thread
from app.rag.engine import get_rag_engine

router = APIRouter(tags=["rag"])


# ── Request / Response models ─────────────────────────────────────────────────

class IndexCodebaseRequest(BaseModel):
    project_id: str
    path: str
    extensions: Optional[list[str]] = None   # e.g. [".py", ".ts"]
    max_file_kb: int = 100


class IndexCodebaseResponse(BaseModel):
    project_id: str
    path: str
    indexed_files: int
    total_chunks: int
    skipped_files: int
    errors: list[str] = []


class RAGChunkResult(BaseModel):
    source_type: str
    source_id: str
    project_id: Optional[str]
    chunk_index: int
    chunk_text: str
    score: float


class RAGSearchResponse(BaseModel):
    query: str
    results: list[RAGChunkResult]
    total: int


class RAGStatsResponse(BaseModel):
    by_source_type: list[dict]
    total_chunks: int


# ── POST /rag/index ────────────────────────────────────────────────────────────

@router.post("/rag/index", response_model=IndexCodebaseResponse)
async def index_codebase(req: IndexCodebaseRequest):
    """Index a local codebase directory for semantic search."""
    extensions = set(req.extensions) if req.extensions else None
    try:
        result = await run_in_thread(
            get_rag_engine().index_codebase,
            req.project_id,
            req.path,
            extensions,
            req.max_file_kb,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return IndexCodebaseResponse(
        project_id=req.project_id,
        path=req.path,
        **result,
    )


# ── GET /rag/search ────────────────────────────────────────────────────────────

@router.get("/rag/search", response_model=RAGSearchResponse)
async def rag_search(
    q: str = Query(..., description="Search query"),
    project_id: Optional[str] = Query(default=None),
    source_type: Optional[str] = Query(default=None, description="Filter: artifact|codebase|web_page|codex"),
    limit: int = Query(default=10, ge=1, le=50),
):
    """Semantic search over embeddings."""
    source_types = [source_type] if source_type else None
    chunks = await run_in_thread(
        get_rag_engine().search,
        q,
        source_types,
        project_id,
        limit,
        0.0,
    )
    return RAGSearchResponse(
        query=q,
        results=[
            RAGChunkResult(
                source_type=c.source_type,
                source_id=c.source_id,
                project_id=c.project_id,
                chunk_index=c.chunk_index,
                chunk_text=c.chunk_text,
                score=round(c.score, 4),
            )
            for c in chunks
        ],
        total=len(chunks),
    )


# ── GET /rag/stats ─────────────────────────────────────────────────────────────

@router.get("/rag/stats", response_model=RAGStatsResponse)
async def rag_stats():
    """Return embedding counts by source type."""
    stats = await run_in_thread(get_rag_engine().get_stats)
    return RAGStatsResponse(**stats)


# ── DELETE /rag/index/{project_id} ─────────────────────────────────────────────

@router.delete("/rag/index/{project_id}")
async def delete_codebase_index(project_id: str):
    """Remove all codebase embeddings for a project."""
    deleted = await run_in_thread(get_rag_engine().delete_project_index, project_id)
    return {"project_id": project_id, "rows_deleted": deleted}


# ── GET /api/rag/search (Atlas-exposed) ────────────────────────────────────────

@router.get("/api/rag/search", response_model=RAGSearchResponse)
async def atlas_rag_search(
    q: str = Query(..., description="Search query"),
    limit: int = Query(default=10, ge=1, le=50),
):
    """
    Atlas-exposed semantic search over artifact + web_page embeddings.
    Codebase embeddings excluded (too project-specific for cross-spoke search).
    """
    chunks = await run_in_thread(
        get_rag_engine().search,
        q,
        ["artifact", "web_page"],  # no codebase for Atlas
        None,                       # no project filter
        limit,
        0.0,
    )
    return RAGSearchResponse(
        query=q,
        results=[
            RAGChunkResult(
                source_type=c.source_type,
                source_id=c.source_id,
                project_id=c.project_id,
                chunk_index=c.chunk_index,
                chunk_text=c.chunk_text,
                score=round(c.score, 4),
            )
            for c in chunks
        ],
        total=len(chunks),
    )
