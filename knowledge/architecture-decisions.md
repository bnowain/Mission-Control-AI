# Architecture Decisions — Mission Control

---

### Warm/Cold VRAM Awareness + Codex Confidence Integration — Phase 3 Requirement — 2026-02-28
**Logged by:** claude
**Severity:** 🟡 Phase 3 — do not implement in Phase 1/2

**Decision:** The router's warm/cold VRAM state awareness and the Codex confidence_score must be connected in Phase 3. Two systems that are currently independent need to become a feedback loop.

**Links:**
1. `confidence_score >= 0.85` on a Codex entry → router should skip the cheap model and route directly to the known-good model, then pre-warm it before the task starts.
2. `confidence_score < 0.50` → try cheapest model first; accept cold-start penalty since we're learning.
3. `tokens_per_second` in `execution_logs` is currently contaminated by cold-start VRAM load time. In Phase 3, track `tokens_per_second_cold` (first call) and `tokens_per_second_warm` (subsequent) separately so model performance comparisons are accurate.
4. Track escalation_rate per issue signature: if a task type escalates 8/10 times, pre-warm the escalation target when that task is queued.

**What to build in Phase 3:**
- `app/router/warmup_manager.py` — polls `GET /api/ps` on Ollama to track warm/cold state
- `execution_logs`: add `tokens_per_second_cold REAL` + `tokens_per_second_warm REAL` columns (additive migration)
- `master_codex`: add `escalation_rate REAL` column (additive migration)
- `app/router/adaptive.py`: query Codex confidence before `select()` — high-confidence entries override task_type routing

**Do not implement before Phase 3.** Foundation is already in the schema (confidence_score, occurrence_count, execution_logs telemetry).

---

### No Own ChromaDB — Use SQLite FTS5 + Atlas — Decided 2026-02-27
**Logged by:** claude
**Severity:** 🔴 Must follow — matches ecosystem hard rule

**Decision:** Mission Control does NOT run its own ChromaDB instance.

**Internal Codex search** → SQLite FTS5. At Codex scale, full-text search is fast and sufficient.
**Ecosystem-level semantic search** → Atlas handles pre-indexing of MC's codex entries via its existing LazyChroma pattern, calling `GET /api/codex/search`.

