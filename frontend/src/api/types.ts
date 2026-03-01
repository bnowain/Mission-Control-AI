// TypeScript interfaces mirroring app/models/schemas.py
// Organized by domain

// ── Enumerations ──────────────────────────────────────────────────────────────

export type TaskType =
  | 'bug_fix' | 'refactor_small' | 'refactor_large'
  | 'architecture_design' | 'file_edit' | 'test_write'
  | 'docs' | 'generic'

export type TaskStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'

export type CapabilityClass =
  | 'fast_model' | 'coder_model' | 'reasoning_model'
  | 'heavy_model' | 'planner_model'

export type ContextTier = 'execution' | 'hybrid' | 'planning'

export type ModelSource =
  | 'cloud:anthropic' | 'cloud:openai' | 'cloud:deepseek'
  | 'local:ollama' | 'local:vllm' | 'cli:claude_code' | 'human'

export type ArtifactState =
  | 'RECEIVED' | 'PROCESSING' | 'PROCESSED'
  | 'AVAILABLE_FOR_EXPORT' | 'EXPORTED' | 'ARCHIVED'

export type PlanStatus = 'pending' | 'running' | 'completed' | 'failed' | 'replanning'

export type StepStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped'

export type PhaseStatus = 'pending' | 'running' | 'completed' | 'failed'

export type JobStatus = 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'RETRYING'

export type InstructionType =
  | 'project_rule' | 'naming_convention' | 'architecture_constraint'

// ── Health ────────────────────────────────────────────────────────────────────

export interface HealthResponse {
  status: string
  db_connectivity: boolean
  worker_status: string
  // Backend returns either a string or {available: boolean}
  gpu_status: string | { available: boolean } | null
  timestamp?: string
}

// ── System ────────────────────────────────────────────────────────────────────

export interface SystemStatusResponse {
  status: string
  schema_version: number
  active_task_count: number
  db_path: string
  service: string
  version: string
}

export interface SystemHardwareResponse {
  gpu_name: string | null
  vram_mb: number | null
  benchmark_tokens_per_sec: number | null
  available_capability_classes: string[]
}

// ── Tasks ─────────────────────────────────────────────────────────────────────

export interface TaskResponse {
  id: string
  project_id: string
  task_type: TaskType
  signature: string
  task_status: TaskStatus
  plan_id: string | null
  phase_id: string | null
  step_id: string | null
  created_at: string
  updated_at: string
}

export interface TaskCreate {
  project_id: string
  task_type: TaskType
  relevant_files?: string[]
  constraints?: string
  expected_output_type?: string
}

export interface TaskExecuteRequest {
  prompt: string
  project_id?: string
  force_model_class?: CapabilityClass
  force_context_tier?: ContextTier
}

export interface TaskExecuteResponse {
  task_id: string
  task_status: TaskStatus
  score: number | null
  passed: boolean | null
  response_text: string
  routing_decision: RoutingDecision
  duration_ms: number | null
  retry_count: number
  loop_count: number
  tokens_generated: number | null
  tokens_per_second: number | null
  thinking_text: string | null
  compile_success: boolean | null
  tests_passed: boolean | null
  lint_passed: boolean | null
  runtime_success: boolean | null
}

// ── Task execution streaming ───────────────────────────────────────────────────

export type TaskStreamEventType =
  | 'started' | 'loop_start' | 'model_response' | 'grading' | 'error' | 'cancelled'

export interface TaskStreamEvent {
  event_type: TaskStreamEventType
  timestamp: number
  // started
  task_type?: string
  project_id?: string
  // loop_start
  loop?: number
  retry_count?: number
  // model_response
  model?: string
  tier?: string
  tokens_generated?: number
  tokens_per_second?: number
  duration_ms?: number
  response_preview?: string
  // grading
  score?: number
  passed?: boolean
  compile_success?: boolean
  tests_passed?: boolean
  lint_passed?: boolean
  runtime_success?: boolean
  // error / cancelled
  content?: string
}

export interface TaskDoneEvent {
  task_id: string
  task_status: string
  score: number | null
  passed: boolean | null
  response_text: string
  thinking_text: string | null
  duration_ms: number | null
  loop_count: number
  retry_count: number
  tokens_generated: number | null
  tokens_per_second: number | null
  compile_success: boolean | null
  tests_passed: boolean | null
  lint_passed: boolean | null
  runtime_success: boolean | null
  model: string
  tier: string
  context_size: number
  routing_reason: string
  cancelled?: boolean
}

// ── Routing ───────────────────────────────────────────────────────────────────

export interface RoutingDecision {
  selected_model: string
  context_size: number
  context_tier: ContextTier
  temperature: number
  routing_reason: string
}

export interface RouterSelectRequest {
  task_type: TaskType
  retry_count?: number
  force_tier?: ContextTier
  force_class?: CapabilityClass
}

export interface RouterStatsRow {
  model_id: string
  task_type: string
  average_score: number | null
  average_retries: number | null
  success_rate: number | null
  sample_size: number | null
  last_updated: string
}

