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
SCHEMA_VERSION = 1

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
    tokens_generated      INTEGER,
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
        # No migrations needed yet — schema version 1 is baseline
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
