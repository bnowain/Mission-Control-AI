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
    CODER_MODEL     = "coder_model"     # code-specialised (deepseek-coder-v2, qwen-coder)
    REASONING_MODEL = "reasoning_model"
    HEAVY_MODEL     = "heavy_model"     # optional 70B+ local tier
    PLANNER_MODEL   = "planner_model"


class ContextTier(str, Enum):
    EXECUTION = "execution"   # default  ~16k
    HYBRID    = "hybrid"      # mid      ~24k
    PLANNING  = "planning"    # large    ~32k


class ModelSource(str, Enum):
    CLOUD_ANTHROPIC  = "cloud:anthropic"
    CLOUD_OPENAI     = "cloud:openai"
    CLOUD_DEEPSEEK   = "cloud:deepseek"
    LOCAL_OLLAMA     = "local:ollama"
    LOCAL_VLLM       = "local:vllm"
    CLI_CLAUDE_CODE  = "cli:claude_code"
    HUMAN            = "human"


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
    tokens_in:              Optional[int] = None    # prompt tokens consumed
    tokens_generated:       Optional[int] = None    # completion tokens produced
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
# Execution result
# ---------------------------------------------------------------------------

class ExecutionResult(BaseModel):
    """
    Structured output from ModelExecutor.run().
    Carries everything the execution loop needs to grade, log, and escalate.
    """
    decision:          RoutingDecision
    response_text:     str
    thinking_text:     Optional[str] = None    # chain-of-thought (stripped before grading)
    tokens_in:         Optional[int] = None    # prompt tokens consumed
    tokens_generated:  Optional[int] = None    # completion tokens produced
    tokens_per_second: Optional[float] = None
    duration_ms:       Optional[int] = None
    retry_count:       int = 0
    escalation_count:  int = 0
    tool_calls_made:   int = 0                 # total tool calls in agent loop
    agent_iterations:  int = 0                 # agent loop iterations
    actual_model:      Optional[str] = None    # real model name from LiteLLM response


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
    CapabilityClass.CODER_MODEL:     {"min_vram_mb": 4_000,  "default_context": 16_384},
    CapabilityClass.REASONING_MODEL: {"min_vram_mb": 20_000, "default_context": 24_576},
    CapabilityClass.HEAVY_MODEL:     {"min_vram_mb": 40_000, "default_context": 32_768},
    CapabilityClass.PLANNER_MODEL:   {"min_vram_mb": 0,      "default_context": 32_768},  # cloud — no VRAM req
}


# ---------------------------------------------------------------------------
# API — shared error response
# ---------------------------------------------------------------------------

class ErrorResponse(BaseModel):
    """Standard error shape per master_codex.md §3.7."""
    error: str
    detail: str = ""


# ---------------------------------------------------------------------------
# API — Task endpoints
# ---------------------------------------------------------------------------

class TaskExecuteRequest(BaseModel):
    """POST /tasks/{id}/execute"""
    prompt: str
    project_id: Optional[str] = None
    force_model_class: Optional[CapabilityClass] = None
    force_context_tier: Optional[ContextTier] = None


class TaskResponse(BaseModel):
    """Full task row returned by POST /tasks and GET /tasks/{id}."""
    id: str
    project_id: str
    task_type: TaskType
    signature: str
    task_status: TaskStatus
    plan_id: Optional[str] = None
    phase_id: Optional[str] = None
    step_id: Optional[str] = None
    created_at: str
    updated_at: str


class TaskExecuteResponse(BaseModel):
    """Response from POST /tasks/{id}/execute."""
    task_id: str
    task_status: TaskStatus
    score: Optional[float] = None
    passed: Optional[bool] = None
    response_text: str
    routing_decision: RoutingDecision
    duration_ms: Optional[int] = None
    retry_count: int = 0
    loop_count: int = 1
    tokens_generated: Optional[int] = None
    tokens_per_second: Optional[float] = None
    thinking_text: Optional[str] = None
    compile_success: Optional[bool] = None
    tests_passed: Optional[bool] = None
    lint_passed: Optional[bool] = None
    runtime_success: Optional[bool] = None


