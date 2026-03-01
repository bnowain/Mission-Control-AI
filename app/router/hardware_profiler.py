"""
Mission Control — Hardware Profiler
=====================================
Detects GPU, VRAM, and benchmarks tokens/sec at startup.
Result is cached in the database and in-process memory.

Pattern from: kb-llm-routing-providers.md → Surya/Docling hardware detection
Detection order: CUDA → MPS → CPU

The profiler determines which capability classes (fast/reasoning/planner)
are available on this hardware. The router uses this to filter the model list.
"""

import time
from datetime import datetime, timezone
from typing import Optional

from ulid import ULID

from app.core.logging import get_logger
from app.models.schemas import CapabilityClass, HardwareProfile

log = get_logger("hardware")

# VRAM thresholds (MB) — must match CAPABILITY_CLASSES in schemas.py
# HEAVY_MODEL and PLANNER_MODEL are omitted here — handled separately below:
#   HEAVY_MODEL: optional local tier, requires 40GB+ (may not be available)
#   PLANNER_MODEL: always available via cloud API regardless of VRAM
_VRAM_THRESHOLDS: dict[CapabilityClass, int] = {
    CapabilityClass.FAST_MODEL:      0,        # CPU-runnable (7B models)
    CapabilityClass.CODER_MODEL:     4_000,    # 4GB min (7B–16B coder models)
    CapabilityClass.REASONING_MODEL: 20_000,   # 20GB min (32B models)
    CapabilityClass.HEAVY_MODEL:     40_000,   # 40GB min (70B+ optional tier)
}

# Module-level cache — detected once per process
_cached_profile: Optional[HardwareProfile] = None


def detect_hardware() -> HardwareProfile:
    """
    Detect GPU/VRAM. Returns a HardwareProfile.
    Cached after first call — safe to call multiple times.
    """
    global _cached_profile
    if _cached_profile is not None:
        return _cached_profile

    gpu_name: Optional[str] = None
    vram_mb: int = 0

    try:
        import torch

        if torch.cuda.is_available():
            props    = torch.cuda.get_device_properties(0)
            gpu_name = props.name
            vram_mb  = props.total_memory // (1024 * 1024)
            log.info("CUDA GPU detected", gpu=gpu_name, vram_mb=vram_mb)

        elif torch.backends.mps.is_available():
            gpu_name = "Apple MPS"
            vram_mb  = 0    # Shared with system RAM — treat conservatively
            log.info("Apple MPS detected — treating as low VRAM")

        else:
            log.info("No GPU detected — CPU only")

    except ImportError:
        log.warning("torch not available — skipping GPU detection, defaulting to CPU")

    _cached_profile = HardwareProfile(
        id=str(ULID()),
        gpu_name=gpu_name,
        vram_mb=vram_mb if vram_mb > 0 else None,
        benchmark_tokens_per_sec=None,   # populated after benchmark
        created_at=datetime.now(timezone.utc),
    )
    return _cached_profile


def _ollama_reachable() -> bool:
    """Return True if a local Ollama server is responding."""
    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
        return True
    except Exception:  # noqa: BLE001
        return False


def available_capability_classes(profile: HardwareProfile) -> list[CapabilityClass]:
    """
    Return the list of capability classes this hardware can run locally.

    VRAM thresholds apply when running models directly via CUDA/MPS.
    When Ollama is reachable, Ollama manages its own memory — fast_model
    and coder_model are always available (Ollama runs on CPU if needed).
    Cloud planner is always available regardless of hardware.
    """
    vram = profile.vram_mb or 0
    classes = []

    for cls, threshold in _VRAM_THRESHOLDS.items():
        if vram >= threshold:
            classes.append(cls)

    # If Ollama is reachable, fast and coder models are always available
    # regardless of VRAM — Ollama handles its own memory management
    if _ollama_reachable():
        for cls in (CapabilityClass.FAST_MODEL, CapabilityClass.CODER_MODEL,
                    CapabilityClass.REASONING_MODEL):
            if cls not in classes:
                classes.append(cls)

    # Cloud planner is always available (API-based, no VRAM required)
    if CapabilityClass.PLANNER_MODEL not in classes:
        classes.append(CapabilityClass.PLANNER_MODEL)

    # HEAVY_MODEL is optional — only included if VRAM qualifies (40GB+)
    # It does NOT get auto-added like PLANNER_MODEL — no cloud fallback for heavy

    return classes


def benchmark_model(
    model_name: str,
    api_base: Optional[str] = None,
    sample_prompt: str = "Write a Python function that returns the sum of two numbers.",
    timeout: float = 30.0,
) -> Optional[float]:
    """
    Run a short completion to measure tokens/sec for a model.
    Returns tokens_per_second, or None if benchmark fails.

    This is called once per model at startup and cached in hardware_profiles.
    """
    try:
        import litellm

        start = time.perf_counter()
        kwargs: dict = {
            "model": model_name,
            "messages": [{"role": "user", "content": sample_prompt}],
            "max_tokens": 100,
            "timeout": timeout,
        }
        if api_base:
            kwargs["api_base"] = api_base

        response = litellm.completion(**kwargs)
        elapsed  = time.perf_counter() - start

        tokens_out = response.usage.completion_tokens or 0
        if elapsed > 0 and tokens_out > 0:
            tps = round(tokens_out / elapsed, 1)
            log.info("Benchmark complete", model=model_name, tokens_per_sec=tps)
            return tps

    except Exception as exc:
        log.warning("Benchmark failed", model=model_name, exc=exc)

    return None


def persist_profile(profile: HardwareProfile) -> None:
    """
    Write the hardware profile to the database.
    Called once at startup after detection + optional benchmark.
    """
    from app.database.init import get_connection

    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO hardware_profiles
                (id, gpu_name, vram_mb, benchmark_tokens_per_sec, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                profile.id,
                profile.gpu_name,
                profile.vram_mb,
                profile.benchmark_tokens_per_sec,
                profile.created_at.isoformat(),
            ),
        )
        conn.commit()
        log.info("Hardware profile persisted", profile_id=profile.id)
    finally:
        conn.close()