**Rationale:**
- Ecosystem rule: only Atlas uses ChromaDB (MASTER_SCHEMA.md §Concerns #4)
- MC is an execution engine — it must not depend on Atlas being up to query its own internal memory
- `embedding BLOB` columns exist in the schema as nullable, optional future-proofing only

**What to build:** Add FTS5 virtual table over `master_codex` and `project_codex` for fast text search. Do not implement the embedding path in Phase 1 or 2.

---

### LiteLLM as Model Interface Layer — Decided 2026-02-27
**Logged by:** claude
**Confirmed:** 1 encounter — pre-build design session
**Severity:** 🔵 Reference
**Context:** Evaluated 6 LLM abstraction options from reference repos

**Decision:** Use LiteLLM's `Router` class as the Model Interface Layer. Do NOT build a custom provider abstraction.

**Rationale:**
- Handles 100+ providers with unified interface out of the box
- Cost/latency/load routing strategies already implemented
- Fallback chains + cooldown cache built in
- DualCache (in-memory + disk) available
- Standard OpenAI-compatible response format from all providers
- Active maintenance, battle-tested at scale

**How to use:**
```python
from litellm import Router
router = Router(
    model_list=[
        {"model_name": "fast_model", "litellm_params": {"model": "ollama/qwen2.5:7b", ...}},
        {"model_name": "reasoning_model", "litellm_params": {"model": "ollama/qwen2.5:32b", ...}},
        {"model_name": "planner_model", "litellm_params": {"model": "anthropic/claude-opus-4-6", ...}},
    ],
    routing_strategy="latency-based-routing",
    fallbacks=[{"fast_model": ["reasoning_model"]}],
)
```

**Never hardcode model names.** Use capability categories only: `fast_model`, `reasoning_model`, `planner_model`.

---

### Model Capability Categories — Decided 2026-02-27
**Logged by:** claude
**Severity:** 🔵 Reference

**Decision:** Three capability classes only. Map to actual models via config, never in code.

```python
CAPABILITY_CLASSES = {
    "fast_model":      {"min_vram_mb": 0,     "default_context": 16384},
    "reasoning_model": {"min_vram_mb": 20000, "default_context": 24576},
    "planner_model":   {"min_vram_mb": 40000, "default_context": 32768},
}
```

**Routing rules:**
- small edits, bug fixes → fast_model
- refactor_large, multi-file → reasoning_model
- architecture_design, replan → planner_model
- After retry threshold: escalate to next tier

---

### Instructor for Structured Output — Decided 2026-02-27
**Logged by:** claude
**Severity:** 🔵 Reference

**Decision:** Use Instructor to patch LiteLLM client for all structured output extraction.

**Rationale:** Provides Pydantic validation with retry-on-failure. On ValidationError, sends the error back to the LLM and retries. Eliminates manual JSON parsing and error handling.

```python
import instructor
client = instructor.from_litellm(litellm.completion)
result = client.chat.completions.create(
    model="fast_model",
    response_model=GradingResult,
    max_retries=3,
    messages=[...]
)
```

---

### CrewAI Flows Pattern for DAG Execution — Decided 2026-02-27
**Logged by:** claude
**Severity:** 🔵 Reference

**Decision:** Use CrewAI Flows @start/@listen/@router decorator pattern for the execution engine's state machine. Do NOT use the full CrewAI Crew (autonomous) mode.

**Rationale:**
- Deterministic event-driven routing (no LLM decides flow)
- Pydantic FlowState for type-safe state
- 5.76x faster than LangGraph in benchmarks
- Standalone (no LangChain dependency)

**Adapt the pattern** — do not import the full crewai package in production. Extract the pattern and implement the decorators natively to avoid dependency bloat.

---

### LangGraph Checkpoint Pattern for Persistence — Decided 2026-02-27
**Logged by:** claude
**Severity:** 🔵 Reference

**Decision:** Implement LangGraph's CheckpointTuple pattern for execution state persistence.

```python
# thread_id = execution session ID
# checkpoint stores: {config, state, metadata, parent_config, pending_writes}
# metadata: {source, step, parent_ids, run_id}
# Enables: replay, time-travel, resumption after crash
```

Use `ULID` (not UUID) for task IDs — lexicographically sortable by creation time.

---

### Codex Separation — Two Systems, One Future — Decided 2026-02-27
**Logged by:** claude
**Severity:** 🔴 Must understand before building

**Context:** 0-The-Beginning.txt wants a supreme master codex. AI-Learning-CODEX already exists.

**Decision (interim):**
- **AI-Learning-CODEX** = technical platform knowledge (Python bugs, Windows gotchas, Blender, etc.) → stays as markdown + gets its own simple sqlite3 DB when threshold hits. Independent of Mission Control.
- **Mission Control Codex** = AI execution patterns (task failures, model routing, prompt refinements, scoring history) → lives in Mission Control's database, queryable via API.
- **Supreme Master Codex** = post-v1 merge of both + all other project knowledge, with `logged_by` source tracking (claude vs local_worker vs human). This is the end-state, not the starting state.

**For now:** Build Mission Control's Codex as designed in Part 2 schema. Knowledge base text files (this directory) feed it during development.

**See:** `build-roadmap.md` → Supreme Master Codex section

---

### Prefect for Phase 1 Worker Scheduling — Decided 2026-02-27
**Logged by:** claude
**Severity:** 🔵 Reference

**Decision:** Use Prefect embedded mode (no server) for Phase 1 local task orchestration. Add Temporal in Phase 3 for distributed/durable execution.

**Rationale:** Prefect @task/@flow gives retry, state machine, observability with zero server overhead in embedded mode. Temporal is production-grade but adds gRPC + database server complexity not needed for Phase 1.

---

### Exponential Backoff Parameters — Decided 2026-02-27
**Logged by:** claude
**Severity:** 🔵 Reference

**Decision (from Aider analysis):**
- Start: 125ms
- Multiply: 2x per retry
- Cap: 60 seconds
- Max retries: 5 (configurable per task_type)
- Exception classification first: retryable vs non-retryable vs context-window-exceeded

`ContextWindowExceededError` → do NOT retry → trigger context tier escalation instead.

---

### Hard Loop Limit — Decided 2026-02-27
**Logged by:** claude
**Severity:** 🔴 Must implement

**Decision:** Every execution loop MUST have a hard cap.

```python
MAX_EXECUTION_LOOPS = 10   # per task (configurable)
MAX_REPLAN_CYCLES   = 3    # total replan attempts per plan
```

Without this, a stuck task will run forever burning tokens and compute.
