"""
Mission Control — RAG Engine
==============================
Orchestrates all RAG operations:
  - index_artifact(artifact_id)     — embed artifact extracted text
  - index_codebase(project_id, path) — walk + embed a code directory
  - index_web(url, project_id)       — fetch URL + embed
  - search(query, ...)               — semantic top-k search
  - inject_context(task_id, project_id, messages) — pre-task RAG injection

All operations gracefully degrade if Ollama is unavailable.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.core.logging import get_logger
from app.database.init import get_connection
from app.rag.chunker import TextChunk, chunk_code_file, chunk_text
from app.rag.embedding import (
    EmbeddingClient,
    get_embedding_client,
    vector_to_blob,
)
from app.rag.similarity import ScoredChunk, top_k_chunks

log = get_logger("rag.engine")

# Default file extensions indexed for codebase RAG
DEFAULT_CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs",
    ".md", ".txt", ".yaml", ".yml", ".toml", ".json",
    ".java", ".kt", ".rb", ".php", ".c", ".cpp", ".h",
}
DEFAULT_MAX_FILE_KB = 100
CODE_EXTENSIONS = set(DEFAULT_CODE_EXTENSIONS)


# ── Internal helpers ─────────────────────────────────────────────────────────

def _store_chunks(
    conn,
    source_type: str,
    source_id: str,
    project_id: Optional[str],
    chunks: list[TextChunk],
    client: EmbeddingClient,
    embedding_model: str,
) -> int:
    """
    Embed and store a list of TextChunks.
    Returns count of chunks actually stored (skips if embedding returns None).
    """
    stored = 0
    now = datetime.now(timezone.utc).isoformat()

    for chunk in chunks:
        vector = client.embed(chunk.text)
        if vector is None:
            log.debug("Skipping chunk — embedding unavailable", index=chunk.index)
            continue

        blob = vector_to_blob(vector)
        row_id = str(uuid.uuid4())

        conn.execute(
            """
            INSERT INTO embeddings
                (id, source_type, source_id, project_id, chunk_index,
                 chunk_text, embedding_model, embedding_vector, embedding_dim, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row_id,
                source_type,
                source_id,
                project_id,
                chunk.index,
                chunk.text,
                embedding_model,
                blob,
                len(vector),
                now,
            ),
        )
        stored += 1

    return stored


def _delete_embeddings(conn, source_type: str, source_id: str) -> int:
    """Remove all embeddings for a given source. Returns rows deleted."""
    cursor = conn.execute(
        "DELETE FROM embeddings WHERE source_type = ? AND source_id = ?",
        (source_type, source_id),
    )
    return cursor.rowcount


def _delete_project_codebase(conn, project_id: str) -> int:
    """Remove all codebase embeddings for a project. Returns rows deleted."""
    cursor = conn.execute(
        "DELETE FROM embeddings WHERE source_type = 'codebase' AND project_id = ?",
        (project_id,),
    )
    return cursor.rowcount


def _load_candidates(
    conn,
    source_types: list[str],
    project_id: Optional[str] = None,
) -> list[dict]:
    """
    Load embedding rows for the given source_types.
    Optionally filter codebase entries by project_id.
    """
    placeholders = ",".join("?" * len(source_types))
    if project_id:
        rows = conn.execute(
            f"""
            SELECT source_type, source_id, project_id, chunk_index, chunk_text, embedding_vector
            FROM embeddings
            WHERE source_type IN ({placeholders})
              AND (project_id IS NULL OR project_id = ?)
            """,
            source_types + [project_id],
        ).fetchall()
    else:
        rows = conn.execute(
            f"""
            SELECT source_type, source_id, project_id, chunk_index, chunk_text, embedding_vector
            FROM embeddings
            WHERE source_type IN ({placeholders})
            """,
            source_types,
        ).fetchall()
    return [dict(r) for r in rows]


# ── RAGEngine ────────────────────────────────────────────────────────────────

