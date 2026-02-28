"""
Mission Control — Artifact Embedding Pipeline (Phase 7)
========================================================
Reads extracted text from artifacts_extracted and embeds it.
Auto-triggered after ocr/audio/llm pipelines complete (via event subscriber).
Also triggered manually: POST /artifacts/{id}/process pipeline_name='embed_artifact'

Pipeline name: 'embed_artifact'
Emits: artifact.embedded
"""

from __future__ import annotations

import time

from app.processing.pipelines.base import BasePipeline


class EmbedArtifactPipeline(BasePipeline):
    """
    Embeds text from the artifacts_extracted table into the embeddings table.
    Available = True (Ollama checked at embed time, degrades gracefully).
    """

    name: str = "embed_artifact"
    available: bool = True

    def validate_input(self, artifact: dict) -> tuple[bool, str]:
        if not artifact.get("id"):
            return False, "embed_artifact requires artifact.id"
        return True, "ok"

    def process(self, artifact: dict, payload: dict) -> dict:
        start = time.monotonic()

        artifact_id = artifact.get("id", "")

        from app.rag.engine import get_rag_engine
        from app.processing.events import emit_event

        engine = get_rag_engine()
        chunks_stored = engine.index_artifact(artifact_id)

        processing_ms = int((time.monotonic() - start) * 1000)

        if artifact_id and chunks_stored > 0:
            try:
                emit_event("artifact.embedded", artifact_id=artifact_id, payload={
                    "source_type": "artifact",
                    "chunks_stored": chunks_stored,
                })
            except Exception:
                pass  # best-effort

        return {
            "extraction_data": {
                "available": True,
                "chunks_stored": chunks_stored,
                "artifact_id": artifact_id,
            },
            "confidence_score": 1.0 if chunks_stored > 0 else 0.0,
            "processing_ms": processing_ms,
        }