# ---------------------------------------------------------------------------
# API — Router endpoints
# ---------------------------------------------------------------------------

class RouterSelectRequest(BaseModel):
    """POST /router/select"""
    task_type: TaskType
    retry_count: int = 0
    force_tier: Optional[ContextTier] = None
    force_class: Optional[CapabilityClass] = None


class RouterStatsRow(BaseModel):
    model_id: str
    task_type: str
    average_score: Optional[float] = None
    average_retries: Optional[float] = None
    success_rate: Optional[float] = None
    sample_size: Optional[int] = None
    last_updated: str


class RouterStatsResponse(BaseModel):
    rows: list[RouterStatsRow]
    total: int


# ---------------------------------------------------------------------------
# API — Model endpoints
# ---------------------------------------------------------------------------

class ModelRunRequest(BaseModel):
    """POST /models/run — direct model call."""
    model_id: str
    messages: list[dict]
    temperature: float = 0.1
    max_tokens: int = 2048


class ModelRunResponse(BaseModel):
    model_id: str
    response_text: str
    thinking_text: Optional[str] = None
    tokens_in: Optional[int] = None
    tokens_generated: Optional[int] = None
    duration_ms: Optional[int] = None


class ModelBenchmarkRequest(BaseModel):
    """POST /models/benchmark"""
    model_id: str
    api_base: Optional[str] = None


class ModelBenchmarkResponse(BaseModel):
    model_id: str
    tokens_per_second: Optional[float] = None
    success: bool


# ---------------------------------------------------------------------------
# API — Codex endpoints
# ---------------------------------------------------------------------------

class CodexQueryRequest(BaseModel):
    """POST /codex/query"""
    issue_text: str
    project_id: Optional[str] = None
    limit: int = Field(default=5, ge=1, le=50)


class CodexCandidateRequest(BaseModel):
    """POST /codex/candidate"""
    task_id: str
    issue_signature: str
    proposed_root_cause: Optional[str] = None
    proposed_resolution: Optional[str] = None


class CodexCandidateResponse(BaseModel):
    candidate_id: str
    task_id: str
    issue_signature: str


class CodexStatsResponse(BaseModel):
    master_codex_count: int
    project_codex_count: int
    candidate_count: int
    promoted_count: int


# ---------------------------------------------------------------------------
# API — Agent endpoints
# ---------------------------------------------------------------------------

class AgentRunRequest(BaseModel):
    """POST /agent/run and POST /agent/run/stream"""
    prompt: str
    working_dir: str
    project_id: str = "default"
    task_type: TaskType = TaskType.GENERIC
    force_model_class: Optional[CapabilityClass] = None
    force_context_tier: Optional[ContextTier] = None
    max_iterations: int = Field(default=50, ge=1, le=200)
    tools_enabled: bool = True
    repo_map_tokens: int = Field(default=1024, ge=0, le=8192)


class AgentRunResponse(BaseModel):
    """Response from POST /agent/run."""
    task_id: str
    task_status: TaskStatus
    score: Optional[float] = None
    passed: Optional[bool] = None
    response_text: str
    routing_decision: RoutingDecision
    duration_ms: Optional[int] = None
    retry_count: int = 0
    loop_count: int = 1
    tokens_generated: Optional[int] = None
    tokens_per_second: Optional[float] = None
    thinking_text: Optional[str] = None
    tool_calls_made: int = 0
    agent_iterations: int = 0
    compile_success: Optional[bool] = None
    tests_passed: Optional[bool] = None
    lint_passed: Optional[bool] = None
    runtime_success: Optional[bool] = None


class InterviewRequest(BaseModel):
    """POST /agent/interview"""
    prompt: str
    working_dir: str
    task_type: str = "generic"
    use_llm: bool = False  # if True, also call LLM to generate extra questions


class InterviewOption(BaseModel):
    label: str
    description: str


class InterviewQuestion(BaseModel):
    question: str
    header: str
    options: list[InterviewOption]