export interface RouterStatsResponse {
  rows: RouterStatsRow[]
  total: number
}

// ── Models ────────────────────────────────────────────────────────────────────

export interface ModelRecord {
  id: string
  display_name: string
  provider: string
  capability_class: CapabilityClass
  quant: string | null
  max_context: number | null
  benchmark_tokens_per_sec: number | null
  deprecated: boolean
  created_at: string
}

export interface ModelRunRequest {
  model_id: string
  messages: { role: string; content: string }[]
  temperature?: number
  max_tokens?: number
}

export interface ModelRunResponse {
  model_id: string
  response_text: string
  thinking_text: string | null
  tokens_in: number | null
  tokens_generated: number | null
  duration_ms: number | null
}

export interface ModelBenchmarkResponse {
  model_id: string
  tokens_per_second: number | null
  success: boolean
}

// ── Telemetry ─────────────────────────────────────────────────────────────────

export interface TelemetryRunsResponse {
  runs: Record<string, unknown>[]
  total: number
  limit: number
  offset: number
}

export interface TelemetryModelStats {
  model_id: string
  run_count: number
  average_score: number | null
  average_duration_ms: number | null
  pass_rate: number | null
}

export interface TelemetryModelsResponse {
  models: TelemetryModelStats[]
}

export interface TelemetryPerformanceResponse {
  total_runs: number
  total_tasks: number
  overall_pass_rate: number | null
  average_score: number | null
  average_duration_ms: number | null
}

export interface TelemetryHardwareResponse {
  profiles: Record<string, unknown>[]
}

// ── Codex ─────────────────────────────────────────────────────────────────────

export interface CodexEntry {
  id: string
  issue_signature: string
  category: string | null
  root_cause: string
  resolution: string
  prevention_guideline: string
  occurrence_count: number
  confidence_score: number
  verified: boolean
  model_source: ModelSource
  scope: string
  first_seen_at: string
  last_seen_at: string
}

export interface CodexSearchResult {
  id: string
  root_cause: string
  prevention_guideline: string
  category: string | null
  scope: string
  confidence_score: number
}

export interface CodexSearchResponse {
  results: CodexSearchResult[]
  total: number
  limit: number
  offset: number
}

export interface CodexStatsResponse {
  master_codex_count: number
  project_codex_count: number
  candidate_count: number
  promoted_count: number
}

export interface CodexCandidate {
  id: string
  task_id: string
  issue_signature: string
  proposed_root_cause: string | null
  proposed_resolution: string | null
  human_verified: boolean
  codex_promoted: boolean
  created_at: string
}

export interface CodexCandidateRequest {
  task_id: string
  issue_signature: string
  proposed_root_cause?: string
  proposed_resolution?: string
}

export interface CodexCandidateResponse {
  candidate_id: string
  task_id: string
  issue_signature: string
}

export interface CodexQueryRequest {
  issue_text: string
  project_id?: string
  limit?: number
}

export interface CodexPromoteRequest {
  candidate_id: string
  promoted_by?: ModelSource
  category?: string
  scope?: string
  confidence_score?: number
}

export interface CodexPromoteResponse {
  candidate_id: string
  master_codex_id: string
  action: string
}

export interface FailureClusterRow {
  id: string
  stack_trace_hash: string
  cluster_label: string | null
  occurrence_count: number
  first_seen_at: string
  last_seen_at: string
  codex_candidate_id: string | null
}

export interface FailureClustersResponse {
  clusters: FailureClusterRow[]
  total: number
}

// ── Plans ─────────────────────────────────────────────────────────────────────

export interface PlanStepCreate {
  step_title: string
  step_type?: string
  step_prompt?: string
  depends_on?: string[]
}

export interface PlanPhaseCreate {
  phase_title: string
  steps: PlanStepCreate[]
}

export interface PlanCreate {
  project_id: string
  plan_title: string
  phases: PlanPhaseCreate[]
}

export interface PlanStepResponse {
  id: string
  phase_id: string
  plan_id: string
  step_index: number
  step_title: string
  step_type: string
  step_status: StepStatus
  step_prompt: string | null
  depends_on: string[]
  task_id: string | null
  result_summary: string | null
  created_at: string
  updated_at: string
}

export interface PlanPhaseResponse {
  id: string
  plan_id: string
  phase_index: number
  phase_title: string
  phase_status: PhaseStatus
  steps: PlanStepResponse[]
  created_at: string
}

export interface PlanResponse {
  id: string
  project_id: string
  plan_title: string
  plan_status: PlanStatus
  plan_version: number
  plan_diff_history: Record<string, unknown>[]
  phases: PlanPhaseResponse[]
  created_at: string
  updated_at: string
}

export interface ReplanRequest {
  reason: string
  new_phases?: PlanPhaseCreate[]
}

// ── SQL ───────────────────────────────────────────────────────────────────────

export interface SqlQueryRequest {
  sql: string
  params?: unknown[]
  write_mode?: boolean
}

