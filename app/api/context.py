"""
Mission Control — Context OS API (Phase 3)
============================================
POST /context/chunk     → chunk a file into the file_chunks table
POST /context/compress  → compress conversation history
POST /context/workingset → build a working set from file chunks
"""

from fastapi import APIRouter, HTTPException

from app.context.chunker import chunk_file, get_file_chunks
from app.context.compressor import compress_messages
from app.context.working_set import build_working_set
from app.database.async_helpers import run_in_thread
from app.models.schemas import (
    ChunkRequest,
    ChunkResponse,
    CompressRequest,
    CompressResponse,
    ContextTier,
    WorkingSetRequest,
    WorkingSetResponse,
)

router = APIRouter(prefix="/context", tags=["context"])


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/chunk", response_model=ChunkResponse)
async def chunk_context(req: ChunkRequest) -> ChunkResponse:
    """
    Split file content into chunks and store in file_chunks table.
    Returns chunk IDs for working set construction.
    """
    def _chunk():
        ids = chunk_file(
            project_id=req.project_id,
            file_path=req.file_path,
            content=req.content,
            chunk_size=req.chunk_size,
        )
        return ChunkResponse(
            file_path=req.file_path,
            project_id=req.project_id,
            chunk_count=len(ids),
            chunk_ids=ids,
        )

    return await run_in_thread(_chunk)


@router.post("/compress", response_model=CompressResponse)
async def compress_context(req: CompressRequest) -> CompressResponse:
    """
    Compress a conversation message history to fit within a token budget.
    Keeps system messages + head/tail turns; summarises the middle.
    """
    def _compress():
        result = compress_messages(
            task_id=req.task_id,
            messages=req.messages,
            max_tokens=req.max_tokens,
        )
        return CompressResponse(
            task_id=result["task_id"],
            original_messages=result["original_messages"],
            compressed_tokens=result["compressed_tokens"],
            summary=result["summary"],
            messages=result["messages"],
        )

    return await run_in_thread(_compress)


@router.post("/workingset", response_model=WorkingSetResponse)
async def build_working_set_endpoint(req: WorkingSetRequest) -> WorkingSetResponse:
    """
    Build a working set of file chunks within the token budget.
    Chunks must have been previously ingested via POST /context/chunk.
    """
    def _build():
        result = build_working_set(
            task_id=req.task_id,
            file_paths=req.file_paths,
            project_id=req.project_id,
            token_budget=req.token_budget,
        )
        return WorkingSetResponse(
            task_id=result["task_id"],
            chunk_count=result["chunk_count"],
            total_tokens=result["total_tokens"],
            chunks=result["chunks"],
        )

    return await run_in_thread(_build)