class InterviewResponse(BaseModel):
    """Response from POST /agent/interview"""
    questions: list[InterviewQuestion]


class AgentRespondRequest(BaseModel):
    """POST /agent/{session_id}/respond"""
    choice: str                        # "approve" | "deny" | "custom" | option label
    message: Optional[str] = None      # optional free-text


class AgentInjectRequest(BaseModel):
    """POST /agent/{session_id}/inject"""
    content: str = Field(..., min_length=1, max_length=4096)


# ---------------------------------------------------------------------------
# API — SQL query endpoint
# ---------------------------------------------------------------------------

class SqlQueryRequest(BaseModel):
    """POST /sql/query"""
    sql: str
    params: list = Field(default_factory=list)
    write_mode: bool = False


class SqlQueryResponse(BaseModel):
    columns: list[str]
    rows: list[list]
    row_count: int


# ---------------------------------------------------------------------------
# API — System endpoints
# ---------------------------------------------------------------------------

class SystemStatusResponse(BaseModel):
    status: str
    schema_version: int
    active_task_count: int
    db_path: str
    service: str = "mission-control"
    version: str = "0.1.0"


class SystemHardwareResponse(BaseModel):
    gpu_name: Optional[str] = None
    vram_mb: Optional[int] = None
    benchmark_tokens_per_sec: Optional[float] = None
    available_capability_classes: list[str]


# ---------------------------------------------------------------------------
# API — Telemetry endpoints
# ---------------------------------------------------------------------------

class TelemetryRunsResponse(BaseModel):
    runs: list[dict]
    total: int
    limit: int
    offset: int


class TelemetryModelStats(BaseModel):
    model_id: str
    run_count: int
    average_score: Optional[float] = None
    average_duration_ms: Optional[float] = None
    pass_rate: Optional[float] = None


class TelemetryModelsResponse(BaseModel):
    models: list[TelemetryModelStats]


class TelemetryPerformanceResponse(BaseModel):
    total_runs: int
    total_tasks: int
    overall_pass_rate: Optional[float] = None
    average_score: Optional[float] = None
    average_duration_ms: Optional[float] = None


class TelemetryHardwareResponse(BaseModel):
    profiles: list[dict]


# ---------------------------------------------------------------------------
# Phase 3 — Plan DAG schemas
# ---------------------------------------------------------------------------

class PlanStatus(str, Enum):
    PENDING    = "pending"
    RUNNING    = "running"
    COMPLETED  = "completed"
    FAILED     = "failed"
    REPLANNING = "replanning"


class StepStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    SKIPPED   = "skipped"


class PhaseStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"


class InstructionType(str, Enum):
    PROJECT_RULE            = "project_rule"
    NAMING_CONVENTION       = "naming_convention"
    ARCHITECTURE_CONSTRAINT = "architecture_constraint"


class PlanStepCreate(BaseModel):
    step_title:  str
    step_type:   str = "generic"
    step_prompt: Optional[str] = None
    depends_on:  list[str] = Field(default_factory=list)


class PlanPhaseCreate(BaseModel):
    phase_title: str
    steps: list[PlanStepCreate]


class PlanCreate(BaseModel):
    project_id: str
    plan_title:  str
    phases: list[PlanPhaseCreate]


class PlanStepResponse(BaseModel):
    id:             str
    phase_id:       str
    plan_id:        str
    step_index:     int
    step_title:     str
    step_type:      str
    step_status:    StepStatus
    step_prompt:    Optional[str] = None
    depends_on:     list[str] = Field(default_factory=list)
    task_id:        Optional[str] = None
    result_summary: Optional[str] = None
    created_at:     str
    updated_at:     str


class PlanPhaseResponse(BaseModel):
    id:           str
    plan_id:      str
    phase_index:  int
    phase_title:  str
    phase_status: PhaseStatus
    steps:        list[PlanStepResponse] = Field(default_factory=list)
    created_at:   str


class PlanResponse(BaseModel):
    id:               str
    project_id:       str
    plan_title:       str
    plan_status:      PlanStatus
    plan_version:     int
    plan_diff_history: list[dict] = Field(default_factory=list)
    phases:           list[PlanPhaseResponse] = Field(default_factory=list)
    created_at:       str
    updated_at:       str


