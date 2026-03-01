"""
Mission Control — Database Initialisation
==========================================
Single source of truth for the SQLite schema.

Rules enforced here:
- WAL mode + foreign keys ON (global hard rules)
- task_status not status (Rule 17)
- ULID for task/log/job IDs, UUID for artifact/codex IDs
- FTS5 virtual tables over master_codex + project_codex (no ChromaDB)
- All embedding BLOB columns exist but are nullable — not used in Phase 1
- execution_logs includes full grading breakdown + replay fields
"""

import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger("mc.database")

DB_PATH = Path(__file__).resolve().parents[2] / "database" / "mission_control.db"

# ---------------------------------------------------------------------------
# Schema version — bump when making additive changes
# ---------------------------------------------------------------------------
SCHEMA_VERSION = 8

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL = """

-- =========================================================
-- PRAGMAS (applied at connection time, not stored in schema)
-- =========================================================
-- PRAGMA journal_mode=WAL;   ← applied in get_connection()
-- PRAGMA foreign_keys=ON;    ← applied in get_connection()


-- =========================================================
-- SCHEMA VERSION TRACKING
-- =========================================================

CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER NOT NULL,
    applied_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);


-- =========================================================
-- CORE ENTITIES
-- =========================================================

CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,                   -- ULID
    name        TEXT NOT NULL,
    created_at  DATETIME NOT NULL,
    config_json TEXT                                -- nullable JSON blob
);

CREATE TABLE IF NOT EXISTS models (
    id                       TEXT PRIMARY KEY,      -- LiteLLM format: "ollama/qwen2.5:32b"
    display_name             TEXT NOT NULL,
    provider                 TEXT NOT NULL,         -- ollama | openai | anthropic | vllm
    capability_class         TEXT NOT NULL,         -- fast_model | reasoning_model | planner_model
    quant                    TEXT,                  -- q4_k_m, q8_0, fp16, etc.
    max_context              INTEGER,
    benchmark_tokens_per_sec REAL,
    deprecated               INTEGER DEFAULT 0,
    created_at               DATETIME DEFAULT CURRENT_TIMESTAMP
);


-- =========================================================
-- TASK DEFINITIONS
-- =========================================================

CREATE TABLE IF NOT EXISTS tasks (
    id          TEXT PRIMARY KEY,                   -- ULID
    project_id  TEXT NOT NULL,
    task_type   TEXT NOT NULL,                      -- bug_fix | refactor_small | refactor_large | architecture_design | ...
    signature   TEXT NOT NULL,                      -- SHA256 fingerprint of task content
    task_status TEXT NOT NULL DEFAULT 'pending',    -- pending | running | completed | failed | cancelled
                                                    -- NOTE: 'task_status' not 'status' — Rule 17 compliance
    plan_id     TEXT,                               -- nullable — set when part of a plan
    phase_id    TEXT,                               -- nullable
    step_id     TEXT,                               -- nullable
    created_at  DATETIME NOT NULL,
    updated_at  DATETIME NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE INDEX IF NOT EXISTS idx_tasks_project   ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_signature ON tasks(signature);
CREATE INDEX IF NOT EXISTS idx_tasks_status    ON tasks(task_status);
CREATE INDEX IF NOT EXISTS idx_tasks_type      ON tasks(task_type);


-- =========================================================
-- CHUNKING SYSTEM
-- =========================================================

CREATE TABLE IF NOT EXISTS file_chunks (
    id          TEXT PRIMARY KEY,                   -- UUID (content-addressed)
    project_id  TEXT NOT NULL,
    file_path   TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    chunk_hash  TEXT NOT NULL,                      -- SHA256 of content
    content     TEXT NOT NULL,
    summary     TEXT,                               -- nullable — LLM-generated summary
    embedding   BLOB,                               -- nullable — Phase 1: unused
    created_at  DATETIME NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE INDEX IF NOT EXISTS idx_chunks_project_file ON file_chunks(project_id, file_path);
CREATE INDEX IF NOT EXISTS idx_chunks_hash         ON file_chunks(chunk_hash);

CREATE TABLE IF NOT EXISTS chunk_dependencies (
    id                 TEXT PRIMARY KEY,
    parent_chunk_id    TEXT NOT NULL,
    dependent_chunk_id TEXT NOT NULL,
    FOREIGN KEY (parent_chunk_id)    REFERENCES file_chunks(id),
    FOREIGN KEY (dependent_chunk_id) REFERENCES file_chunks(id)
);


-- =========================================================
-- EXECUTION LOGS (TELEMETRY)
-- Full grading breakdown + replay fields included.
-- See: kb-execution-validation-telemetry.md
-- =========================================================

CREATE TABLE IF NOT EXISTS execution_logs (
    id                    TEXT PRIMARY KEY,         -- ULID
    task_id               TEXT NOT NULL,
    project_id            TEXT NOT NULL,
    model_id              TEXT NOT NULL,
    context_size          INTEGER NOT NULL,
    context_tier          TEXT,                     -- execution | hybrid | planning
    temperature           REAL,
    tokens_in             INTEGER,                  -- prompt tokens consumed
    tokens_generated      INTEGER,                  -- completion tokens produced
    tokens_per_second     REAL,
    retries               INTEGER DEFAULT 0,

    -- Score + grading breakdown (GradingEngine output)
    score                 REAL,                     -- 0-100 composite
    passed                INTEGER,                  -- 0/1 — score >= passing_threshold
    compile_success       INTEGER,                  -- 0/1
    tests_passed          INTEGER,                  -- 0/1
    lint_passed           INTEGER,                  -- 0/1
    runtime_success       INTEGER,                  -- 0/1

    -- Penalty flags
    human_intervention    INTEGER DEFAULT 0,        -- 0/1
    downstream_impact     INTEGER DEFAULT 0,        -- 0/1

    -- Timing
    duration_ms           INTEGER,

    -- Routing audit
    routing_reason        TEXT,                     -- why this model/config was selected

    -- Failure dedup (n8n pattern)
    stack_trace_hash      TEXT,                     -- SHA1 of normalised frames

    -- Replay fields (required for POST /runs/{id}/replay)
    prompt_id             TEXT,                     -- FK → prompt_registry
    prompt_version        TEXT,                     -- snapshot of version string
    injected_chunk_hashes TEXT,                     -- JSON array of chunk SHA256s

    -- Phase 7 RAG telemetry
    rag_chunks_injected   INTEGER DEFAULT 0,        -- count of RAG chunks prepended
    rag_source_ids        TEXT,                     -- JSON array of source IDs

    created_at            DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (task_id)   REFERENCES tasks(id),
    FOREIGN KEY (project_id) REFERENCES projects(id),
    FOREIGN KEY (model_id)  REFERENCES models(id)
);

CREATE INDEX IF NOT EXISTS idx_logs_task       ON execution_logs(task_id);
CREATE INDEX IF NOT EXISTS idx_logs_model      ON execution_logs(model_id);
CREATE INDEX IF NOT EXISTS idx_logs_score      ON execution_logs(score);
CREATE INDEX IF NOT EXISTS idx_logs_hash       ON execution_logs(stack_trace_hash);
CREATE INDEX IF NOT EXISTS idx_logs_created    ON execution_logs(created_at);


-- =========================================================
-- FAILURE TRACKING
-- =========================================================

CREATE TABLE IF NOT EXISTS failure_events (
    id               TEXT PRIMARY KEY,              -- ULID
    task_id          TEXT NOT NULL,
    error_type       TEXT,
    stack_trace_hash TEXT,                          -- SHA1 — join to execution_logs for clustering
    file_path        TEXT,
    diff_hash        TEXT,
    created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);

CREATE INDEX IF NOT EXISTS idx_failure_hash    ON failure_events(stack_trace_hash);
CREATE INDEX IF NOT EXISTS idx_failure_task    ON failure_events(task_id);


-- =========================================================
-- ESCALATION EVENTS
-- =========================================================

CREATE TABLE IF NOT EXISTS escalation_events (
    id           TEXT PRIMARY KEY,                  -- ULID
    task_id      TEXT NOT NULL,
    from_context INTEGER,                           -- tokens
    to_context   INTEGER,                           -- tokens
    reason       TEXT,
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);

CREATE INDEX IF NOT EXISTS idx_escalation_task ON escalation_events(task_id);


-- =========================================================
-- ROUTING PERFORMANCE STATS
-- Aggregated periodically by background job.
-- =========================================================

CREATE TABLE IF NOT EXISTS routing_stats (
    id            TEXT PRIMARY KEY,
    model_id      TEXT NOT NULL,
    task_type     TEXT NOT NULL,
    average_score REAL,
    average_retries REAL,
    success_rate  REAL,
    sample_size   INTEGER,
    last_updated  DATETIME NOT NULL,
    FOREIGN KEY (model_id) REFERENCES models(id)
);

CREATE INDEX IF NOT EXISTS idx_routing_model_task ON routing_stats(model_id, task_type);


-- =========================================================
-- HARDWARE PROFILES
-- =========================================================

CREATE TABLE IF NOT EXISTS hardware_profiles (
    id                       TEXT PRIMARY KEY,
    gpu_name                 TEXT,
    vram_mb                  INTEGER,
    benchmark_tokens_per_sec REAL,
    created_at               DATETIME DEFAULT CURRENT_TIMESTAMP
);


-- =========================================================
-- MASTER CODEX (GLOBAL MEMORY)
-- model_source is required — foundation of Supreme Master Codex.
-- Embeddings nullable — Phase 1 uses FTS5, not vector search.
-- =========================================================

CREATE TABLE IF NOT EXISTS master_codex (
    id                  TEXT PRIMARY KEY,           -- UUID
    issue_signature     TEXT NOT NULL,
    category            TEXT,
    root_cause          TEXT NOT NULL,
    resolution          TEXT NOT NULL,
    prevention_guideline TEXT NOT NULL,
    occurrence_count    INTEGER DEFAULT 1,
    confidence_score    REAL DEFAULT 0.5,
    verified            INTEGER DEFAULT 0,
    model_source        TEXT NOT NULL,              -- cloud:anthropic | local:ollama | local:vllm | human
    scope               TEXT NOT NULL DEFAULT 'global',
    embedding           BLOB,                       -- nullable — Phase 1: unused
    first_seen_at       DATETIME NOT NULL,
    last_seen_at        DATETIME NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_master_signature ON master_codex(issue_signature);
CREATE INDEX IF NOT EXISTS idx_master_source    ON master_codex(model_source);
CREATE INDEX IF NOT EXISTS idx_master_verified  ON master_codex(verified);


-- =========================================================
-- PROJECT-SPECIFIC CODEX
-- =========================================================

CREATE TABLE IF NOT EXISTS project_codex (
    id                TEXT PRIMARY KEY,             -- UUID
    project_id        TEXT NOT NULL,
    issue_signature   TEXT NOT NULL,
    module_path       TEXT,
    root_cause        TEXT NOT NULL,
    resolution        TEXT NOT NULL,
    architecture_note TEXT,
    occurrence_count  INTEGER DEFAULT 1,
    verified          INTEGER DEFAULT 0,
    model_source      TEXT NOT NULL,                -- cloud:anthropic | local:ollama | local:vllm | human
    embedding         BLOB,                         -- nullable — Phase 1: unused
    first_seen_at     DATETIME NOT NULL,
    last_seen_at      DATETIME NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE INDEX IF NOT EXISTS idx_project_codex_project   ON project_codex(project_id);
CREATE INDEX IF NOT EXISTS idx_project_codex_signature ON project_codex(issue_signature);


-- =========================================================
-- CODEX FTS (Full-Text Search)
-- No ChromaDB — SQLite FTS5 for internal Codex search.
-- Atlas handles ecosystem-level semantic search via LazyChroma.
-- See: architecture-decisions.md → No Own ChromaDB
-- =========================================================

CREATE VIRTUAL TABLE IF NOT EXISTS master_codex_fts USING fts5(
    root_cause,
    prevention_guideline,
    category,
    content='master_codex',
    content_rowid='rowid'
);

CREATE VIRTUAL TABLE IF NOT EXISTS project_codex_fts USING fts5(
    root_cause,
    prevention_guideline,
    module_path,
    content='project_codex',
    content_rowid='rowid'
);

-- Keep FTS in sync with base tables
CREATE TRIGGER IF NOT EXISTS master_codex_fts_insert AFTER INSERT ON master_codex BEGIN
    INSERT INTO master_codex_fts(rowid, root_cause, prevention_guideline, category)
    VALUES (new.rowid, new.root_cause, new.prevention_guideline, new.category);
END;

CREATE TRIGGER IF NOT EXISTS master_codex_fts_update AFTER UPDATE ON master_codex BEGIN
    INSERT INTO master_codex_fts(master_codex_fts, rowid, root_cause, prevention_guideline, category)
    VALUES ('delete', old.rowid, old.root_cause, old.prevention_guideline, old.category);
    INSERT INTO master_codex_fts(rowid, root_cause, prevention_guideline, category)
    VALUES (new.rowid, new.root_cause, new.prevention_guideline, new.category);
END;

CREATE TRIGGER IF NOT EXISTS master_codex_fts_delete AFTER DELETE ON master_codex BEGIN
    INSERT INTO master_codex_fts(master_codex_fts, rowid, root_cause, prevention_guideline, category)
    VALUES ('delete', old.rowid, old.root_cause, old.prevention_guideline, old.category);
END;

CREATE TRIGGER IF NOT EXISTS project_codex_fts_insert AFTER INSERT ON project_codex BEGIN
    INSERT INTO project_codex_fts(rowid, root_cause, prevention_guideline, module_path)
    VALUES (new.rowid, new.root_cause, new.prevention_guideline, new.module_path);
END;

CREATE TRIGGER IF NOT EXISTS project_codex_fts_update AFTER UPDATE ON project_codex BEGIN
    INSERT INTO project_codex_fts(project_codex_fts, rowid, root_cause, prevention_guideline, module_path)
    VALUES ('delete', old.rowid, old.root_cause, old.prevention_guideline, old.module_path);
    INSERT INTO project_codex_fts(rowid, root_cause, prevention_guideline, module_path)
    VALUES (new.rowid, new.root_cause, new.prevention_guideline, new.module_path);
END;

CREATE TRIGGER IF NOT EXISTS project_codex_fts_delete AFTER DELETE ON project_codex BEGIN
    INSERT INTO project_codex_fts(project_codex_fts, rowid, root_cause, prevention_guideline, module_path)
    VALUES ('delete', old.rowid, old.root_cause, old.prevention_guideline, old.module_path);
END;


-- =========================================================
-- CODEX PROMOTION CANDIDATES
-- =========================================================

CREATE TABLE IF NOT EXISTS codex_candidates (
    id                   TEXT PRIMARY KEY,          -- UUID
    task_id              TEXT NOT NULL,
    issue_signature      TEXT NOT NULL,
    proposed_root_cause  TEXT,
    proposed_resolution  TEXT,
    human_verified       INTEGER DEFAULT 0,
    codex_promoted       INTEGER DEFAULT 0,         -- NOT 'promoted' — Rule 17 clarity
    created_at           DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);

CREATE INDEX IF NOT EXISTS idx_candidates_task      ON codex_candidates(task_id);
CREATE INDEX IF NOT EXISTS idx_candidates_promoted  ON codex_candidates(codex_promoted);


-- =========================================================
-- CODEX SUPERSESSIONS
-- Old entries are NEVER deleted — marked superseded, remain queryable.
-- Foundation of Supreme Master Codex merge (post-v1).
-- =========================================================

CREATE TABLE IF NOT EXISTS codex_supersessions (
    id                    TEXT PRIMARY KEY,         -- UUID
    old_entry_id          TEXT NOT NULL,
    new_entry_id          TEXT NOT NULL,
    reason                TEXT NOT NULL,
    superseded_by_source  TEXT NOT NULL,            -- who made the call
    created_at            DATETIME DEFAULT CURRENT_TIMESTAMP
);


-- =========================================================
-- ARTIFACT REGISTRY (3-layer)
-- Phase 1: table exists but ingestion not implemented.
-- page_url is nullable but MUST be populated on external ingest (Rule 3).
-- =========================================================

CREATE TABLE IF NOT EXISTS artifacts_raw (
    id               TEXT PRIMARY KEY,              -- UUID (content-addressed)
    artifact_version INTEGER DEFAULT 1,
    pipeline_version TEXT,
    schema_version   TEXT,
    processing_state TEXT NOT NULL DEFAULT 'RECEIVED',
                                                    -- RECEIVED | PROCESSING | PROCESSED |
                                                    -- AVAILABLE_FOR_EXPORT | EXPORTED | ARCHIVED
    source_type      TEXT,                          -- pdf | audio | image | etc.
    source_hash      TEXT,                          -- SHA256 of raw file — dedup key
    file_path        TEXT,
    file_size_bytes  INTEGER,
    mime_type        TEXT,
    page_url         TEXT,                          -- nullable — human-browsable source URL
                                                    -- MUST be set for any external ingest (Rule 3)
    is_cold_storage  INTEGER DEFAULT 0,             -- Phase 8: 1 = archived to cold storage
    archived_at      DATETIME,                      -- Phase 8: when artifact was archived
    ingest_at        DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_artifacts_hash  ON artifacts_raw(source_hash);
CREATE INDEX IF NOT EXISTS idx_artifacts_state ON artifacts_raw(processing_state);


-- =========================================================
-- PROMPT REGISTRY
-- Every LLM call must reference a versioned prompt.
-- Backfill eligibility: detect prompt version change.
-- =========================================================

CREATE TABLE IF NOT EXISTS prompt_registry (
    id            TEXT PRIMARY KEY,                 -- UUID
    name          TEXT NOT NULL,
    version       TEXT NOT NULL,
    template_text TEXT NOT NULL,
    template_hash TEXT NOT NULL,                    -- SHA256 — change detection
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    deprecated    INTEGER DEFAULT 0,
    UNIQUE(name, version)
);


-- =========================================================
-- AUDIT LOG (immutable)
-- =========================================================

CREATE TABLE IF NOT EXISTS audit_log (
    id            TEXT PRIMARY KEY,                 -- ULID
    timestamp     DATETIME NOT NULL,
    api_key_id    TEXT,
    action_type   TEXT NOT NULL,                    -- artifact.uploaded | task.created |
                                                    -- codex.promoted | sql.query.executed | ...
    artifact_id   TEXT,
    task_id       TEXT,
    ip_address    TEXT,
    result        TEXT,                             -- success | failure
    metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_timestamp   ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_action_type ON audit_log(action_type);
CREATE INDEX IF NOT EXISTS idx_audit_task        ON audit_log(task_id);


-- =========================================================
-- FEATURE FLAGS
-- =========================================================

CREATE TABLE IF NOT EXISTS feature_flags (
    flag_name          TEXT PRIMARY KEY,
    enabled            INTEGER DEFAULT 0,
    rollout_percentage INTEGER DEFAULT 100,
    project_scope      TEXT                         -- nullable — project_id to scope to one project
);

-- Seed default flags
INSERT OR IGNORE INTO feature_flags (flag_name, enabled) VALUES
    ('codex_auto_promote',    0),
    ('adaptive_router_v2',    0),
    ('handwriting_v2',        0),
    ('diarization_v3',        0);


-- =========================================================
-- PLAN DAG (Phase 3)
-- plans → plan_phases → plan_steps (dependency graph)
-- =========================================================

CREATE TABLE IF NOT EXISTS plans (
    id               TEXT PRIMARY KEY,          -- ULID
    project_id       TEXT NOT NULL,
    plan_title       TEXT NOT NULL,
    plan_status      TEXT NOT NULL DEFAULT 'pending',
                                                -- pending | running | completed | failed | replanning
    plan_version     INTEGER DEFAULT 1,
    plan_diff_history TEXT DEFAULT '[]',        -- JSON array of {version, diff, changed_at}
    created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE INDEX IF NOT EXISTS idx_plans_project ON plans(project_id);
CREATE INDEX IF NOT EXISTS idx_plans_status  ON plans(plan_status);


CREATE TABLE IF NOT EXISTS plan_phases (
    id           TEXT PRIMARY KEY,              -- ULID
    plan_id      TEXT NOT NULL,
    phase_index  INTEGER NOT NULL,
    phase_title  TEXT NOT NULL,
    phase_status TEXT NOT NULL DEFAULT 'pending',
                                                -- pending | running | completed | failed
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (plan_id) REFERENCES plans(id)
);

CREATE INDEX IF NOT EXISTS idx_phases_plan ON plan_phases(plan_id);


CREATE TABLE IF NOT EXISTS plan_steps (
    id             TEXT PRIMARY KEY,            -- ULID
    phase_id       TEXT NOT NULL,
    plan_id        TEXT NOT NULL,
    step_index     INTEGER NOT NULL,
    step_title     TEXT NOT NULL,
    step_type      TEXT NOT NULL DEFAULT 'generic',
    step_status    TEXT NOT NULL DEFAULT 'pending',
                                                -- pending | running | completed | failed | skipped
    step_prompt    TEXT,                        -- task prompt for this step
    depends_on     TEXT NOT NULL DEFAULT '[]',  -- JSON array of step_ids
    task_id        TEXT,                        -- nullable: linked when step executes
    result_summary TEXT,                        -- brief result for diff history
    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (phase_id) REFERENCES plan_phases(id),
    FOREIGN KEY (plan_id)  REFERENCES plans(id)
);

CREATE INDEX IF NOT EXISTS idx_steps_phase  ON plan_steps(phase_id);
CREATE INDEX IF NOT EXISTS idx_steps_plan   ON plan_steps(plan_id);
CREATE INDEX IF NOT EXISTS idx_steps_status ON plan_steps(step_status);


-- =========================================================
-- EXECUTION CHECKPOINTS (LangGraph CheckpointTuple pattern — native)
-- thread_id = plan execution session
-- =========================================================

CREATE TABLE IF NOT EXISTS execution_checkpoints (
    id              TEXT PRIMARY KEY,           -- ULID
    thread_id       TEXT NOT NULL,              -- plan_id (session identifier)
    checkpoint_key  TEXT NOT NULL,              -- step_id or phase_id
    state_json      TEXT NOT NULL,              -- full serialized state dict
    checkpoint_type TEXT NOT NULL DEFAULT 'step', -- step | phase | plan
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_checkpoints_thread ON execution_checkpoints(thread_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_checkpoints_thread_key
    ON execution_checkpoints(thread_id, checkpoint_key);


-- =========================================================
-- FAILURE CLUSTERS (Phase 3)
-- Groups failure_events by stack_trace_hash
-- =========================================================

CREATE TABLE IF NOT EXISTS failure_clusters (
    id                  TEXT PRIMARY KEY,       -- ULID
    stack_trace_hash    TEXT NOT NULL UNIQUE,
    cluster_label       TEXT,
    occurrence_count    INTEGER DEFAULT 1,
    first_seen_at       DATETIME NOT NULL,
    last_seen_at        DATETIME NOT NULL,
    codex_candidate_id  TEXT                    -- nullable: linked candidate
);

CREATE INDEX IF NOT EXISTS idx_clusters_hash ON failure_clusters(stack_trace_hash);


-- =========================================================
-- PROJECT INSTRUCTIONS (Persistent Instruction Layer)
-- =========================================================

CREATE TABLE IF NOT EXISTS project_instructions (
    id                   TEXT PRIMARY KEY,      -- UUID
    project_id           TEXT NOT NULL,
    instruction_type     TEXT NOT NULL,         -- project_rule | naming_convention | architecture_constraint
    content              TEXT NOT NULL,
    instruction_version  INTEGER DEFAULT 1,
    active               INTEGER DEFAULT 1,     -- 0/1 soft delete
    created_at           DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at           DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE INDEX IF NOT EXISTS idx_instructions_project ON project_instructions(project_id);
CREATE INDEX IF NOT EXISTS idx_instructions_type    ON project_instructions(instruction_type);


-- =========================================================
-- CONTEXT COMPRESSIONS (Phase 3)
-- Audit trail of context compression events
-- =========================================================

CREATE TABLE IF NOT EXISTS context_compressions (
    id                TEXT PRIMARY KEY,         -- UUID
    task_id           TEXT NOT NULL,
    compression_round INTEGER DEFAULT 1,
    original_tokens   INTEGER,
    compressed_tokens INTEGER,
    summary_text      TEXT,
    created_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);

CREATE INDEX IF NOT EXISTS idx_compressions_task ON context_compressions(task_id);


-- =========================================================
-- ARTIFACTS EXTRACTED (Layer 2: structured extraction)
-- Phase 4: populated by OCR/Audio/Image pipelines.
-- =========================================================

CREATE TABLE IF NOT EXISTS artifacts_extracted (
    id               TEXT PRIMARY KEY,              -- UUID
    artifact_id      TEXT NOT NULL,
    pipeline_name    TEXT NOT NULL,                 -- ocr | audio | image | llm_analysis
    pipeline_version TEXT NOT NULL,
    model_version    TEXT,
    engine_version   TEXT NOT NULL DEFAULT '1.0',
    extraction_data  TEXT NOT NULL DEFAULT '{}',    -- JSON blob
    confidence_score REAL,
    retry_count      INTEGER DEFAULT 0,
    gpu_used         TEXT,
    processing_ms    INTEGER,
    created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (artifact_id) REFERENCES artifacts_raw(id)
);

CREATE INDEX IF NOT EXISTS idx_extracted_artifact ON artifacts_extracted(artifact_id);


-- =========================================================
-- ARTIFACTS ANALYSIS (Layer 3: LLM analysis outputs)
-- Phase 4: populated by LLMAnalysisPipeline.
-- =========================================================

CREATE TABLE IF NOT EXISTS artifacts_analysis (
    id                    TEXT PRIMARY KEY,         -- UUID
    artifact_id           TEXT NOT NULL,
    model_id              TEXT,
    prompt_id             TEXT,
    prompt_version        TEXT,
    engine_version        TEXT NOT NULL DEFAULT '1.0',
    summary_text          TEXT,
    tags_json             TEXT DEFAULT '[]',
    reasoning_text        TEXT,
    validation_score      REAL,
    routing_decision_json TEXT DEFAULT '{}',
    processing_ms         INTEGER,
    created_at            DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (artifact_id) REFERENCES artifacts_raw(id)
);

CREATE INDEX IF NOT EXISTS idx_analysis_artifact ON artifacts_analysis(artifact_id);


-- =========================================================
-- PROCESSING JOBS (Worker Scheduler)
-- ULID for job IDs per schema-decisions.md.
-- =========================================================

CREATE TABLE IF NOT EXISTS processing_jobs (
    id               TEXT PRIMARY KEY,              -- ULID
    artifact_id      TEXT,
    job_type         TEXT NOT NULL,                 -- ocr | audio | llm_analysis | image | backfill
    job_status       TEXT NOT NULL DEFAULT 'QUEUED',
    priority         INTEGER NOT NULL DEFAULT 5,
    idempotency_key  TEXT UNIQUE,
    worker_id        TEXT,
    retry_count      INTEGER DEFAULT 0,
    max_retries      INTEGER DEFAULT 3,
    error_message    TEXT,
    payload_json     TEXT DEFAULT '{}',
    result_json      TEXT,
    created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
    started_at       DATETIME,
    completed_at     DATETIME,
    FOREIGN KEY (artifact_id) REFERENCES artifacts_raw(id)
);

CREATE INDEX IF NOT EXISTS idx_jobs_status   ON processing_jobs(job_status);
CREATE INDEX IF NOT EXISTS idx_jobs_artifact ON processing_jobs(artifact_id);


-- =========================================================
-- PIPELINE VERSIONS (Version Tracker)
-- Enables backfill eligibility checks.
-- =========================================================

CREATE TABLE IF NOT EXISTS pipeline_versions (
    id                      TEXT PRIMARY KEY,       -- UUID
    pipeline_name           TEXT NOT NULL,
    engine_version          TEXT NOT NULL,
    model_version           TEXT,
    prompt_template_version TEXT,
    chunking_version        TEXT,
    diarization_version     TEXT,
    active                  INTEGER DEFAULT 1,
    created_at              DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (pipeline_name, engine_version)
);


-- =========================================================
-- EVENT LOG (Event System)
-- Immutable append-only log of all system events.
-- =========================================================

CREATE TABLE IF NOT EXISTS event_log (
    id           TEXT PRIMARY KEY,                  -- ULID
    event_type   TEXT NOT NULL,
    artifact_id  TEXT,
    payload_json TEXT DEFAULT '{}',
    delivered    INTEGER DEFAULT 0,
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_event_type    ON event_log(event_type);
CREATE INDEX IF NOT EXISTS idx_event_created ON event_log(created_at);


-- =========================================================
-- WEBHOOK SUBSCRIBERS (Event System)
-- UUID for subscriber IDs per schema-decisions.md.
-- =========================================================

CREATE TABLE IF NOT EXISTS webhook_subscribers (
    id          TEXT PRIMARY KEY,                   -- UUID
    url         TEXT NOT NULL UNIQUE,
    event_types TEXT NOT NULL DEFAULT '[]',
    active      INTEGER DEFAULT 1,
    secret      TEXT,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);


-- =========================================================
-- EMBEDDINGS (Phase 7 — RAG)
-- SQLite-native vector store. No external vector DB.
-- See: architecture-decisions.md → Vector Store: SQLite + Ollama
-- =========================================================

CREATE TABLE IF NOT EXISTS embeddings (
    id               TEXT PRIMARY KEY,              -- UUID
    source_type      TEXT NOT NULL,                 -- 'artifact' | 'codex' | 'codebase' | 'web_page'
    source_id        TEXT NOT NULL,                 -- artifact UUID, codex UUID, or relative file path
    project_id       TEXT,                          -- nullable; scopes codebase embeddings
    chunk_index      INTEGER NOT NULL DEFAULT 0,    -- 0-based chunk position within source
    chunk_text       TEXT NOT NULL,
    embedding_model  TEXT NOT NULL,                 -- e.g. "nomic-embed-text"
    embedding_vector BLOB NOT NULL,                 -- struct.pack float32 array
    embedding_dim    INTEGER NOT NULL,              -- e.g. 768 for nomic-embed-text
    created_at       DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_embeddings_source  ON embeddings(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_project ON embeddings(project_id)
    WHERE project_id IS NOT NULL;


-- =========================================================
-- HUMAN OVERRIDE LAYER (Phase 8)
-- Overrides NEVER alter the raw artifact. Append-only per artifact.
-- =========================================================

CREATE TABLE IF NOT EXISTS ocr_corrections (
    id               TEXT PRIMARY KEY,              -- ULID
    artifact_id      TEXT NOT NULL,
    original_value   TEXT,
    corrected_value  TEXT,
    corrected_by     TEXT,
    timestamp        DATETIME DEFAULT CURRENT_TIMESTAMP,
    artifact_version INTEGER,
    reason           TEXT,
    FOREIGN KEY (artifact_id) REFERENCES artifacts_raw(id)
);

CREATE INDEX IF NOT EXISTS idx_ocr_corrections_artifact ON ocr_corrections(artifact_id);


CREATE TABLE IF NOT EXISTS speaker_resolution_overrides (
    id               TEXT PRIMARY KEY,              -- ULID
    artifact_id      TEXT NOT NULL,
    segment_index    INTEGER,
    original_speaker TEXT,
    corrected_speaker TEXT,
    corrected_by     TEXT,
    timestamp        DATETIME DEFAULT CURRENT_TIMESTAMP,
    reason           TEXT,
    FOREIGN KEY (artifact_id) REFERENCES artifacts_raw(id)
);

CREATE INDEX IF NOT EXISTS idx_speaker_overrides_artifact ON speaker_resolution_overrides(artifact_id);


CREATE TABLE IF NOT EXISTS summary_corrections (
    id               TEXT PRIMARY KEY,              -- ULID
    artifact_id      TEXT NOT NULL,
    original_summary TEXT,
    corrected_summary TEXT,
    corrected_by     TEXT,
    timestamp        DATETIME DEFAULT CURRENT_TIMESTAMP,
    reason           TEXT,
    FOREIGN KEY (artifact_id) REFERENCES artifacts_raw(id)
);

CREATE INDEX IF NOT EXISTS idx_summary_corrections_artifact ON summary_corrections(artifact_id);


CREATE TABLE IF NOT EXISTS tag_overrides (
    id             TEXT PRIMARY KEY,                -- ULID
    artifact_id    TEXT NOT NULL,
    original_tags  TEXT,                            -- JSON array
    corrected_tags TEXT,                            -- JSON array
    corrected_by   TEXT,
    timestamp      DATETIME DEFAULT CURRENT_TIMESTAMP,
    reason         TEXT,
    FOREIGN KEY (artifact_id) REFERENCES artifacts_raw(id)
);

CREATE INDEX IF NOT EXISTS idx_tag_overrides_artifact ON tag_overrides(artifact_id);


-- =========================================================
-- DATA LINEAGE (Phase 8)
-- Artifact transformation graph: Raw → OCR → Chunk → Summary → Migration
-- =========================================================

CREATE TABLE IF NOT EXISTS data_lineage (
    id                        TEXT PRIMARY KEY,     -- ULID
    artifact_id               TEXT NOT NULL,
    derived_from_artifact_id  TEXT,
    pipeline_stage            TEXT,                 -- ocr | audio | chunk | summary | migration | embed
    model_version             TEXT,
    timestamp                 DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (artifact_id)              REFERENCES artifacts_raw(id),
    FOREIGN KEY (derived_from_artifact_id) REFERENCES artifacts_raw(id)
);

CREATE INDEX IF NOT EXISTS idx_lineage_artifact ON data_lineage(artifact_id);
CREATE INDEX IF NOT EXISTS idx_lineage_derived   ON data_lineage(derived_from_artifact_id)
    WHERE derived_from_artifact_id IS NOT NULL;


-- =========================================================
-- SCHEMA MIGRATIONS LOG (Phase 8)
-- Tracks applied migrations for schema evolution management.
-- =========================================================

CREATE TABLE IF NOT EXISTS schema_migrations (
    id             TEXT PRIMARY KEY,                -- ULID
    version_from   INTEGER NOT NULL,
    version_to     INTEGER NOT NULL,
    migration_type TEXT NOT NULL DEFAULT 'additive',  -- additive | breaking | backcompat
    applied_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    migration_success INTEGER NOT NULL DEFAULT 1
);

"""


