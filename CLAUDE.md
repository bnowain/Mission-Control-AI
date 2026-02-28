# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Project Status

**Mission Control is in Phase 0 (pre-build complete) — Phase 1 implementation starting.** All 8 specification documents are finalized. Compatibility check against ecosystem complete. Knowledge base created at `knowledge/`. Schema registered in MASTER_SCHEMA.md. Phase 1 builds the core execution engine (DB, model interface, grading, telemetry, router).

---

## HARD RULE — Check These at the Start of Every Implementation Session

Before writing any implementation code, scan the relevant files below. Each takes under 2 minutes. Skipping this has a known cost: reinventing patterns that are already solved, or building against a stale schema.

### 1. Reference Knowledge Base (32 repos, pre-extracted)
**`E:\0-Automated-Apps\Reference\REFERENCE_INDEX.md`** — quick lookup table

| If you're about to build... | Read this first |
|-----------------------------|-----------------|
| Model Interface Layer, Router, LiteLLM config | `kb-llm-routing-providers.md` |
| Execution Engine, DAG, state machine, replan | `kb-orchestration-frameworks.md` |
| Grading Engine, retry logic, telemetry, logging | `kb-execution-validation-telemetry.md` |
| Codex, persistent memory, FTS search | `kb-persistent-memory-rag.md` |
| Worker scheduler, background jobs, durable tasks | `kb-workflow-orchestration.md` |
| OCR pipeline, audio pipeline, document processing | `kb-document-processing.md` |

The GradingEngine, exception classification registry, execution loop, mutex TaskState, and StructuredLogger are all **ready to use verbatim** from `kb-execution-validation-telemetry.md`. Do not reimplement them.

### 2. Mission Control Knowledge Base
**`knowledge/INDEX.md`** → Quick-Find table for MC-specific decisions.
Check before touching: schema fields, LLM routing, Codex logic, Atlas integration.

### 3. Current Phase Checklist
**`knowledge/build-roadmap.md`** → find the current phase, check which deliverables are pending.

### 4. Schema (if touching DB or API)
**`E:\0-Automated-Apps\MASTER_SCHEMA.md` § Spoke: Mission_Control** — canonical field names and types.
Update it immediately if you change any table or endpoint.

---

## Atlas Spoke Declaration

**This project is a spoke in the Atlas ecosystem.**

| Property | Value |
|----------|-------|
| Port | **8860** |
| DB | `Mission_Control/database/mission_control.db` |
| Health | `GET /api/health` → `{"status": "ok"}` |
| Framework | FastAPI (async) |

**Exposed to Atlas:**
- `GET /api/health` — Atlas polls every 30s
- `GET /api/codex/search?q=&limit=&offset=` — Codex lessons search
- `GET /api/router/stats` — Model performance summary (read-only)

**NOT exposed to Atlas:** raw telemetry, task management, model routing internals, worker status

**Atlas registration checklist** (complete during Phase 8): see `knowledge/build-roadmap.md → Phase 8`

**No spoke-to-spoke calls.** All cross-project communication routes through Atlas (:8888). Mission Control has no approved exceptions.

---

## What This Project Is

Mission Control is an **Adaptive AI Execution Framework** — a structured, API-first autonomous execution operating system for LLM-based engineering workflows. It is NOT a chatbot. It is a plan-driven execution engine where LLMs are workers, not decision-makers, with deterministic validation (compilers, tests, linters) as ground truth.

---

## Specification Documents (Read Order for Implementation)

| File | Purpose |
|------|---------|
| `1-Buildout.txt` | Phase 1 scope: Model Interface, Execution Engine, Grading, Telemetry, Router, Codex stub |
| `4 SPACESHIP ARCHITECTURE — API-FIRST AUTONOMOUS EXECUTION OS.txt` | Complete API contracts for all 8 modules |
| `7 MISSION CONTROL ENGINE (PROCESSING PLATFORM).txt` | Backend engine: pipelines, artifact registry, worker scheduler |
| `3 CLAUDE-DERIVED EXECUTION PRINCIPLES.txt` | Behavioral standards: plan-phase separation, replan triggers, file logging |
| `5 User Interface.txt` | React/TypeScript UI — 12 sections, DAG visualization, WebSocket streaming |
| `6-CLI interface.txt` | Python/Typer CLI — structured commands, interactive mode |
| `8 — PLATFORM HARDENING, GOVERNANCE & TESTING SPEC.txt` | Observability, audit logging, idempotency, Pytest + Playwright strategy |
| `2 PROPOSED DATABASE SCHEMA.txt` | Baseline schema — decisions refined in `knowledge/schema-decisions.md`. Registered in `MASTER_SCHEMA.md`. |

