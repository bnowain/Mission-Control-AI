# Build Roadmap — Mission Control
**Version:** 0.1
**Created:** 2026-02-27
**Logged by:** claude

---

## CRITICAL — Codex Deduplication Rule (For the Claude Worker)

**Read this before any session that touches knowledge bases.**

Two Codex systems exist and will be merged post-v1. Until then, strict domain routing prevents duplication:

### What Goes Where

| Content Type | System | Examples |
|---|---|---|
| Platform/technical knowledge applicable to ALL projects | AI-Learning-CODEX (`E:\0-Automated-Apps\AI-Learning-CODEX\`) | Python ABI issues, Windows encoding traps, SQLite locking, Playwright, Celery/Redis |
| Mission Control-specific architectural decisions | MC Knowledge Base (`E:\0-Automated-Apps\Mission_Control\knowledge\`) | LiteLLM Router config, capability categories, DAG execution pattern, Codex schema choices |

### Hard Rules

1. **Never write the same content in both systems.** If you're unsure which system owns it, ask: "Would this be useful to a developer working on civic_media or article-tracker?" If yes → AI-Learning-CODEX. If it only makes sense in the context of Mission Control's execution engine → MC knowledge.

2. **Cross-reference with `see also` links instead of copying.** Example: MC schema-decisions.md can say "See AI-Learning-CODEX/windows-environment.md for SQLite WAL gotchas on Windows" without repeating the content.

3. **Platform discoveries made DURING Mission Control work go to AI-Learning-CODEX.** If you hit a Python version incompatibility while building MC, the entry goes in AI-Learning-CODEX (all projects benefit), NOT in MC knowledge.

4. **MC-specific implementation discoveries go to MC knowledge.** If you discover that LiteLLM Router's `latency-based-routing` has a specific behavior that affects how you implement the escalation policy, that goes in architecture-decisions.md.

### At Merge Time (Post-v1)
Run a semantic similarity scan across both systems. Entries with >0.85 similarity get human review. Source is tagged `model_source: "cloud:anthropic"` for all existing claude-logged entries. No entries are deleted — older entries are marked superseded via `codex_supersessions` table.

---

## Phase 0 — Pre-Build Checklist
**Status:** 🟡 In progress

These must be done before writing implementation code.

- [x] Reference knowledge base built (`E:\0-Automated-Apps\Reference\`)
- [x] Spec files read (Parts 0–8)
- [x] Compatibility check against MASTER_SCHEMA.md completed
- [x] Port 8860 claimed in root CLAUDE.md and MASTER_INDEX.md
- [x] MC knowledge base created (this directory)
- [ ] **Register MC schema in MASTER_SCHEMA.md** — Part 2 schema is defined but not registered. Rule 6: do this immediately when schema is finalized.
- [ ] **Update Mission Control CLAUDE.md** — add spoke declaration section (port 8860, Atlas surface, DB path)
- [ ] Resolve Yellow #1 tracking — see Cross-Project TODO section below

---

## Phase 1 — Foundation Layer
**Spec:** Parts 1, 2, 3
**Goal:** Working execution loop with DB, grading, routing, and telemetry. No UI. No full API yet.

### Deliverables
- [ ] SQLite database schema (Part 2) fully implemented with WAL enabled
- [ ] Model Interface Layer using LiteLLM Router (see architecture-decisions.md)
- [ ] `ModelExecutor` class — run(task, context_size, temperature, tools) → structured result
- [ ] Execution Engine — pre-task → model execution → validation → post-execution flow
- [ ] Grading Engine — configurable scoring (+40/+30/+15/+15, penalties -10/-20/-25/-30)
- [ ] Telemetry Logger — structured logging to `execution_logs` table
- [ ] Router v1 — rule-based, capability-category only (fast/reasoning/planner)
- [ ] Context Escalation — 3 tiers: Execution (16k) → Hybrid (24k) → Planning (32k)
- [ ] Codex Hook stub — `CodexEngine.query(task_signature)` and `register_candidate(issue_data)`
- [ ] Hardware profiler — GPU detect, VRAM detect, benchmark tokens/sec
- [ ] Replan mode scaffolding (flag only, no full planner)
- [ ] Hard loop limits: `MAX_EXECUTION_LOOPS=10`, `MAX_REPLAN_CYCLES=3`

### Key Architecture Rules
- Use ULID for task_id, execution_log_id, job_id (see schema-decisions.md)
- Stack trace hashing for failure deduplication (see schema-decisions.md)
- Exponential backoff: 125ms start, 2x, 60s cap, max 5 retries (see architecture-decisions.md)
- Classify exceptions before retry: retryable / non-retryable / context-window-exceeded
- `ContextWindowExceededError` → do NOT retry → trigger context tier escalation

### Module Structure
```
Mission_Control/
  app/
    core/
      task_dag.py          # DAG execution engine
      state_machine.py     # Execution state transitions
      execution_loop.py    # Main loop with hard cap
      replan_controller.py # Replan mode scaffold
    models/
      interface.py         # ModelExecutor base class
      litellm_router.py    # LiteLLM Router implementation
      providers/           # ollama, openai, anthropic, vllm adapters
    grading/
      engine.py            # Configurable scoring
      validators.py        # Compile, test, lint, typecheck, runtime
    router/
      adaptive.py          # LiteLLM Router wrapper + routing logic
      escalation.py        # Context escalation policy
      hardware_profiler.py # GPU detection and benchmarking
    codex/
      engine.py            # Query + candidate registration interface
    telemetry/
      logger.py            # Structured telemetry to execution_logs
    context/
      chunker.py           # File-level chunking
      compressor.py        # History compression
      working_set.py       # Working set builder
    database/
      init.py              # Schema creation + WAL setup
      migrations.py        # Future migration support
```

---

## Phase 2 — API Layer
**Spec:** Part 4
**Goal:** Full FastAPI skeleton. Every subsystem exposed via REST. Health endpoint live (required for Atlas).

### Deliverables
- [ ] FastAPI app with async handlers
- [ ] `GET /api/health` → `{"status": "ok"}` (Atlas-required — must be done before Atlas integration)
- [ ] Task API: POST /tasks, GET /tasks/{id}, POST /tasks/{id}/execute, POST /tasks/{id}/cancel
- [ ] Plan API: POST /plans, GET /plans/{id}, POST /plans/{id}/replan, GET /plans/{id}/diff
- [ ] Router API: POST /router/select, GET /router/stats
- [ ] Model API: POST /models/run, GET /models, POST /models/benchmark
- [ ] Validation API: POST /validate, GET /validate/results/{id}
- [ ] Codex API: POST /codex/query, POST /codex/candidate, POST /codex/promote, GET /codex/stats
- [ ] Context API: POST /context/build, POST /context/compress
- [ ] Telemetry API: GET /telemetry/runs, GET /telemetry/models, GET /telemetry/performance, GET /telemetry/hardware
- [ ] SQL API: POST /sql/query (read-only default, explicit write mode toggle)
- [ ] System API: GET /system/status, GET /system/hardware
- [ ] WebSocket endpoint for real-time execution streaming
- [ ] Pydantic models for all request/response shapes
- [ ] Standard error response shape (see master_codex.md §3.7)
- [ ] Atlas-exposed endpoints: GET /api/codex/search, GET /api/router/stats

### Atlas Search Response Shape (Required)
```json
{
  "results": [
    {
      "id": "...",
      "root_cause": "...",
      "prevention_guideline": "...",
      "category": "...",
      "scope": "global",
      "confidence_score": 0.85
    }
  ],
  "total": 42,
  "limit": 20,
  "offset": 0
}
```

---

## Phase 3 — Codex + Plan DAG
**Spec:** Part 4 (Phase 2), Parts 2 & 3
**Goal:** Full Codex database, Plan DAG with state persistence, context OS.

### Deliverables
- [ ] Codex database fully implemented (`master_codex`, `project_codex`, `codex_candidates`, `codex_supersessions`)
- [ ] `model_source` tracking on all Codex entries (`cloud:anthropic`, `local:ollama`, `human`, etc.)
- [ ] Codex promotion pipeline with threshold enforcement (retry OR human intervention OR downstream breakage)
- [ ] Failure clustering by `stack_trace_hash`
- [ ] Plan DAG engine — plan_id, phase_id, step_id, step_status, plan_version, plan_diff_history
- [ ] LangGraph CheckpointTuple pattern for execution state persistence (thread_id = session ID)
- [ ] CrewAI Flows @start/@listen/@router pattern implemented natively for state machine
- [ ] Context OS — chunking, compression, working set management
- [ ] Escalation policies with full logging
- [ ] Codex pre-task injection — query → inject prevention_guidelines into prompt
- [ ] Replay system: POST /runs/{id}/replay
- [ ] Persistent instruction layer: project_rules, naming_conventions, architecture_constraints loading

---

## Phase 4 — Processing Engine ✅ COMPLETE
**Spec:** Part 7
**Goal:** Artifact Registry + processing pipelines + worker scheduler.
**Completed:** 2026-02-27 | **Tests:** 37 new (140 total) | **Schema:** v6 | **Commit:** `0084e80`

### Deliverables
- [x] Artifact Registry — 3-layer schema (raw, extracted, analysis) with SHA256 hashing + dedup
- [x] Artifact state machine: RECEIVED → PROCESSING → PROCESSED → AVAILABLE_FOR_EXPORT → EXPORTED → ARCHIVED (409 on invalid transitions)
- [x] OCR Pipeline — stub-safe: returns `{available: false, blocks: [], tables: [], signatures: []}` when surya not installed
- [x] Audio Pipeline — stub-safe: returns `{available: false, transcript: "", segments: []}` when faster_whisper not installed
- [x] LLM Analysis Pipeline — always available (no hard ML deps at import time)
- [x] Pipeline registry — auto-registers OCR/Audio/LLM at import; `GET /workers/pipelines` returns availability flags
- [x] Worker Scheduler — processing_jobs table, ULID IDs, idempotency keys, QUEUED→RUNNING→COMPLETED/FAILED/RETRYING
- [x] Version Tracking — pipeline_versions table, backfill eligibility checks by comparing artifact extraction version vs current
- [x] Backfill Engine — `POST /backfill` with `simulate=true` returns plan without enqueuing
- [x] Event system — event_log (ULID IDs) + in-memory subscribers + best-effort webhook dispatch
- [x] Webhook CRUD — webhook_subscribers table, `POST/GET/DELETE /events/webhooks`
- [x] `page_url` captured on all ingest endpoints (Rule 3 compliant)
- [ ] Migration layer — GET /artifacts/{id}/migrate (deferred to Phase 7)
- [ ] GPU allocation logic — VRAM tracking, prevent over-allocation (deferred to Phase 7)

### New API Endpoints
- `POST/GET /artifacts`, `GET /artifacts/{id}`, `GET /artifacts/{id}/export`, `POST /artifacts/{id}/state`, `POST /artifacts/{id}/process`
- `GET /workers/pipelines`, `GET /workers/jobs`, `GET /workers/jobs/{id}`, `GET /workers/stats`
- `POST /backfill`
- `GET /events`, `POST/GET/DELETE /events/webhooks`

### New Tables (schema v6)
`artifacts_extracted`, `artifacts_analysis`, `processing_jobs`, `pipeline_versions`, `event_log`, `webhook_subscribers`

---

## Phase 5 — UI (Mission Control Cockpit)
**Spec:** Part 5
**Tech stack:** React + TypeScript, Vite, Zustand, React Flow, Monaco Editor, TailwindCSS + shadcn/ui, ECharts, WebSocket

### Panels
1. Dashboard — active tasks, hardware profile, token throughput, system health, real-time stream
2. Tasks — list with filters, detail page with diff viewer, replay button, Codex warnings
3. Plans — React Flow DAG, node color coding, step detail side panel, plan version comparison
4. Validation — tabs: Compile/Tests/Lint/Typecheck/Security/Performance
5. Codex — searchable memory, promote/merge/deprecate, confidence scores, linked tasks
6. Router Analytics — charts: success rate, score distribution, retry averages, escalation frequency
7. Telemetry — run history explorer, replay, compare, export JSON
8. Reports — project health, model performance, Codex effectiveness, failure clusters (PDF/JSON/MD)
9. SQL Console — Monaco SQL editor, schema browser, safe mode, query history
10. Integrations — Atlas, CI/CD hooks, webhooks, GitHub/GitLab
11. Workers (future-ready) — worker list, status, hardware profile
12. Settings — router config, validation weights, Codex thresholds, security toggles

### Requirements
- No direct database access from frontend — all calls through API
- WebSocket for live execution streaming, validation stream, escalation events
- Dark mode, keyboard shortcuts, accessible design
- Lazy loading for heavy panels

---

## Phase 6 — CLI (Thin API Client) ✅ COMPLETE
**Spec:** Part 6
**Tech stack:** Python, Typer, httpx, rich, WebSocket client

### Commands
```
mission-control task create|run|cancel|list|replay
mission-control status
mission-control artifacts list|view|export|migrate
mission-control backfill [--simulate]
mission-control router stats|override
mission-control telemetry list|view|export
mission-control sql "<query>" | --interactive
mission-control workers list|enable|disable
mission-control coder  # interactive mode
```

### Requirements
- Config in `~/.mission-control/config.json`
- Override via MISSION_CONTROL_API_KEY, MISSION_CONTROL_ENDPOINT env vars
- `--json` flag for machine-readable output
- Streaming support in interactive mode
- Never access DB directly
- Never implement processing logic

---

## Phase 7 — RAG Integration ✅ COMPLETE
**Goal:** Full retrieval-augmented generation layer: web ingestion, artifact embedding, codebase indexing, and pre-task context injection. All backed by SQLite + Ollama embeddings (no external vector DB).
**Decision:** SQLite `embeddings` table with serialized float vectors; cosine similarity in Python; `nomic-embed-text` (or any Ollama embedding model) via LiteLLM. Overrides the Phase 0 "no own ChromaDB" note — ChromaDB is still not used; this is a leaner, SQLite-native approach.

---

### 7.1 — Core Vector Infrastructure

**New table: `embeddings`** (schema v7)
```sql
CREATE TABLE embeddings (
    id              TEXT PRIMARY KEY,           -- UUID
    source_type     TEXT NOT NULL,              -- 'artifact' | 'codex' | 'codebase' | 'web_page'
    source_id       TEXT NOT NULL,              -- artifact UUID, codex UUID, or file path hash
    project_id      TEXT,                       -- nullable; scopes codebase embeddings
    chunk_index     INTEGER NOT NULL DEFAULT 0, -- 0-based chunk position within source
    chunk_text      TEXT NOT NULL,
    embedding_model TEXT NOT NULL,              -- e.g. "ollama/nomic-embed-text"
    embedding_vector BLOB NOT NULL,             -- serialized float32 array (numpy tobytes)
    embedding_dim   INTEGER NOT NULL,           -- e.g. 768
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_embeddings_source ON embeddings(source_type, source_id);
CREATE INDEX idx_embeddings_project ON embeddings(project_id) WHERE project_id IS NOT NULL;
```

**Add to `execution_logs`:**
```sql
ALTER TABLE execution_logs ADD COLUMN rag_chunks_injected INTEGER DEFAULT 0;
ALTER TABLE execution_logs ADD COLUMN rag_source_ids TEXT;  -- JSON array of source_ids used
```

**New module: `app/rag/`**
```
app/rag/
  __init__.py
  engine.py        # RAGEngine: embed(), search(), inject_context()
  chunker.py       # Text → fixed-size overlapping chunks (512 tokens, 64 overlap)
  embedding.py     # EmbeddingClient: wraps Ollama /api/embeddings via httpx
  similarity.py    # cosine_similarity(), top_k_chunks()
  web_fetcher.py   # URL → clean text (httpx + html2text)
```

**Key classes:**
- `EmbeddingClient` — `embed(text: str) → list[float]`, `embed_batch(texts) → list[list[float]]`. Calls `POST http://localhost:11434/api/embeddings` with model `nomic-embed-text`. Falls back gracefully if Ollama is not running (returns None, logs warning, RAG skipped for that call).
- `RAGEngine` — `index_artifact(artifact_id)`, `index_codebase(project_id, path)`, `index_web(url, project_id)`, `search(query, source_type, project_id, top_k) → list[RAGChunk]`, `inject_context(task_ctx) → str`.
- Chunker — 512-token chunks with 64-token overlap. Token count via `len(text.split())` (approximate, avoids tokenizer dep).

**New dependencies to add to requirements.txt:**
- `html2text>=2020.1.16` — web page text extraction (pure Python)

---

### 7.2 — Web Ingest Pipeline

Extends Phase 4 artifact pipeline pattern. New pipeline name: `web_ingest`.

**Flow:**
```
CLI: artifacts ingest --url <url>
  → POST /artifacts  (source_type='web_page', page_url=<url>)
  → POST /artifacts/{id}/process  (pipeline_name='web_ingest')
    → Worker picks up job
    → web_fetcher.py: httpx GET url → html2text → clean text
    → Chunker: split into 512-token overlapping chunks
    → EmbeddingClient: embed each chunk (batch)
    → Store chunks in embeddings table (source_type='web_page', source_id=artifact_id)
    → Store clean text in artifacts_extracted.extracted_text
    → Transition artifact: RECEIVED → PROCESSING → PROCESSED
    → Emit event: artifact.embedded
```

**New pipeline file:** `app/processing/pipelines/web_ingest.py`

---

### 7.3 — Artifact Embedding Pipeline

Auto-triggered after any OCR/audio/LLM analysis pipeline completes. New pipeline name: `embed_artifact`.

**Flow:**
```
Event: artifact.processed (emitted by ocr/audio/llm pipelines)
  → Subscriber enqueues embed_artifact job for that artifact_id
  → Worker picks up job
  → Reads artifacts_extracted.extracted_text
  → Chunks → embeds → stores in embeddings (source_type='artifact')
  → Emit: artifact.embedded
```

Also triggered manually: `POST /artifacts/{id}/process` with `pipeline_name='embed_artifact'`.

---

### 7.4 — Codebase Indexing

Index a local directory as a project's code context. Scoped to `project_id`.

**Flow:**
```
POST /rag/index  body: {project_id, path, file_extensions, max_file_size_kb}
  → Walk path, filter by extensions (default: .py .js .ts .go .rs .md .txt)
  → Skip files > max_file_size_kb (default: 100KB)
  → Per file: read → chunk by function/class boundary (fallback: fixed-size)
  → Embed each chunk → store (source_type='codebase', project_id=<project_id>)
  → Return: {indexed_files, total_chunks, skipped_files}

DELETE /rag/index/{project_id}  → remove all codebase embeddings for that project
```

**CLI:** `mission-control rag index --path <dir> --project <id> [--extensions .py,.ts] [--max-kb 100]`

---

### 7.5 — Pre-Task RAG Injection

In `ExecutionLoop`, before building the user prompt, call `RAGEngine.inject_context(task_ctx)`.

**Logic:**
1. Query `source_type='codebase'` filtered by `project_id`, top-5 chunks
2. Query `source_type='artifact'` filtered by `project_id` (or global if no project match), top-3 chunks
3. Query `source_type='web_page'` filtered by `project_id`, top-2 chunks
4. Codex query already handled by `CodexEngine` (FTS) — augment with vector search on `source_type='codex'` top-3
5. Assemble RAG context block:
   ```
   [RAG CONTEXT — {n} chunks from {sources}]
   <chunk_text>
   ...
   [END RAG CONTEXT]
   ```
6. Prepend to user message
7. Log: `rag_chunks_injected={total_count}`, `rag_source_ids=[...]`

**Guard:** If Ollama is unavailable (embedding returns None), skip RAG silently. Execution continues without RAG — no failure.

---

### 7.6 — API Endpoints

```
POST   /rag/index                     # Index a codebase directory
GET    /rag/search?q=&project=&type=&limit=  # Semantic search (used by CLI + UI)
GET    /rag/stats                     # Embedding counts by source_type
DELETE /rag/index/{project_id}        # Remove codebase index for a project
```

**Atlas-exposed:** `GET /api/rag/search?q=&limit=` — semantic search over all non-codebase embeddings (web_page + artifact). Codebase embeddings excluded (too project-specific).

---

### 7.7 — CLI Commands (add to Phase 6 CLI)

Add a new `rag` command group to `cli/commands/rag.py`:
```
mission-control rag index   --path <dir> --project <id> [--extensions] [--max-kb]
mission-control rag search  <query> [--project] [--type] [--limit]
mission-control rag stats
```

`artifacts ingest --url <url>` already works — just needs the web_ingest pipeline registered.

---

### 7.8 — Testing

- [ ] `tests/test_phase7_rag.py` — unit tests for chunker, similarity, EmbeddingClient (mock Ollama), RAGEngine
- [ ] Integration test: web_ingest pipeline end-to-end with mocked httpx
- [ ] Integration test: artifact embedding triggered after processing
- [ ] Integration test: codebase index → search → verify top-k relevance
- [ ] Integration test: pre-task injection adds context block to prompt
- [ ] Graceful degradation: Ollama offline → execution proceeds without RAG

---

### 7.9 — Schema Changes (v7)

**New table:** `embeddings` (see 7.1 above)
**Altered:** `execution_logs` — `rag_chunks_injected INTEGER DEFAULT 0`, `rag_source_ids TEXT`
**New pipeline registered:** `web_ingest`, `embed_artifact`

Update `MASTER_SCHEMA.md` immediately when implementing.

---

## Phase 8 — Platform Hardening ✅ COMPLETE
**Spec:** Part 8
**Goal:** Production-grade observability, testing, security, governance.

### Deliverables
- [ ] GET /api/health (full: DB connectivity + worker status + GPU status)
- [ ] GET /metrics — Prometheus-compatible (task_count_total, pipeline_duration_seconds, gpu_memory_usage_bytes, queue_depth)
- [ ] Structured JSON logging — request_id, artifact_id, task_id, api_key_id, timestamp, level
- [ ] Audit log table — immutable, tracks: artifact.uploaded, task.created, sql.query.executed, codex.promoted
- [ ] Idempotency-Key header support + SHA256 artifact deduplication
- [ ] Prompt registry — versioned prompt templates, backfill eligibility detection
- [ ] API key scopes: artifact:read, artifact:write, audio:process, ocr:process, codex:read, codex:write, sql:query
- [ ] Feature flag registry
- [ ] Execution timeouts, memory limits, rate limiting per API key
- [ ] Hot/cold storage, archival endpoint
- [ ] Disaster recovery — DB backup script, restore script
- [ ] Human override tables (OCR correction, speaker resolution, summary correction, tag override)
- [ ] Data lineage tracking (artifact transformation graph)
- [ ] Schema evolution — schema_version on artifacts, migration scripts, migration log

### Testing Strategy
- [ ] Pytest unit + integration tests (artifact, pipeline, versioning, codex, idempotency, telemetry, audit)
- [ ] Failure injection tests (GPU OOM, model timeout, corrupt artifact, SQL injection attempt)
- [ ] Playwright E2E tests (10 scenarios: dashboard, create task, upload file, SQL console, etc.)
- [ ] Load testing scripts (100 concurrent uploads, 50 concurrent LLM tasks)
- [ ] CI pipeline config, linting, type checking, coverage report

---

## Phase 9 — Atlas Integration ✅ COMPLETE

**Spec:** integration-patterns.md
**Goal:** Mission Control fully registered as an Atlas spoke.

### Registration Checklist
- [x] Schema registered in MASTER_SCHEMA.md (done Phase 1)
- [x] Spoke section added to master_codex.md (§11D)
- [x] GET /api/health responding (done Phase 2)
- [x] GET /api/codex/search returning Atlas-compatible response shape
- [x] GET /api/router/stats returning read-only summary
- [x] Mission Control added to Atlas `config.py` SPOKES dict (port 8860)
- [x] Search keywords added to Atlas `query_classifier.py` (24 keywords)
- [x] Searcher added to Atlas `unified_search.py` (`_search_mission_control`)
- [x] Tool schemas defined in Atlas `tools.py` (MISSION_CONTROL_TOOLS: 3 tools)
- [x] TOOL_TO_SPOKE mapping updated in Atlas `tools.py`
- [x] Feature Completeness Matrix updated in master_codex.md §12
- [x] 27 tests: 12 passed, 15 skipped (Atlas not in path — correct), 0 failures

### What NOT to expose to Atlas
- Raw execution telemetry
- Task management endpoints
- Model routing internals
- Worker status

---

## Post-v1 — Supreme Master Codex

**This is NOT a Phase 1-8 task.** Do not start this until Mission Control v1 is complete and stable.

**Vision:**
One unified knowledge database where:
- Cloud agents (Claude) log with `model_source: "cloud:anthropic"`
- Local LLM workers log with `model_source: "local:ollama"` or `"local:vllm"`
- Humans override with `model_source: "human"`
- All sources can read all entries
- Supersession is explicit and versioned (never delete, mark superseded)

**Migration plan:**
1. Export AI-Learning-CODEX markdown entries to structured rows
2. Export Mission Control knowledge base entries to structured rows
3. Run semantic similarity scan — entries >0.85 similarity flagged for human review
4. Tag all migrated entries with `model_source: "cloud:anthropic"` (logged during Claude sessions)
5. Load into Supreme Master Codex database (schema: see `codex_supersessions` in schema-decisions.md)
6. Retire AI-Learning-CODEX markdown files (keep as archive)
7. Update all projects' CLAUDE.md to point to Supreme Master Codex API

**Structural foundation already designed.** See schema-decisions.md → Codex Cloud/Local Source Separation.

---

## Cross-Project TODO — `status` Field Naming Debt

**This is NOT Mission Control's problem to fix. It requires explicit user approval for each project.**

**Context:** Root CLAUDE.md Rule 17 requires globally unique, descriptive field names. The word `status` appears in 4+ existing spokes (civic_media, Facebook-Offline, Shasta-Campaign-Finance, and others). Mission Control uses `task_status` to comply with Rule 17.

**Existing spokes with ambiguous `status` fields:**
- `civic_media.processing_jobs.status` → candidate for rename to `processing_status`
- `Facebook-Offline.imports.status` → candidate for rename to `import_status`
- `Shasta-Campaign-Finance.filers.status` → candidate for rename to `filer_status`

**Action required (per user approval):** When touching those projects, propose the rename as part of a migration. Each rename requires:
1. Additive migration: add new named column, copy data, update queries, remove old column
2. Update MASTER_SCHEMA.md
3. Update any Atlas query_classifier or unified_search references
4. Codex entry logging the change

**Do NOT touch other projects without explicit instruction.** Log this as a reminder only.

---

## Version History

| Version | Date | Change |
|---------|------|--------|
| 0.1 | 2026-02-27 | Initial creation — 8 phases + post-v1 Supreme Master Codex roadmap + dedup routing rule |
| 0.2 | 2026-02-27 | Phase 4 complete — Processing Engine (artifact registry, pipelines, workers, events, backfill) |
| 0.3 | 2026-02-28 | Phase 6 complete — CLI (Typer + httpx + rich, 30 tests, 170 total). Phase 7 redesigned as RAG Integration (SQLite + Ollama embeddings): web_ingest, artifact embedding, codebase indexing, pre-task injection. Platform Hardening → Phase 8, Atlas → Phase 9. |
| 0.4 | 2026-02-28 | Phase 7 complete — RAG Integration (32 tests, 202 total). New: app/rag/ package (chunker, embedding, similarity, web_fetcher, engine), web_ingest + embed_artifact pipelines, /rag/* API endpoints, rag CLI command group, execution_loop RAG injection, schema v7 (embeddings table + rag columns on execution_logs). |
| 0.5 | 2026-02-28 | Phase 8 complete — Platform Hardening (37 tests, 239 total). New: schema v8 (6 tables: ocr_corrections, speaker_resolution_overrides, summary_corrections, tag_overrides, data_lineage, schema_migrations + archival cols on artifacts_raw), audit helper, feature flags helper, Prometheus /metrics, enhanced /api/health (db+worker+gpu), governance API (/audit, /feature-flags, /prompt-registry, /overrides/*, /lineage/*), POST /artifacts/{id}/archive. |
| 0.6 | 2026-02-28 | Phase 9 complete — Atlas Integration (12 passed + 15 skipped, 251 total). Atlas-side: SPOKES dict, MISSION_CONTROL_TOOLS (3 tools), query_classifier keywords, unified_search searcher, TOOL_TO_SPOKE map. MC-side: confirmed /api/health, /api/codex/search, /api/router/stats, /api/rag/search shapes. Documentation: master_codex.md §11D (MC spoke section) + updated §12 Feature Completeness Matrix. |