# ---------------------------------------------------------------------------
# Connection factory
# ---------------------------------------------------------------------------

def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """
    Open a SQLite connection with WAL mode and foreign keys enabled.
    These pragmas must be applied on every new connection — they are not
    stored persistently in the database file.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA synchronous=NORMAL;")   # Safe with WAL, faster than FULL
    conn.execute("PRAGMA busy_timeout=5000;")    # 5s wait on locked DB

    return conn


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------

def init_db(db_path: Path = DB_PATH) -> None:
    """
    Create all tables, indexes, FTS virtual tables, and triggers if they
    don't already exist. Safe to call on every startup.
    """
    logger.info("Initialising database", extra={"db_path": str(db_path)})

    conn = get_connection(db_path)
    try:
        # executescript handles multi-statement DDL including triggers with
        # BEGIN...END blocks correctly. It also issues an implicit COMMIT first.
        conn.executescript(_DDL)

        # Record schema version if not already present
        row = conn.execute("SELECT version FROM schema_version ORDER BY applied_at DESC LIMIT 1").fetchone()
        if row is None or row["version"] < SCHEMA_VERSION:
            conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (SCHEMA_VERSION,)
            )

        conn.commit()
        logger.info("Database initialised", extra={"schema_version": SCHEMA_VERSION})

    except Exception:
        conn.rollback()
        logger.exception("Database initialisation failed")
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Migration stub
# ---------------------------------------------------------------------------

def run_migrations(db_path: Path = DB_PATH) -> None:
    """
    Placeholder for future additive migrations.

    Pattern:
        current = get_current_version(conn)
        if current < 2:
            conn.execute("ALTER TABLE tasks ADD COLUMN ...")
            update_version(conn, 2)

    Rules:
    - Additive only (never DROP COLUMN, never change PK type)
    - New columns must be nullable with a default
    - Update schema_version after each migration
    - Update MASTER_SCHEMA.md in the same session
    """
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT version FROM schema_version ORDER BY applied_at DESC LIMIT 1"
        ).fetchone()
        current = row["version"] if row else 0
        logger.info("Schema migration check", extra={"current_version": current, "target_version": SCHEMA_VERSION})

        # v1 → v2: add tokens_in column for prompt token tracking
        if current < 2:
            try:
                conn.execute("ALTER TABLE execution_logs ADD COLUMN tokens_in INTEGER")
                conn.execute("INSERT INTO schema_version (version) VALUES (2)")
                logger.info("Migration v1→v2 applied: added tokens_in to execution_logs")
            except Exception as e:
                # Column may already exist if DB was created fresh at v2
                logger.debug("Migration v1→v2 skipped (column may exist): %s", e)

        # v2 → v3: add tokens_in column (migration v2 was unreliable due to init_db
        # setting schema_version=2 before the migration ran)
        if current < 3:
            try:
                conn.execute("ALTER TABLE execution_logs ADD COLUMN tokens_in INTEGER")
                logger.info("Migration v2→v3 applied: added tokens_in to execution_logs")
            except Exception as e:
                logger.debug("Migration v2→v3 skipped (column may exist): %s", e)
            conn.execute("INSERT INTO schema_version (version) VALUES (3)")

        # v3 → v4: add Phase 3 tables via executescript (CREATE TABLE IF NOT EXISTS is idempotent)
        if current < 4:
            conn.execute("INSERT INTO schema_version (version) VALUES (4)")
            logger.info("Migration v3→v4 applied: Phase 3 tables registered")

        # v4 → v5: add context_compressions (added after v4 tag was cut)
        if current < 5:
            try:
                conn.executescript("""
                CREATE TABLE IF NOT EXISTS context_compressions (
                    id                TEXT PRIMARY KEY,
                    task_id           TEXT NOT NULL,
                    compression_round INTEGER DEFAULT 1,
                    original_tokens   INTEGER,
                    compressed_tokens INTEGER,
                    summary_text      TEXT,
                    created_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (task_id) REFERENCES tasks(id)
                );
                CREATE INDEX IF NOT EXISTS idx_compressions_task ON context_compressions(task_id);
                """)
                logger.info("Migration v4→v5 applied: context_compressions table created")
            except Exception as e:
                logger.debug("Migration v4→v5 skipped: %s", e)
            conn.execute("INSERT INTO schema_version (version) VALUES (5)")

        # v5 → v6: add Phase 4 tables (CREATE TABLE IF NOT EXISTS is idempotent)
        if current < 6:
            conn.executescript(r"""
            CREATE TABLE IF NOT EXISTS artifacts_extracted (
                id               TEXT PRIMARY KEY,
                artifact_id      TEXT NOT NULL,
                pipeline_name    TEXT NOT NULL,
                pipeline_version TEXT NOT NULL,
                model_version    TEXT,
                engine_version   TEXT NOT NULL DEFAULT '1.0',
                extraction_data  TEXT NOT NULL DEFAULT '{}',
                confidence_score REAL,
                retry_count      INTEGER DEFAULT 0,
                gpu_used         TEXT,
                processing_ms    INTEGER,
                created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (artifact_id) REFERENCES artifacts_raw(id)
            );
            CREATE INDEX IF NOT EXISTS idx_extracted_artifact ON artifacts_extracted(artifact_id);
            CREATE TABLE IF NOT EXISTS artifacts_analysis (
                id                    TEXT PRIMARY KEY,
                artifact_id           TEXT NOT NULL,
                model_id              TEXT,
                prompt_id             TEXT,
                prompt_version        TEXT,
                engine_version        TEXT NOT NULL DEFAULT '1.0',
                summary_text          TEXT,
                tags_json             TEXT DEFAULT '[]',
                reasoning_text        TEXT,
                validation_score      REAL,
                routing_decision_json TEXT DEFAULT '{}',
                processing_ms         INTEGER,
                created_at            DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (artifact_id) REFERENCES artifacts_raw(id)
            );
            CREATE INDEX IF NOT EXISTS idx_analysis_artifact ON artifacts_analysis(artifact_id);
            CREATE TABLE IF NOT EXISTS processing_jobs (
                id               TEXT PRIMARY KEY,
                artifact_id      TEXT,
                job_type         TEXT NOT NULL,
                job_status       TEXT NOT NULL DEFAULT 'QUEUED',
                priority         INTEGER NOT NULL DEFAULT 5,
                idempotency_key  TEXT UNIQUE,
                worker_id        TEXT,
                retry_count      INTEGER DEFAULT 0,
                max_retries      INTEGER DEFAULT 3,
                error_message    TEXT,
                payload_json     TEXT DEFAULT '{}',
                result_json      TEXT,
                created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
                started_at       DATETIME,
                completed_at     DATETIME,
                FOREIGN KEY (artifact_id) REFERENCES artifacts_raw(id)
            );
            CREATE INDEX IF NOT EXISTS idx_jobs_status   ON processing_jobs(job_status);
            CREATE INDEX IF NOT EXISTS idx_jobs_artifact ON processing_jobs(artifact_id);
            CREATE TABLE IF NOT EXISTS pipeline_versions (
                id                      TEXT PRIMARY KEY,
                pipeline_name           TEXT NOT NULL,
                engine_version          TEXT NOT NULL,
                model_version           TEXT,
                prompt_template_version TEXT,
                chunking_version        TEXT,
                diarization_version     TEXT,
                active                  INTEGER DEFAULT 1,
                created_at              DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (pipeline_name, engine_version)
            );
            CREATE TABLE IF NOT EXISTS event_log (
                id           TEXT PRIMARY KEY,
                event_type   TEXT NOT NULL,
                artifact_id  TEXT,
                payload_json TEXT DEFAULT '{}',
                delivered    INTEGER DEFAULT 0,
                created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_event_type    ON event_log(event_type);
            CREATE INDEX IF NOT EXISTS idx_event_created ON event_log(created_at);
            CREATE TABLE IF NOT EXISTS webhook_subscribers (
                id          TEXT PRIMARY KEY,
                url         TEXT NOT NULL UNIQUE,
                event_types TEXT NOT NULL DEFAULT '[]',
                active      INTEGER DEFAULT 1,
                secret      TEXT,
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """)
            conn.execute("INSERT INTO schema_version (version) VALUES (6)")
            logger.info("Migration v5→v6 applied: Phase 4 tables created")

        # v6 → v7: add Phase 7 RAG tables + execution_logs columns
        if current < 7:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS embeddings (
                id               TEXT PRIMARY KEY,
                source_type      TEXT NOT NULL,
                source_id        TEXT NOT NULL,
                project_id       TEXT,
                chunk_index      INTEGER NOT NULL DEFAULT 0,
                chunk_text       TEXT NOT NULL,
                embedding_model  TEXT NOT NULL,
                embedding_vector BLOB NOT NULL,
                embedding_dim    INTEGER NOT NULL,
                created_at       DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_embeddings_source
                ON embeddings(source_type, source_id);
            """)
            # Additive columns on execution_logs — ignore if already present
            for col_sql in (
                "ALTER TABLE execution_logs ADD COLUMN rag_chunks_injected INTEGER DEFAULT 0",
                "ALTER TABLE execution_logs ADD COLUMN rag_source_ids TEXT",
            ):
                try:
                    conn.execute(col_sql)
                except Exception as e:
                    logger.debug("Migration v6→v7 column skipped: %s", e)
            conn.execute("INSERT INTO schema_version (version) VALUES (7)")
            logger.info("Migration v6→v7 applied: embeddings table + rag columns on execution_logs")

        # v7 → v8: Phase 8 — human override tables, data lineage, schema_migrations,
        #           archival columns on artifacts_raw
        if current < 8:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS ocr_corrections (
                id TEXT PRIMARY KEY, artifact_id TEXT NOT NULL,
                original_value TEXT, corrected_value TEXT, corrected_by TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                artifact_version INTEGER, reason TEXT,
                FOREIGN KEY (artifact_id) REFERENCES artifacts_raw(id)
            );
            CREATE INDEX IF NOT EXISTS idx_ocr_corrections_artifact
                ON ocr_corrections(artifact_id);

            CREATE TABLE IF NOT EXISTS speaker_resolution_overrides (
                id TEXT PRIMARY KEY, artifact_id TEXT NOT NULL,
                segment_index INTEGER, original_speaker TEXT, corrected_speaker TEXT,
                corrected_by TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, reason TEXT,
                FOREIGN KEY (artifact_id) REFERENCES artifacts_raw(id)
            );
            CREATE INDEX IF NOT EXISTS idx_speaker_overrides_artifact
                ON speaker_resolution_overrides(artifact_id);

            CREATE TABLE IF NOT EXISTS summary_corrections (
                id TEXT PRIMARY KEY, artifact_id TEXT NOT NULL,
                original_summary TEXT, corrected_summary TEXT, corrected_by TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, reason TEXT,
                FOREIGN KEY (artifact_id) REFERENCES artifacts_raw(id)
            );
            CREATE INDEX IF NOT EXISTS idx_summary_corrections_artifact
                ON summary_corrections(artifact_id);

            CREATE TABLE IF NOT EXISTS tag_overrides (
                id TEXT PRIMARY KEY, artifact_id TEXT NOT NULL,
                original_tags TEXT, corrected_tags TEXT, corrected_by TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, reason TEXT,
                FOREIGN KEY (artifact_id) REFERENCES artifacts_raw(id)
            );
            CREATE INDEX IF NOT EXISTS idx_tag_overrides_artifact
                ON tag_overrides(artifact_id);

            CREATE TABLE IF NOT EXISTS data_lineage (
                id TEXT PRIMARY KEY, artifact_id TEXT NOT NULL,
                derived_from_artifact_id TEXT, pipeline_stage TEXT,
                model_version TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (artifact_id) REFERENCES artifacts_raw(id),
                FOREIGN KEY (derived_from_artifact_id) REFERENCES artifacts_raw(id)
            );
            CREATE INDEX IF NOT EXISTS idx_lineage_artifact ON data_lineage(artifact_id);

            CREATE TABLE IF NOT EXISTS schema_migrations (
                id TEXT PRIMARY KEY, version_from INTEGER NOT NULL,
                version_to INTEGER NOT NULL,
                migration_type TEXT NOT NULL DEFAULT 'additive',
                applied_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                migration_success INTEGER NOT NULL DEFAULT 1
            );
            """)
            for col_sql in (
                "ALTER TABLE artifacts_raw ADD COLUMN is_cold_storage INTEGER DEFAULT 0",
                "ALTER TABLE artifacts_raw ADD COLUMN archived_at DATETIME",
            ):
                try:
                    conn.execute(col_sql)
                except Exception as e:
                    logger.debug("Migration v7→v8 column skipped: %s", e)
            conn.execute("INSERT INTO schema_version (version) VALUES (8)")
            logger.info("Migration v7→v8 applied: Phase 8 tables + archival columns")

        # Idempotent column guard — ensures columns added across all phase
        # migrations are present regardless of which migration path the DB
        # took (catches DBs created at a later schema version than when a
        # column was introduced).
        _ensure_columns = [
            ("execution_logs", "tokens_in", "INTEGER"),
            ("execution_logs", "rag_chunks_injected", "INTEGER DEFAULT 0"),
            ("execution_logs", "rag_source_ids", "TEXT"),
        ]
        for table, col, typedef in _ensure_columns:
            existing_cols = {
                r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if col not in existing_cols:
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")
                    logger.info("Idempotent column added: %s.%s", table, col)
                except Exception as e:
                    logger.debug("Column guard skipped %s.%s: %s", table, col, e)

        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DB_PATH
    print(f"Initialising database at: {path}")
    init_db(path)
    run_migrations(path)
    print("Done.")