class ReplanRequest(BaseModel):
    reason: str
    new_phases: Optional[list[PlanPhaseCreate]] = None


# ---------------------------------------------------------------------------
# Phase 3 — Context OS schemas
# ---------------------------------------------------------------------------

class ChunkRequest(BaseModel):
    file_path:  str
    content:    str
    project_id: str
    chunk_size: int = Field(default=2000, ge=200, le=10000)  # chars per chunk


class ChunkResponse(BaseModel):
    file_path:   str
    project_id:  str
    chunk_count: int
    chunk_ids:   list[str]


class CompressRequest(BaseModel):
    task_id:  str
    messages: list[dict]  # OpenAI-format conversation history
    max_tokens: int = Field(default=4000, ge=500, le=32000)


class CompressResponse(BaseModel):
    task_id:           str
    original_messages: int
    compressed_tokens: int
    summary:           str
    messages:          list[dict]  # compressed message list


class WorkingSetRequest(BaseModel):
    task_id:       str
    file_paths:    list[str]
    project_id:    str
    token_budget:  int = Field(default=8000, ge=1000, le=32000)


class WorkingSetResponse(BaseModel):
    task_id:       str
    chunk_count:   int
    total_tokens:  int
    chunks:        list[dict]


# ---------------------------------------------------------------------------
# Phase 3 — Replay schemas
# ---------------------------------------------------------------------------

class ReplayResponse(BaseModel):
    original_run_id:  str
    new_run_id:       str
    model_id:         str
    context_size:     int
    original_score:   Optional[float] = None
    new_score:        Optional[float] = None
    response_text:    str
    duration_ms:      Optional[int] = None


# ---------------------------------------------------------------------------
# Phase 3 — Instruction layer schemas
# ---------------------------------------------------------------------------

class InstructionCreate(BaseModel):
    project_id:       str
    instruction_type: InstructionType
    content:          str


class InstructionResponse(BaseModel):
    id:                  str
    project_id:          str
    instruction_type:    InstructionType
    content:             str
    instruction_version: int
    active:              bool
    created_at:          str


# ---------------------------------------------------------------------------
# Phase 3 — Failure clustering schemas
# ---------------------------------------------------------------------------

class FailureClusterRow(BaseModel):
    id:                 str
    stack_trace_hash:   str
    cluster_label:      Optional[str] = None
    occurrence_count:   int
    first_seen_at:      str
    last_seen_at:       str
    codex_candidate_id: Optional[str] = None


class FailureClustersResponse(BaseModel):
    clusters: list[FailureClusterRow]
    total:    int


# ---------------------------------------------------------------------------
# Phase 3 — Codex promote (real implementation)
# ---------------------------------------------------------------------------

class CodexPromoteRequest(BaseModel):
    candidate_id: str
    promoted_by:  ModelSource = ModelSource.HUMAN
    category:     Optional[str] = None
    scope:        str = "global"
    confidence_score: float = Field(default=0.7, ge=0.0, le=1.0)


class CodexPromoteResponse(BaseModel):
    candidate_id:   str
    master_codex_id: str
    action:         str  # "created" | "updated"


# ---------------------------------------------------------------------------
# Phase 4 — Processing Engine schemas
# ---------------------------------------------------------------------------

class JobStatus(str, Enum):
    QUEUED    = "QUEUED"
    RUNNING   = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED    = "FAILED"
    RETRYING  = "RETRYING"


class JobPriority(int, Enum):
    CRITICAL  = 1
    HIGH      = 3
    NORMAL    = 5
    LOW       = 7
    BACKFILL  = 100


class PipelineName(str, Enum):
    OCR          = "ocr"
    AUDIO        = "audio"
    IMAGE        = "image"
    LLM_ANALYSIS = "llm_analysis"


