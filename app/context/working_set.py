"""
Mission Control — Working Set Builder (Phase 3)
=================================================
Selects which file_chunks to include in the context window for a task,
respecting the token budget for the active context tier.

Strategy:
  1. Load all chunks for each requested file_path
  2. Score chunks by relevance (Phase 3: recency + position; Phase 5+: embedding similarity)
  3. Fill budget greedily from highest-scored chunks
  4. Return selected chunks as message content

Token budget = CONTEXT_TIER_SIZE * 0.6  (leave 40% for prompt + response)
"""

from __future__ import annotations

from typing import Optional

from app.context.chunker import FileChunker
from app.core.logging import get_logger
from app.database.init import get_connection
from app.models.schemas import CONTEXT_TIER_SIZES, ContextTier

log = get_logger("context.working_set")

CHARS_PER_TOKEN = 4
CONTEXT_BUDGET_FRACTION = 0.6  # use 60% of tier budget for file context


class WorkingSetBuilder:
    """
    Builds a working set of file chunks that fit within a token budget.

    Usage:
        builder = WorkingSetBuilder()
        result = builder.build(
            task_id="01J...",
            file_paths=["app/core/execution_loop.py", "app/grading/engine.py"],
            project_id="01J...",
            tier=ContextTier.EXECUTION,
        )
        # result["chunks"] is a list of chunk dicts
        # result["total_tokens"] is the estimated token count
    """

    def __init__(self) -> None:
        self._chunker = FileChunker()

    def build(
        self,
        task_id: str,
        file_paths: list[str],
        project_id: str,
        tier: ContextTier = ContextTier.EXECUTION,
        token_budget: Optional[int] = None,
    ) -> dict:
        """
        Select chunks from the given file_paths within the token budget.

        Returns dict with: task_id, chunk_count, total_tokens, chunks.
        """
        if token_budget is None:
            tier_size = CONTEXT_TIER_SIZES[tier]
            token_budget = int(tier_size * CONTEXT_BUDGET_FRACTION)

        selected: list[dict] = []
        total_chars = 0
        budget_chars = token_budget * CHARS_PER_TOKEN

        for file_path in file_paths:
            chunks = self._chunker.get_chunks(project_id, file_path)
            if not chunks:
                log.debug("No chunks found for file", file_path=file_path, project_id=project_id)
                continue

            # Phase 3: include chunks in order until budget is full
            for chunk in chunks:
                chunk_chars = len(chunk.get("content", ""))
                if total_chars + chunk_chars > budget_chars:
                    log.info(
                        "Budget reached — stopping chunk inclusion",
                        file_path=file_path,
                        selected=len(selected),
                        budget_chars=budget_chars,
                    )
                    break
                selected.append({
                    "id": chunk["id"],
                    "file_path": file_path,
                    "chunk_index": chunk["chunk_index"],
                    "content": chunk["content"],
                    "chunk_hash": chunk["chunk_hash"],
                })
                total_chars += chunk_chars

        total_tokens = total_chars // CHARS_PER_TOKEN

        log.info(
            "Working set built",
            task_id=task_id,
            file_count=len(file_paths),
            chunk_count=len(selected),
            total_tokens=total_tokens,
            budget_tokens=token_budget,
        )

        return {
            "task_id": task_id,
            "chunk_count": len(selected),
            "total_tokens": total_tokens,
            "chunks": selected,
        }

    def to_messages(self, working_set: dict) -> list[dict]:
        """
        Convert a working set into OpenAI-format system messages.
        One message per unique file path (all chunks concatenated).
        """
        # Group chunks by file_path
        by_file: dict[str, list[dict]] = {}
        for chunk in working_set.get("chunks", []):
            fp = chunk["file_path"]
            by_file.setdefault(fp, []).append(chunk)

        messages: list[dict] = []
        for file_path, chunks in by_file.items():
            content = f"[File: {file_path}]\n" + "\n".join(c["content"] for c in chunks)
            messages.append({"role": "system", "content": content})

        return messages


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_builder = WorkingSetBuilder()


def build_working_set(
    task_id: str,
    file_paths: list[str],
    project_id: str,
    tier: ContextTier = ContextTier.EXECUTION,
    token_budget: Optional[int] = None,
) -> dict:
    """Convenience wrapper for WorkingSetBuilder.build()."""
    return _builder.build(
        task_id=task_id,
        file_paths=file_paths,
        project_id=project_id,
        tier=tier,
        token_budget=token_budget,
    )
