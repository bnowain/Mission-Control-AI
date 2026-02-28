"""
Mission Control — Base Pipeline (Phase 4)
==========================================
Abstract base class for all processing pipelines.
Concrete pipelines override process() and validate_input().
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class BasePipeline(ABC):
    """
    Abstract base for OCR, Audio, LLM, and Image pipelines.

    Attributes:
        name      -- pipeline identifier (e.g. "ocr")
        available -- True if all ML dependencies are installed
    """

    name: str = "base"
    available: bool = False

    @abstractmethod
    def process(self, artifact: dict, payload: dict) -> dict:
        """
        Run the pipeline on an artifact.

        Args:
            artifact -- artifacts_raw row dict
            payload  -- additional parameters (from processing_jobs.payload_json)

        Returns dict with at minimum:
            extraction_data  : dict
            confidence_score : float | None
            processing_ms    : int | None
        """
        raise NotImplementedError

    def validate_input(self, artifact: dict) -> tuple[bool, str]:
        """
        Check whether this pipeline can process the artifact.

        Returns:
            (True, "ok") if valid
            (False, reason) if invalid
        """
        return True, "ok"