# Artifact ingest
class ArtifactCreateRequest(BaseModel):
    source_type:  Optional[str] = None   # pdf | audio | image | etc.
    source_hash:  Optional[str] = None   # SHA256 of raw file — dedup key
    file_path:    Optional[str] = None
    file_size_bytes: Optional[int] = None
    mime_type:    Optional[str] = None
    page_url:     Optional[str] = None   # human-browsable source (Rule 3)
    pipeline_version: Optional[str] = None


class ArtifactResponse(BaseModel):
    id:               str
    artifact_version: int
    pipeline_version: Optional[str] = None
    processing_state: ArtifactState
    source_type:      Optional[str] = None
    source_hash:      Optional[str] = None
    file_path:        Optional[str] = None
    file_size_bytes:  Optional[int] = None
    mime_type:        Optional[str] = None
    page_url:         Optional[str] = None
    ingest_at:        str


class ArtifactListResponse(BaseModel):
    artifacts: list[ArtifactResponse]
    total:     int
    limit:     int
    offset:    int


class ArtifactExportResponse(BaseModel):
    """Canonical 3-layer export for an artifact."""
    raw:       dict
    extracted: list[dict]
    analysis:  list[dict]


class ArtifactStateTransitionRequest(BaseModel):
    new_state: ArtifactState


class ProcessArtifactRequest(BaseModel):
    pipeline_name: PipelineName
    priority:      int = Field(default=5, ge=1, le=100)
    payload:       dict = Field(default_factory=dict)


# Jobs
class JobResponse(BaseModel):
    id:              str
    artifact_id:     Optional[str] = None
    job_type:        str
    job_status:      JobStatus
    priority:        int
    idempotency_key: Optional[str] = None
    worker_id:       Optional[str] = None
    retry_count:     int
    max_retries:     int
    error_message:   Optional[str] = None
    payload_json:    Optional[str] = None
    result_json:     Optional[str] = None
    created_at:      str
    started_at:      Optional[str] = None
    completed_at:    Optional[str] = None


class JobListResponse(BaseModel):
    jobs:   list[JobResponse]
    total:  int
    limit:  int
    offset: int


# Backfill
class BackfillRequest(BaseModel):
    pipeline_name: str
    simulate:      bool = False


class BackfillArtifactInfo(BaseModel):
    id:              str
    current_version: Optional[str] = None
    target_version:  str


class BackfillResponse(BaseModel):
    pipeline_name:  str
    eligible_count: int
    jobs_enqueued:  int   # 0 if simulate=True
    simulated:      bool
    artifacts:      list[BackfillArtifactInfo]


# Pipeline versions
class PipelineVersionResponse(BaseModel):
    id:                      str
    pipeline_name:           str
    engine_version:          str
    model_version:           Optional[str] = None
    prompt_template_version: Optional[str] = None
    chunking_version:        Optional[str] = None
    diarization_version:     Optional[str] = None
    active:                  bool
    created_at:              str


class PipelineVersionCreate(BaseModel):
    pipeline_name:           str
    engine_version:          str
    model_version:           Optional[str] = None
    prompt_template_version: Optional[str] = None
    chunking_version:        Optional[str] = None
    diarization_version:     Optional[str] = None


# Events
class EventResponse(BaseModel):
    id:           str
    event_type:   str
    artifact_id:  Optional[str] = None
    payload_json: Optional[str] = None
    delivered:    bool
    created_at:   str


class EventListResponse(BaseModel):
    events: list[EventResponse]
    total:  int
    limit:  int
    offset: int


# Webhooks
class WebhookCreateRequest(BaseModel):
    url:         str
    event_types: list[str] = Field(default_factory=list)
    secret:      Optional[str] = None


class WebhookResponse(BaseModel):
    id:          str
    url:         str
    event_types: list[str]
    active:      bool
    created_at:  str


class WebhookListResponse(BaseModel):
    webhooks: list[WebhookResponse]


# Worker stats
class WorkerStatsResponse(BaseModel):
    queued:    int
    running:   int
    completed: int
    failed:    int
    retrying:  int
    total:     int


# Pipeline availability
class PipelineAvailabilityResponse(BaseModel):
    name:      str
    available: bool
