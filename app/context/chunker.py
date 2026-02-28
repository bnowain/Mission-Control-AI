"""
Mission Control — File Chunker (Phase 3)
==========================================
Splits file content into fixed-size chunks for context window management.

Strategy (Phase 3): character-based chunking with line boundary respect.
Phase 5+: AST-aware chunking for Python/JS/TS files.

Each chunk is stored in the file_chunks table with:
  - SHA256 hash (content-addressed, dedup key)
  - chunk_index (position in file)
  - file_path + project_id (retrieval key)
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.core.logging import get_logger
from app.database.init import get_connection

log = get_logger("context.chunker")

DEFAULT_CHUNK_SIZE = 2000    # characters (~500 tokens at 4 chars/token)
DEFAULT_CHUNK_OVERLAP = 200  # overlap prevents losing context at boundaries


class FileChunker:
    """
    Splits file content into overlapping character chunks.

    Usage:
        chunker = FileChunker()
        chunk_ids = chunker.chunk_file(
            project_id="01J...",
            file_path="app/core/execution_loop.py",
            content=file_text,
        )
    """

    def chunk_file(
        self,
        project_id: str,
        file_path: str,
        content: str,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        overlap: int = DEFAULT_CHUNK_OVERLAP,
    ) -> list[str]:
        """
        Chunk content and upsert into file_chunks table.
        Returns list of chunk UUIDs (content-addressed — same content = same id).
        Existing chunks with the same hash are reused (deduped).
        """
        chunks = self._split(content, chunk_size, overlap)
        chunk_ids: list[str] = []
        now = datetime.now(timezone.utc).isoformat()

        conn = get_connection()
        try:
            for idx, chunk_text in enumerate(chunks):
                chunk_hash = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()
                chunk_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk_hash))

                # Upsert: if same hash exists for this file, reuse it
                existing = conn.execute(
                    "SELECT id FROM file_chunks WHERE chunk_hash = ? AND project_id = ? AND file_path = ?",
                    (chunk_hash, project_id, file_path),
                ).fetchone()

                if existing:
                    chunk_ids.append(existing["id"])
                else:
                    conn.execute(
                        """
                        INSERT INTO file_chunks
                            (id, project_id, file_path, chunk_index, chunk_hash, content, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (chunk_id, project_id, file_path, idx, chunk_hash, chunk_text, now),
                    )
                    chunk_ids.append(chunk_id)

            conn.commit()

        finally:
            conn.close()

        log.info(
            "File chunked",
            project_id=project_id,
            file_path=file_path,
            chunks=len(chunk_ids),
            chunk_size=chunk_size,
        )
        return chunk_ids

    def get_chunks(
        self,
        project_id: str,
        file_path: str,
    ) -> list[dict]:
        """Return all chunks for a file, ordered by chunk_index."""
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT id, chunk_index, chunk_hash, content, summary
                FROM file_chunks
                WHERE project_id = ? AND file_path = ?
                ORDER BY chunk_index
                """,
                (project_id, file_path),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_chunk_by_id(self, chunk_id: str) -> Optional[dict]:
        """Fetch a single chunk by UUID."""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM file_chunks WHERE id = ?",
                (chunk_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Splitting logic
    # ------------------------------------------------------------------

    @staticmethod
    def _split(content: str, chunk_size: int, overlap: int) -> list[str]:
        """
        Split content into overlapping chunks, respecting newline boundaries.
        The last chunk includes all remaining content.
        """
        if not content:
            return []

        chunks: list[str] = []
        start = 0
        length = len(content)

        while start < length:
            end = start + chunk_size

            if end >= length:
                # Last chunk: take everything remaining
                chunks.append(content[start:])
                break

            # Walk back to the last newline to avoid splitting mid-line
            boundary = content.rfind("\n", start, end)
            if boundary == -1 or boundary <= start:
                boundary = end  # No newline found — hard cut

            chunks.append(content[start:boundary])
            start = max(start + 1, boundary - overlap)

        return [c for c in chunks if c.strip()]


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_chunker = FileChunker()


def chunk_file(
    project_id: str,
    file_path: str,
    content: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> list[str]:
    """Convenience wrapper for FileChunker.chunk_file()."""
    return _chunker.chunk_file(project_id, file_path, content, chunk_size=chunk_size)


def get_file_chunks(project_id: str, file_path: str) -> list[dict]:
    """Convenience wrapper for FileChunker.get_chunks()."""
    return _chunker.get_chunks(project_id, file_path)
