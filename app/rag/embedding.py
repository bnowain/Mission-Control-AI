"""
Mission Control — Embedding Client
=====================================
Wraps the Ollama /api/embeddings endpoint.
Returns None gracefully when Ollama is not running.

Vector serialization: struct.pack float32 (4 bytes per dimension).
No numpy dependency — compatible with minimal Python envs.
"""

from __future__ import annotations

import struct
from typing import Optional

import httpx

from app.core.logging import get_logger

log = get_logger("rag.embedding")

# Default Ollama embedding model — nomic-embed-text produces 768-dim vectors
DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"
DEFAULT_OLLAMA_URL = "http://localhost:11434"
_EMBED_TIMEOUT = 30.0


class EmbeddingClient:
    """
    Calls Ollama's /api/embeddings endpoint to produce float32 vectors.
    Falls back to None on any connection or model error — callers skip RAG.
    """

    def __init__(
        self,
        model: str = DEFAULT_EMBEDDING_MODEL,
        ollama_url: str = DEFAULT_OLLAMA_URL,
    ) -> None:
        self.model = model
        self._url = f"{ollama_url.rstrip('/')}/api/embeddings"

    def embed(self, text: str) -> Optional[list[float]]:
        """
        Embed a single text string.
        Returns list[float] on success, None if Ollama is unavailable.
        """
        if not text or not text.strip():
            return None
        try:
            with httpx.Client(timeout=_EMBED_TIMEOUT) as client:
                resp = client.post(
                    self._url,
                    json={"model": self.model, "prompt": text},
                )
            resp.raise_for_status()
            data = resp.json()
            vector = data.get("embedding")
            if not vector:
                log.warning("Ollama returned empty embedding", model=self.model)
                return None
            return [float(v) for v in vector]
        except httpx.ConnectError:
            log.warning(
                "Ollama not reachable — RAG will be skipped",
                url=self._url,
                model=self.model,
            )
            return None
        except Exception as exc:
            log.warning(
                "Embedding request failed",
                url=self._url,
                model=self.model,
                exc=str(exc),
            )
            return None

    def embed_batch(self, texts: list[str]) -> list[Optional[list[float]]]:
        """
        Embed a batch of texts. Returns a list of same length;
        None entries where embedding failed.
        Ollama has no native batch endpoint — calls embed() sequentially.
        """
        return [self.embed(t) for t in texts]


# ── Vector serialization ────────────────────────────────────────────────────

def vector_to_blob(vector: list[float]) -> bytes:
    """Serialize a float32 vector to bytes for SQLite BLOB storage."""
    return struct.pack(f"{len(vector)}f", *vector)


def blob_to_vector(blob: bytes) -> list[float]:
    """Deserialize a SQLite BLOB back to a float32 vector."""
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


# ── Module-level singleton ─────────────────────────────────────────────────

_client: Optional[EmbeddingClient] = None


def get_embedding_client() -> EmbeddingClient:
    global _client
    if _client is None:
        _client = EmbeddingClient()
    return _client
