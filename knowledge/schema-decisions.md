# Schema Decisions — Mission Control

---

### `task_status` not `status` — Rule 17 Compliance — Decided 2026-02-27
**Logged by:** claude
**Confirmed:** 1 encounter — ecosystem compatibility check
**Severity:** 🔴 Must act — apply before schema implementation

**Context:** Root CLAUDE.md Rule 17 requires globally unique, descriptive field names. The word `status` appears in 4+ existing spokes: civic_media.processing_jobs.status, Facebook-Offline.imports.status, Shasta-Campaign-Finance.filers.status. An LLM building a cross-system query cannot unambiguously resolve `status`.

**Decision:** In Mission Control's schema, rename:
- `tasks.status` → `tasks.task_status`
- `file_chunks` has no status field — no change needed
- `codex_candidates.promoted` → `codex_candidates.codex_promoted` (clearer scope)

**Cross-project debt:** Other existing spokes have ambiguous `status` fields. This is tracked as a follow-up TODO in `build-roadmap.md`. It is NOT Mission Control's problem to fix — those are separate projects requiring user approval. This entry exists so future agents know the naming debt exists.

---

### `models` Table vs Atlas `llm_providers` — Decided 2026-02-27
**Logged by:** claude
**Severity:** 🔵 Reference — document clearly, no code change needed

**Context:** Atlas has an `llm_providers` table (for the chat UI: API keys, display names, provider_type). Mission Control has a `models` table (execution routing registry: capability class, quant, context limit, benchmark speed).

**Decision:** Keep both. They serve different purposes and live in different databases.
- `Atlas.llm_providers` = "which API key/endpoint to use for Atlas chat conversations"
- `Mission_Control.models` = "which model configuration to use for AI task execution"

**Documentation rule:** Any agent working across both projects must be told this distinction explicitly. Add to both CLAUDE.md files.

**models table schema (final):**
```sql
CREATE TABLE models (
    id TEXT PRIMARY KEY,              -- e.g. "ollama/qwen2.5:32b" (LiteLLM format)
    display_name TEXT NOT NULL,
    provider TEXT NOT NULL,           -- ollama | openai | anthropic | vllm
    capability_class TEXT NOT NULL,   -- fast_model | reasoning_model | planner_model
    quant TEXT,                       -- q4_k_m, q8_0, fp16, etc.
    max_context INTEGER,
    benchmark_tokens_per_sec REAL,
    deprecated INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

### `page_url` on Artifacts — Decided 2026-02-27
**Logged by:** claude
**Severity:** 🔵 Reference — pre-emptive compliance with Rule 3

**Decision:** Add `page_url TEXT` to `artifacts_raw` table even though ingestion is not planned for v1. The field is nullable. When data IS ingested from an external source, the page_url (human-browsable URL) must be stored.

**Pattern for automatic capture:**
```python
# Any ingest endpoint that accepts an artifact from an external source:
# Must accept optional page_url parameter
# Must store it in artifacts_raw.page_url
@app.post("/artifacts/ingest")
async def ingest_artifact(
    file: UploadFile,
    source_url: str | None = None,    # raw file URL
    page_url: str | None = None,      # human-browsable URL (required if external)
):
    ...
```

---

### UUID TEXT vs INTEGER PK — Decided 2026-02-27
**Logged by:** claude
**Severity:** 🔴 Must follow — avoid repeating Shasta-Campaign-Finance mistake

**Context:** Shasta-Campaign-Finance used UUID strings for person_id, which caused type-casting issues in Atlas unified_people. The root CLAUDE.md warns about this explicitly.

**Decision for Mission Control:**
- Internal records (projects, tasks, models, codex entries): `TEXT PRIMARY KEY` with UUID/ULID is acceptable because Mission Control records do NOT federate to Atlas unified_people.
- If Mission Control ever adds a `people` table: must use `INTEGER PRIMARY KEY` to be Atlas-compatible.
- Mission Control has NO people records planned — this is informational only.

---

### ULID for Task IDs — Decided 2026-02-27
**Logged by:** claude
**Severity:** 🔵 Reference

**Decision:** Use ULID (Universally Unique Lexicographically Sortable Identifier) for task_id, execution_log_id, and job_id instead of UUID.

**Rationale:** ULIDs sort chronologically, which is useful for:
- Pagination by ID (instead of by timestamp)
- Efficient range queries on recent tasks
- Human-readable ordering in logs

```python
# pip install python-ulid
from ulid import ULID
task_id = str(ULID())  # "01ARZ3NDEKTSV4RRFFQ69G5FAV"
```

**Use UUID for:** artifact_id (to match industry convention for content-addressed storage), codex entry IDs.

---

### Stack Trace Hashing for Dedup — Decided 2026-02-27
**Logged by:** claude
**Severity:** 🔵 Reference

**Decision:** Hash normalized stack traces and store in `execution_logs.stack_trace_hash`. Used for:
- Deduplication of alerts (same bug → one alert, not hundreds)
- Clustering in `failure_events` table
- Codex pattern matching (similar failures → same Codex entry)

```python
def hash_stack_trace(exc: Exception) -> str:
    import traceback, hashlib
    frames = traceback.extract_tb(exc.__traceback__)
    normalized = [f"{f.filename.split('/')[-1]}:{f.name}" for f in frames]
    key = "|".join(normalized) + f"|{type(exc).__name__}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]
```

---

### Codex Cloud/Local Source Separation — Decided 2026-02-27
**Logged by:** claude
**Severity:** 🔴 Must implement correctly — foundation of Supreme Master Codex

**Decision:** Every Codex entry (in both `master_codex` and `project_codex` tables) must record `model_source` using a structured format:

```
model_source values:
  "cloud:anthropic"     — Claude (cloud) discovered this
  "cloud:openai"        — OpenAI cloud model
  "local:ollama"        — Local worker (Ollama) discovered this
  "local:vllm"          — Local vLLM worker
  "human"               — Human override or manual entry
```

**Cross-reading:** Both sources CAN read each other's entries. Supersession must be explicit:
```sql
CREATE TABLE codex_supersessions (
    id TEXT PRIMARY KEY,
    old_entry_id TEXT NOT NULL,
    new_entry_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    superseded_by_source TEXT NOT NULL,  -- who made the call
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
-- Old entries are NEVER deleted — marked superseded, remain queryable
```

**This is the structural foundation of the Supreme Master Codex.**
