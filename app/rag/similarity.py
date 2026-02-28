"""
Mission Control — Cosine Similarity
======================================
Pure-Python cosine similarity and top-k chunk retrieval.
No numpy required — compatible with any Python 3.x environment.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


@dataclass
class ScoredChunk:
    source_type: str
    source_id: str
    project_id: Optional[str]
    chunk_index: int
    chunk_text: str
    score: float          # cosine similarity [0.0, 1.0]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """
    Compute cosine similarity between two equal-length float vectors.
    Returns 0.0 if either vector is zero-length or the dot product is zero.
    """
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def top_k_chunks(
    query_vector: list[float],
    candidates: list[dict],  # rows from embeddings table (with 'embedding_vector' as bytes)
    top_k: int = 5,
    threshold: float = 0.0,
) -> list[ScoredChunk]:
    """
    Score all candidate rows by cosine similarity against query_vector,
    return the top_k results above threshold in descending score order.

    Expected keys per candidate dict:
        source_type, source_id, project_id, chunk_index, chunk_text, embedding_vector (bytes)
    """
    from app.rag.embedding import blob_to_vector

    scored: list[ScoredChunk] = []
    for row in candidates:
        blob = row.get("embedding_vector")
        if not blob:
            continue
        try:
            vec = blob_to_vector(blob)
        except Exception:
            continue
        score = cosine_similarity(query_vector, vec)
        if score >= threshold:
            scored.append(ScoredChunk(
                source_type=row["source_type"],
                source_id=row["source_id"],
                project_id=row.get("project_id"),
                chunk_index=row["chunk_index"],
                chunk_text=row["chunk_text"],
                score=score,
            ))

    scored.sort(key=lambda c: c.score, reverse=True)
    return scored[:top_k]