---

## Technology Stack

**Backend:** FastAPI (Python) + SQLite (WAL mode, mandatory per root CLAUDE.md)
**Frontend:** React + TypeScript, Vite or Next.js, TailwindCSS + shadcn/ui, React Flow (DAG viz), Monaco Editor, ECharts
**CLI:** Python + Typer, httpx, rich
**LLM Providers:** Ollama (local), OpenAI, Anthropic, vLLM, llama.cpp — all abstracted behind a pluggable Model Interface Layer
**Processing:** Whisper/faster-whisper (audio), Tesseract/PaddleOCR (OCR)
**Testing:** Pytest (unit/integration) + Playwright (E2E)

---

## Implementation Phases

**Phase 1 (start here):**
1. Model Interface Layer — pluggable provider abstraction
2. Execution Engine — task orchestration loop
3. Grading Engine — deterministic scoring (0–100 from compiler/test/lint output)
4. Telemetry Logger
5. Basic Router — rule-based model selection
6. Context Escalation — three tiers: Execution (16k), Hybrid (24k), Planning (32k)
7. Codex Interface — stub only

**Phase 2:** Full Codex (lessons DB), Plan DAG execution, Context OS (chunking, compression)
**Phase 3:** Multi-agent roles, replay system, distributed workers

---

## Core API Modules (from Part 4)

```
POST /tasks                    # Create task
POST /tasks/{id}/execute       # Execute task
POST /plans                    # Create plan
GET  /router/select            # Model selection
POST /models/run               # Run model
POST /validate                 # Run validators
POST /codex/query              # Query lessons
GET  /api/health               # {"status": "ok"} — Atlas polls every 30s
GET  /metrics                  # Prometheus-compatible
POST /runs/{id}/replay         # Exact replay
```

---

## Key Architectural Principles

- **Deterministic validation is ground truth** — never trust model self-assessment; scores derive from compiler/test/lint output only
- **Persistent Codex** — failures stored with patterns/root causes; queried before each task; only promoted after verified resolution
- **Plan-driven DAG execution** — strict separation of PLANNING, EXECUTION, and REPLAN modes
- **Hardware-aware routing** — on startup detect GPU/VRAM/tokens-per-sec; adapt context tiers and model routing
- **Observable and replayable** — log model_id, context_size, prompt_version, chunk hashes, tool commands for every run
- **API-first** — internal modules use the same REST/WebSocket interfaces as external callers

---

## Ecosystem Integration

- **Port:** 8860 (claimed — see root `CLAUDE.md` Port Registry)
- **Schema:** Registered in `E:\0-Automated-Apps\MASTER_SCHEMA.md` § Spoke: Mission_Control
- **Knowledge base:** `knowledge/` directory mirrors AI-Learning-CODEX format. Read `knowledge/INDEX.md` at session start when working on MC-specific architectural decisions. See `knowledge/build-roadmap.md` for full phase plan.
- **No spoke-to-spoke calls** — all cross-project communication routes through Atlas (:8888)

## Key Schema Rules (from knowledge/schema-decisions.md)

- Field is `task_status`, not `status` (Rule 17 — global uniqueness)
- Task/job/log IDs use **ULID**; artifact/codex IDs use **UUID**
- Every Codex entry requires `model_source` field: `"cloud:anthropic"`, `"local:ollama"`, `"human"`, etc.
- `codex_candidates` uses `codex_promoted`, not `promoted`
- `artifacts_raw` includes `page_url` (nullable) — populate on any external ingest
- `models` table ≠ Atlas `llm_providers` — different purposes, different DBs

---

## Config & Secrets

- Backend env vars: GPU/VRAM detection, model paths, pipeline versions, worker config, feature flags
- CLI user config: `~/.mission-control/config.json` (`api_endpoint`, `api_key`, `default_project`, `default_model`)
- CLI env overrides: `MISSION_CONTROL_API_KEY`, `MISSION_CONTROL_ENDPOINT`
- All secrets in `.env` only — never in code or these docs
