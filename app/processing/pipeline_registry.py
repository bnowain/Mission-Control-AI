"""
Mission Control — Pipeline Registry (Phase 4)
=============================================
Central registration point for all processing pipelines.
Auto-registers OCR, Audio, and LLM pipelines at import time.
"""

from __future__ import annotations

from app.processing.pipelines.base import BasePipeline

_PIPELINES: dict[str, BasePipeline] = {}


def register(pipeline: BasePipeline) -> None:
    """Register a pipeline instance by name."""
    _PIPELINES[pipeline.name] = pipeline


def get_pipeline(name: str) -> BasePipeline:
    """
    Return pipeline by name.
    Raises KeyError if pipeline not registered.
    """
    if name not in _PIPELINES:
        raise KeyError(f"Pipeline {name!r} not registered. Available: {list(_PIPELINES)}")
    return _PIPELINES[name]


def list_pipelines() -> list[dict]:
    """Return [{name, available}] for all registered pipelines."""
    return [
        {"name": p.name, "available": p.available}
        for p in _PIPELINES.values()
    ]


# ---------------------------------------------------------------------------
# Auto-register all built-in pipelines at import time
# ---------------------------------------------------------------------------

def _register_defaults() -> None:
    from app.processing.pipelines.ocr import OCRPipeline
    from app.processing.pipelines.audio import AudioPipeline
    from app.processing.pipelines.llm_analysis import LLMAnalysisPipeline
    from app.processing.pipelines.web_ingest import WebIngestPipeline
    from app.processing.pipelines.embed_artifact import EmbedArtifactPipeline

    register(OCRPipeline())
    register(AudioPipeline())
    register(LLMAnalysisPipeline())
    register(WebIngestPipeline())
    register(EmbedArtifactPipeline())


_register_defaults()