class RAGEngine:
    """
    Manages all RAG indexing and retrieval operations.
    Uses a shared EmbeddingClient — degrades gracefully when Ollama is down.
    """

    def __init__(self, client: Optional[EmbeddingClient] = None) -> None:
        self._client = client or get_embedding_client()

    @property
    def embedding_model(self) -> str:
        return self._client.model

    # ── Indexing ──────────────────────────────────────────────────────────────

    def index_artifact(self, artifact_id: str) -> int:
        """
        Embed text from artifacts_extracted for a given artifact_id.
        Re-indexes (deletes old embeddings first).
        Returns count of chunks stored.
        """
        conn = get_connection()
        try:
            # Fetch extracted text — prefer the most recent row
            row = conn.execute(
                """
                SELECT extraction_data FROM artifacts_extracted
                WHERE artifact_id = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (artifact_id,),
            ).fetchone()

            if not row:
                log.warning("No extracted data for artifact", artifact_id=artifact_id)
                return 0

            try:
                data = json.loads(row["extraction_data"])
            except (json.JSONDecodeError, TypeError):
                data = {}

            # Try to extract text from different pipeline output shapes
            text = (
                data.get("extracted_text")
                or data.get("transcript")
                or data.get("summary_text")
                or data.get("text")
                or ""
            )

            if not text:
                log.info("No text to embed for artifact", artifact_id=artifact_id)
                return 0

            chunks = chunk_text(text)
            if not chunks:
                return 0

            # Delete stale embeddings, store fresh ones
            _delete_embeddings(conn, "artifact", artifact_id)
            stored = _store_chunks(
                conn,
                source_type="artifact",
                source_id=artifact_id,
                project_id=None,
                chunks=chunks,
                client=self._client,
                embedding_model=self.embedding_model,
            )
            conn.commit()
            log.info("Artifact indexed", artifact_id=artifact_id, chunks=stored)
            return stored
        finally:
            conn.close()

    def index_codebase(
        self,
        project_id: str,
        path: str,
        extensions: Optional[set[str]] = None,
        max_file_kb: int = DEFAULT_MAX_FILE_KB,
    ) -> dict:
        """
        Walk a directory and embed all eligible source files.
        Scoped to project_id. Replaces any existing codebase index for that project.

        Returns: {indexed_files, total_chunks, skipped_files, errors}
        """
        exts = extensions or CODE_EXTENSIONS
        root = Path(path)

        if not root.exists() or not root.is_dir():
            raise ValueError(f"Path does not exist or is not a directory: {path}")

        conn = get_connection()
        try:
            _delete_project_codebase(conn, project_id)
            conn.commit()

            indexed_files = 0
            skipped_files = 0
            total_chunks = 0
            errors: list[str] = []

            for fpath in root.rglob("*"):
                if not fpath.is_file():
                    continue
                if fpath.suffix.lower() not in exts:
                    continue
                if fpath.stat().st_size > max_file_kb * 1024:
                    skipped_files += 1
                    continue

                # Skip hidden directories and common noise dirs
                parts = fpath.parts
                if any(p.startswith(".") or p in ("node_modules", "__pycache__", ".git", "venv", ".venv") for p in parts):
                    skipped_files += 1
                    continue

                try:
                    text = fpath.read_text(encoding="utf-8", errors="replace")
                except Exception as exc:
                    errors.append(f"{fpath}: {exc}")
                    skipped_files += 1
                    continue

                # Use source_id = relative path from root
                source_id = str(fpath.relative_to(root))
                chunks = chunk_code_file(text, file_path=source_id)
                if not chunks:
                    continue

                stored = _store_chunks(
                    conn,
                    source_type="codebase",
                    source_id=source_id,
                    project_id=project_id,
                    chunks=chunks,
                    client=self._client,
                    embedding_model=self.embedding_model,
                )
                if stored > 0:
                    indexed_files += 1
                    total_chunks += stored

            conn.commit()
            log.info(
                "Codebase indexed",
                project_id=project_id,
                path=path,
                indexed_files=indexed_files,
                total_chunks=total_chunks,
                skipped_files=skipped_files,
            )
            return {
                "indexed_files": indexed_files,
                "total_chunks": total_chunks,
                "skipped_files": skipped_files,
                "errors": errors,
            }
        finally:
            conn.close()

    def index_web(
        self,
        url: str,
        project_id: Optional[str] = None,
        artifact_id: Optional[str] = None,
    ) -> int:
        """
        Fetch a URL, extract text, chunk and embed.
        If artifact_id is provided, uses it as source_id and stores clean text
        back to artifacts_extracted.
        Returns count of chunks stored.
        """
        from app.rag.web_fetcher import fetch_url

        text = fetch_url(url)
        if not text:
            log.warning("Web fetch returned no text", url=url)
            return 0

        source_id = artifact_id or url
        chunks = chunk_text(text)
        if not chunks:
            return 0

        conn = get_connection()
        try:
            _delete_embeddings(conn, "web_page", source_id)

            # If we have an artifact_id, store clean text to artifacts_extracted
            if artifact_id:
                row_id = str(uuid.uuid4())
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    """
                    INSERT OR IGNORE INTO artifacts_extracted
                        (id, artifact_id, pipeline_name, pipeline_version,
                         engine_version, extraction_data, created_at)
                    VALUES (?, ?, 'web_ingest', '1.0', '1.0', ?, ?)
                    """,
                    (
                        row_id,
                        artifact_id,
                        json.dumps({"extracted_text": text, "url": url}),
                        now,
                    ),
                )

            stored = _store_chunks(
                conn,
                source_type="web_page",
                source_id=source_id,
                project_id=project_id,
                chunks=chunks,
                client=self._client,
                embedding_model=self.embedding_model,
            )
            conn.commit()
            log.info("Web page indexed", url=url, source_id=source_id, chunks=stored)
            return stored
        finally:
            conn.close()

    def delete_project_index(self, project_id: str) -> int:
        """Remove all codebase embeddings for a project. Returns rows deleted."""
        conn = get_connection()
        try:
            deleted = _delete_project_codebase(conn, project_id)
            conn.commit()
            log.info("Codebase index deleted", project_id=project_id, rows=deleted)
            return deleted
        finally:
            conn.close()

    # ── Search ────────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        source_types: Optional[list[str]] = None,
        project_id: Optional[str] = None,
        top_k: int = 5,
        threshold: float = 0.0,
    ) -> list[ScoredChunk]:
        """
        Embed query and return top-k chunks by cosine similarity.
        Returns [] if Ollama is unavailable or no embeddings exist.
        """
        types = source_types or ["artifact", "codex", "codebase", "web_page"]
        query_vec = self._client.embed(query)
        if query_vec is None:
            return []

        conn = get_connection()
        try:
            candidates = _load_candidates(conn, types, project_id=project_id)
        finally:
            conn.close()

        if not candidates:
            return []

        return top_k_chunks(query_vec, candidates, top_k=top_k, threshold=threshold)

    def get_stats(self) -> dict:
        """Return embedding counts grouped by source_type."""
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT source_type, COUNT(*) AS chunk_count,
                       COUNT(DISTINCT source_id) AS source_count
                FROM embeddings
                GROUP BY source_type
                ORDER BY source_type
                """
            ).fetchall()
            return {
                "by_source_type": [dict(r) for r in rows],
                "total_chunks": sum(r["chunk_count"] for r in rows),
            }
        finally:
            conn.close()

    # ── Pre-task RAG injection ────────────────────────────────────────────────

    def inject_context(
        self,
        task_id: str,
        project_id: str,
        messages: list[dict],
        prompt_text: Optional[str] = None,
    ) -> tuple[list[dict], int, list[str]]:
        """
        Query relevant chunks and prepend a RAG context block to the messages.

        Uses the user message content as query if prompt_text is not provided.

        Returns:
            (augmented_messages, chunk_count, source_ids_used)
        """
        # Extract query from the last user message if no explicit prompt
        query = prompt_text
        if not query:
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    query = msg["content"]
                    break

        if not query:
            return messages, 0, []

        all_chunks: list[ScoredChunk] = []

        # 1. Codebase chunks (project-scoped, top-5)
        cb = self.search(query, source_types=["codebase"], project_id=project_id, top_k=5)
        all_chunks.extend(cb)

        # 2. Artifact chunks (project-scoped or global, top-3)
        art = self.search(query, source_types=["artifact"], project_id=project_id, top_k=3)
        all_chunks.extend(art)

        # 3. Web page chunks (project-scoped, top-2)
        web = self.search(query, source_types=["web_page"], project_id=project_id, top_k=2)
        all_chunks.extend(web)

        if not all_chunks:
            return messages, 0, []

        # Deduplicate by (source_id, chunk_index), keep highest score
        seen: dict[tuple, ScoredChunk] = {}
        for chunk in all_chunks:
            key = (chunk.source_id, chunk.chunk_index)
            if key not in seen or chunk.score > seen[key].score:
                seen[key] = chunk

        # Sort by score, take top 10 overall
        top = sorted(seen.values(), key=lambda c: c.score, reverse=True)[:10]

        # Build context block
        source_ids = list({c.source_id for c in top})
        lines = [f"[RAG CONTEXT — {len(top)} chunks from {len(source_ids)} source(s)]"]
        for chunk in top:
            label = f"{chunk.source_type}:{chunk.source_id}[{chunk.chunk_index}]"
            lines.append(f"\n--- {label} (score: {chunk.score:.3f}) ---")
            lines.append(chunk.chunk_text)
        lines.append("\n[END RAG CONTEXT]")

        rag_msg = {"role": "system", "content": "\n".join(lines)}

        # Insert RAG block after existing system messages, before user messages
        system_msgs = [m for m in messages if m.get("role") == "system"]
        other_msgs  = [m for m in messages if m.get("role") != "system"]
        augmented = system_msgs + [rag_msg] + other_msgs

        log.info(
            "RAG context injected",
            task_id=task_id,
            chunks=len(top),
            sources=len(source_ids),
        )
        return augmented, len(top), source_ids


# ── Module-level singleton ───────────────────────────────────────────────────

_engine: Optional[RAGEngine] = None


def get_rag_engine() -> RAGEngine:
    global _engine
    if _engine is None:
        _engine = RAGEngine()
    return _engine