export interface SqlQueryResponse {
  columns: string[]
  rows: unknown[][]
  row_count: number
}

// ── Artifacts ─────────────────────────────────────────────────────────────────

export interface ArtifactResponse {
  id: string
  artifact_version: number
  pipeline_version: string | null
  processing_state: ArtifactState
  source_type: string | null
  source_hash: string | null
  file_path: string | null
  file_size_bytes: number | null
  mime_type: string | null
  page_url: string | null
  ingest_at: string
}

export interface ArtifactListResponse {
  artifacts: ArtifactResponse[]
  total: number
  limit: number
  offset: number
}

export interface ArtifactCreateRequest {
  source_type?: string
  source_hash?: string
  file_path?: string
  file_size_bytes?: number
  mime_type?: string
  page_url?: string
  pipeline_version?: string
}

export interface ArtifactExportResponse {
  raw: Record<string, unknown>
  extracted: Record<string, unknown>[]
  analysis: Record<string, unknown>[]
}

export interface ArtifactStateTransitionRequest {
  new_state: ArtifactState
}

export interface ProcessArtifactRequest {
  pipeline_name: string
  priority?: number
  payload?: Record<string, unknown>
}

// ── Workers / Jobs ────────────────────────────────────────────────────────────

export interface JobResponse {
  id: string
  artifact_id: string | null
  job_type: string
  job_status: JobStatus
  priority: number
  idempotency_key: string | null
  worker_id: string | null
  retry_count: number
  max_retries: number
  error_message: string | null
  payload_json: string | null
  result_json: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
}

export interface JobListResponse {
  jobs: JobResponse[]
  total: number
  limit: number
  offset: number
}

export interface WorkerStatsResponse {
  queued: number
  running: number
  completed: number
  failed: number
  retrying: number
  total: number
}

export interface PipelineAvailabilityResponse {
  name: string
  available: boolean
}

// ── Events / Webhooks ─────────────────────────────────────────────────────────

export interface EventResponse {
  id: string
  event_type: string
  artifact_id: string | null
  payload_json: string | null
  delivered: boolean
  created_at: string
}

export interface EventListResponse {
  events: EventResponse[]
  total: number
  limit: number
  offset: number
}

export interface WebhookCreateRequest {
  url: string
  event_types?: string[]
  secret?: string
}

export interface WebhookResponse {
  id: string
  url: string
  event_types: string[]
  active: boolean
  created_at: string
}

export interface WebhookListResponse {
  webhooks: WebhookResponse[]
}

// ── Validation ────────────────────────────────────────────────────────────────

export interface ValidateRequest {
  response_text: string
  task_type: TaskType
}

export interface GradingResult {
  score: number
  passed: boolean
  compile_success: boolean
  tests_passed: boolean
  lint_passed: boolean
  runtime_success: boolean
  retry_count: number
  human_flag: boolean
  downstream_impact_flag: boolean
  grade_components: Record<string, number>
}

// ── Governance ────────────────────────────────────────────────────────────────

export interface AuditLogEntry {
  id: number
  action: string
  actor: string | null
  target_type: string | null
  target_id: string | null
  detail: string | null
  created_at: string
}

export interface FeatureFlag {
  flag: string
  enabled: boolean
  project_id: string | null
  updated_at: string
}

export interface PromptRegistryEntry {
  id: string
  prompt_id: string
  version: string
  content: string
  task_type: string | null
  model_id: string | null
  created_at: string
}

// ── Instructions ──────────────────────────────────────────────────────────────

export interface InstructionCreate {
  project_id: string
  instruction_type: InstructionType
  content: string
}

export interface InstructionResponse {
  id: string
  project_id: string
  instruction_type: InstructionType
  content: string
  instruction_version: number
  active: boolean
  created_at: string
}

// ── RAG ───────────────────────────────────────────────────────────────────────

export interface RagSearchResult {
  chunk_id: string
  content: string
  similarity: number
  source_path: string | null
  project_id: string | null
  chunk_type: string | null
}

export interface RagSearchResponse {
  results: RagSearchResult[]
  total: number
  query: string
}

export interface RagStatsResponse {
  total_chunks: number
  projects: string[]
  chunk_types: Record<string, number>
}

// ── Planner ───────────────────────────────────────────────────────────────────

export type PlanEventType =
  | 'thinking' | 'output' | 'tool_use' | 'file_diff' | 'error' | 'done' | 'cancelled'

export interface PlanEvent {
  event_type: PlanEventType
  content: string
  timestamp: number
}

export interface PlanDoneEvent {
  response_text: string
  thinking_text: string | null
  duration_ms: number
  model_used: string
  cancelled: boolean
}

export interface PlanResult {
  response_text: string
  thinking_text: string | null
  events: PlanEvent[]
  duration_ms: number
  model_used: string
  cancelled: boolean
}

// ── Error ─────────────────────────────────────────────────────────────────────

export interface ErrorResponse {
  error: string
  detail: string
}
