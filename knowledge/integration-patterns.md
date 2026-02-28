# Integration Patterns — Mission Control

---

### Atlas Spoke Registration — Decided 2026-02-27
**Logged by:** claude
**Severity:** 🔴 Must implement before going live

**Decision:** Mission Control is a Spoke in the Atlas ecosystem (not standalone).

**Port:** 8860 (claimed 2026-02-27 in root CLAUDE.md and MASTER_INDEX.md)
**DB:** `Mission_Control/database/mission_control.db`
**Framework:** FastAPI (async)

**What to expose to Atlas:**
```
✅ GET /api/health          → {"status": "ok"}  — Atlas polls every 30s
✅ GET /api/codex/search    → Codex lessons search (q, limit, offset)
✅ GET /api/router/stats    → Model performance stats (read-only summary)

❌ NOT exposed to Atlas:
   - Raw execution telemetry (internal infrastructure data)
   - Task management endpoints (not Atlas business)
   - Model routing internals
   - Worker status (not civic data)
```

**Atlas search response shape (required):**
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

**Registration checklist (complete during Atlas integration phase):**
- [ ] Schema registered in MASTER_SCHEMA.md
- [ ] Spoke section added to master_codex.md
- [ ] Port in MASTER_INDEX.md and root CLAUDE.md ✅ (done 2026-02-27)
- [ ] Added to Atlas config.py SPOKE_URLS
- [ ] Search keywords in Atlas query_classifier.py
- [ ] Searcher in Atlas unified_search.py
- [ ] /api/health responding before Atlas integration

---

### No Direct Spoke-to-Spoke Calls — Confirmed 2026-02-27
**Logged by:** claude
**Severity:** 🔴 Hard rule — no exceptions without explicit approval

**Rule:** Mission Control must NOT call civic_media, Shasta-DB, or any other spoke directly. All cross-project communication routes through Atlas (:8888).

**Only approved exception in ecosystem:** Shasta-PRA-Backup → civic_media POST /api/transcribe (pre-existing approval). Mission Control has no such exception.

**If Mission Control needs data from civic_media:** Route through Atlas POST /api/chat or GET /api/search.

---

### AI-Learning-CODEX — Read-Only Reference — Decided 2026-02-27
**Logged by:** claude
**Severity:** 🔵 Reference

**Decision:** During Mission Control's build, agents should reference AI-Learning-CODEX (at E:\0-Automated-Apps\AI-Learning-CODEX\) as a read-only knowledge source. Mission Control does NOT write to AI-Learning-CODEX — each system maintains its own knowledge base.

**When to check AI-Learning-CODEX:**
- Python ABI/version compatibility issues
- Windows-specific traps (encoding, paths, SQLite locking)
- Playwright automation
- Celery/Redis patterns
- Blender (unlikely but possible)

**When to write to Mission Control knowledge base (this directory):**
- Decisions specific to Mission Control's architecture
- Execution engine patterns
- LLM routing discoveries
- Codex design choices

**NOT yet merged** — see Supreme Master Codex roadmap in build-roadmap.md

---

### Reference KB Available to All Projects — Noted 2026-02-27
**Logged by:** claude
**Severity:** 🔵 Reference

The reference knowledge base at `E:\0-Automated-Apps\Reference\` is available to all projects. Contains extracted patterns from 32 reference repos. Key files:
- `REFERENCE_INDEX.md` — quick lookup table
- `kb-llm-routing-providers.md` — LiteLLM, Instructor, DSPy, Semantic Kernel
- `kb-orchestration-frameworks.md` — LangGraph, CrewAI, Plandex, OpenHands, AutoGen
- `kb-persistent-memory-rag.md` — Mem0, Haystack, LlamaIndex, RAGFlow
- `kb-document-processing.md` — Docling, Marker, Surya, Ollama
- `kb-execution-validation-telemetry.md` — Aider, Cline, Continue, n8n
- `kb-workflow-orchestration.md` — Prefect, Temporal
