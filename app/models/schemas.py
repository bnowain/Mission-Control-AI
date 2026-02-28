"""
Mission Control — Pydantic Schemas
====================================
Shared data models used across all subsystems.
These mirror the SQLite schema but are used for:
  - API request/response validation
  - Inter-module data passing
  - Telemetry serialisation
  - Grading Engine output

Naming rules (Rule 17):
  - task_status  not  status
  - codex_promoted  not  promoted
  - model_source required on all Codex entries
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class TaskType(str, Enum):
    BUG_FIX           = "bug_fix"
    REFACTOR_SMALL    = "refactor_small"
    REFACTOR_LARGE    = "refactor_large"
    ARCHITECTURE_DESIGN = "architecture_design"
    FILE_EDIT         = "file_edit"
    TEST_WRITE        = "test_write"
    DOCS              = "docs"
    GENERIC           = "generic"


class TaskStatus(str, Enum):
    PENDING    = "pending"
    RUNNING    = "running"
    COMPLETED  = "completed"
    FAILED     = "failed"
    CANCELLED  = "cancelled"


class CapabilityClass(str, Enum):
    FAST_MODEL      = "fast_model"
    REASONING_MODEL = "reasoning_model"
    PLANNER_MODEL   = "planner_model"


class ContextTier(str, Enum):
    EXECUTION = "execution"   # default  ~16k
    HYBRID    = "hybrid"      # mid      ~24k
    PLANNING  = "planning"    # large    ~32k


class ModelSource(str, Enum):
    CLOUD_ANTHROPIC = "cloud:anthropic"
    CLOUD_OPENAI    = "cloud:openai"
    LOCAL_OLLAMA    = "local:ollama"
    LOCAL_VLLM      = "local:vllm"
    HUMAN           = "human"


class ArtifactState(str, Enum):
    RECEIVED              = "RECEIVED"
    PROCESSING            = "PROCESSING"
    PROCESSED             = "PROCESSED"
    AVAILABLE_FOR_EXPORT  = "AVAILABLE_FOR_EXPORT"
    EXPORTED              = "EXPORTED"
    ARCHIVED              = "ARCHIVED"


# ---------------------------------------------------------------------------
# Core entities
# ---------------------------------------------------------------------------

class Project(BaseModel):
    id: str                         # ULID
    name: str
    created_at: datetime
    config_json: Optional[str] = None


class Model(BaseModel):
    id: str                         # LiteLLM format: "ollama/qwen2.5:32b"
    display_name: str
    provider: str                   # ollama | openai | anthropic | vllm
    capability_class: CapabilityClass
    quant: Optional[str] = None
    max_context: Optional[int] = None
    benchmark_tokens_per_sec: Optional[float] = None
    deprecated: bool = False
    created_at: datetime


class Task(BaseModel):
    id: str                         # ULID
    project_id: str
    task_type: TaskType
    signature: str                  # SHA256 fingerprint
    task_status: TaskStatus = TaskStatus.PENDING
    plan_id: Optional[str] = None
    phase_id: Optional[str] = None
    step_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class TaskCreate(BaseModel):
    project_id: str
    task_type: TaskType
    relevant_files: list[str] = Field(default_factory=list)
    constraints: Optional[str] = None
    expected_output_type: Optional[str] = None


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------

class GradingWeights(BaseModel):
    compile_success:    float = 40.0
    tests_pass:         float = 30.0
    lint_pass:          float = 15.0
    runtime_success:    float = 15.0
    retry_penalty:      float = 10.0   # per retry, capped at 30
    human_intervention: float = 20.0
    downstream_breakage: float = 25.0
    architecture_change: float = 30.0


class GradingResult(BaseModel):
    score:                    float = Field(ge=0, le=100)
    passed:                   bool
    compile_success:          bool
    tests_passed:             bool
    lint_passed:              bool
    runtime_success:          bool
    retry_count:              int
    human_flag:               bool
    downstream_impact_flag:   bool
    grade_components:         dict[str, float]  # audit trail


# ---------------------------------------------------------------------------
# Execution / Telemetry
# ---------------------------------------------------------------------------

class RoutingDecision(BaseModel):
    selected_model:    str              # capability class name
    context_size:      int
    context_tier:      ContextTier
    temperature:       float
    routing_reason:    str


class ExecutionLog(BaseModel):
    id:                     str         # ULID
    task_id:                str
    project_id:             str
    model_id:               str
    context_size:           int
    context_tier:           Optional[ContextTier] = None
    temperature:            Optional[float] = None
    tokens_generated:       Optional[int] = None
    tokens_per_second:      Optional[float] = None
    retries:                int = 0

    # Grading breakdown
    score:                  Optional[float] = None
    passed:                 Optional[bool] = None
    compile_success:        Optional[bool] = None
    tests_passed:           Optional[bool] = None
    lint_passed:            Optional[bool] = None
    runtime_success:        Optional[bool] = None

    # Penalty flags
    human_intervention:     bool = False
    downstream_impact:      bool = False

    duration_ms:            Optional[int] = None
    routing_reason:         Optional[str] = None
    stack_trace_hash:       Optional[str] = None

    # Replay fields
    prompt_id:              Optional[str] = None
    prompt_version:         Optional[str] = None
    injected_chunk_hashes:  Optional[list[str]] = None

    created_at:             datetime


# ---------------------------------------------------------------------------
# Hardware
# ---------------------------------------------------------------------------

class HardwareProfile(BaseModel):
    id: str
    gpu_name:                Optional[str] = None
    vram_mb:                 Optional[int] = None
    benchmark_tokens_per_sec: Optional[float] = None
    created_at:              datetime

    @property
    def available_capability_classes(self) -> list[CapabilityClass]:
        """Return which model classes this hardware can run."""
        vram = self.vram_mb or 0
        classes = [CapabilityClass.FAST_MODEL]
        if vram >= 20_000:
            classes.append(CapabilityClass.REASONING_MODEL)
        if vram >= 40_000:
            classes.append(CapabilityClass.PLANNER_MODEL)
        return classes


# ---------------------------------------------------------------------------
# Codex
# ---------------------------------------------------------------------------

class CodexEntry(BaseModel):
    id:                   str           # UUID
    issue_signature:      str
    category:             Optional[str] = None
    root_cause:           str
    resolution:           str
    prevention_guideline: str
    occurrence_count:     int = 1
    confidence_score:     float = 0.5
    verified:             bool = False
    model_source:         ModelSource
    scope:                str = "global"
    first_seen_at:        datetime
    last_seen_at:         datetime


class CodexCandidate(BaseModel):
    id:                  str            # UUID
    task_id:             str
    issue_signature:     str
    proposed_root_cause: Optional[str] = None
    proposed_resolution: Optional[str] = None
    human_verified:      bool = False
    codex_promoted:      bool = False   # NOT 'promoted' — Rule 17
    created_at:          datetime


class CodexSearchResult(BaseModel):
    """Atlas-compatible search response shape."""
    id:                   str
    root_cause:           str
    prevention_guideline: str
    category:             Optional[str] = None
    scope:                str
    confidence_score:     float


class CodexSearchResponse(BaseModel):
    """Required response shape for GET /api/codex/search (Atlas contract)."""
    results: list[CodexSearchResult]
    total:   int
    limit:   int
    offset:  int


# ---------------------------------------------------------------------------
# Escalation
# ---------------------------------------------------------------------------

class EscalationEvent(BaseModel):
    id:           str               # ULID
    task_id:      str
    from_context: Optional[int] = None
    to_context:   Optional[int] = None
    reason:       Optional[str] = None
    created_at:   datetime


# ---------------------------------------------------------------------------
# Context tiers
# ---------------------------------------------------------------------------

CONTEXT_TIER_SIZES: dict[ContextTier, int] = {
    ContextTier.EXECUTION: 16_384,
    ContextTier.HYBRID:    24_576,
    ContextTier.PLANNING:  32_768,
}

CAPABILITY_CLASSES: dict[CapabilityClass, dict] = {
    CapabilityClass.FAST_MODEL:      {"min_vram_mb": 0,      "default_context": 16_384},
    CapabilityClass.REASONING_MODEL: {"min_vram_mb": 20_000, "default_context": 24_576},
    CapabilityClass.PLANNER_MODEL:   {"min_vram_mb": 40_000, "default_context": 32_768},
}
