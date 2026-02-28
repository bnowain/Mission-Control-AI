"""
Mission Control — Web Ingest Pipeline (Phase 7)
================================================
Fetches a URL, extracts text, chunks, and embeds it.
Stores clean text in artifacts_extracted.
Stores vectors in embeddings table.
Emits: artifact.embedded

Pipeline name: 'web_ingest'
Expects artifact.source_type = 'web_page' and artifact.page_url set.
"""

from __future__ import annotations

import time

from app.processing.pipelines.base import BasePipeline

# html2text availability check (hardware_profiler pattern)
try:
    import html2text  # noqa: F401
    _HTML2TEXT_AVAILABLE = True
except ImportError:
    _HTML2TEXT_AVAILABLE = False


class WebIngestPipeline(BasePipeline):
    """
    Fetches and embeds web pages as artifacts.
    Available when httpx is importable (always true — it's a core dep).
    """

    name: str = "web_ingest"
    available: bool = True  # httpx is always available; Ollama checked at embed time

    def validate_input(self, artifact: dict) -> tuple[bool, str]:
        url = artifact.get("page_url") or artifact.get("file_path")
        if not url:
            return False, "web_ingest requires page_url or file_path to be set"
        return True, "ok"

    def process(self, artifact: dict, payload: dict) -> dict:
        start = time.monotonic()

        url = artifact.get("page_url") or artifact.get("file_path", "")
        artifact_id = artifact.get("id", "")

        from app.rag.engine import get_rag_engine
        from app.processing.events import emit_event

        engine = get_rag_engine()
        chunks_stored = engine.index_web(
            url=url,
            project_id=payload.get("project_id"),
            artifact_id=artifact_id,
        )

        processing_ms = int((time.monotonic() - start) * 1000)

        if artifact_id:
            try:
                emit_event("artifact.embedded", artifact_id=artifact_id, payload={
                    "source_type": "web_page",
                    "chunks_stored": chunks_stored,
                    "url": url,
                })
            except Exception:
                pass  # event emission is best-effort

        return {
            "extraction_data": {
                "available": True,
                "url": url,
                "chunks_stored": chunks_stored,
                "html2text_available": _HTML2TEXT_AVAILABLE,
            },
            "confidence_score": 1.0 if chunks_stored > 0 else 0.0,
            "processing_ms": processing_ms,
        }
