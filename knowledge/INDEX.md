# Mission Control — Knowledge Base Index

**Version:** 0.1
**Scope:** Mission Control project (`E:\0-Automated-Apps\Mission_Control`)
**Format:** Mirrors AI-Learning-CODEX structure for eventual merge into Supreme Master Codex
**Source tracking:** Every entry records `logged_by` (claude | local_worker | human)

---

## Hard Rules

### Rule 1 — Check Reference KB at the Start of Every Implementation Session

**`E:\0-Automated-Apps\Reference\REFERENCE_INDEX.md`** contains pre-extracted patterns from 32 reference repos. Check it before implementing any component. Several patterns (GradingEngine, exception classification, execution loop, StructuredLogger, LiteLLM Router config) are ready to use verbatim — do not reinvent them.

| Building... | Reference file |
|---|---|
| Model Interface Layer / LiteLLM Router | `kb-llm-routing-providers.md` |
| Execution Engine / DAG / state machine | `kb-orchestration-frameworks.md` |
| Grading Engine / retry logic / telemetry | `kb-execution-validation-telemetry.md` |
| Codex / FTS / persistent memory | `kb-persistent-memory-rag.md` |
| Worker scheduler / background jobs | `kb-workflow-orchestration.md` |
| OCR / audio / document pipelines | `kb-document-processing.md` |

### Rule 2 — Check MC Knowledge Base Before Building
At session start, or after 2 failed attempts on the same problem:
Scan the Quick-Find table below. Match your symptom → read the linked file.

**Check proactively when the task involves:**
- LLM provider routing or model selection
- SQLite schema changes or migrations
- Context window management
- Task execution loop design
- Codex query/promotion logic
- FastAPI + async patterns
- Atlas spoke integration

### Rule 3 — Log Before Closing
When you make a significant architectural decision, solve a non-obvious problem,
or identify a pattern worth preserving:
1. Find or create the right topic file
2. Add a dated entry (format below)
3. Update this INDEX
4. Logged_by: record whether this was discovered by claude or local_worker

### Rule 4 — Source Matters
Every entry must record who discovered it. This is prep for the Supreme Master Codex
where cloud and local agents cross-check each other's knowledge.
- `logged_by: claude` — discovered in a Claude Code session
- `logged_by: local_worker` — discovered by a local LLM execution worker
- `logged_by: human` — human override or manual correction

### Rule 5 — DB Migration Tracker
Check thresholds at session close. When any threshold is hit, note it for the user.
See DB Migration Tracker section below.

### Rule 6 — Two Codex Systems, One Future (No Duplication)
Two knowledge systems exist until post-v1 merge. Strict domain routing:
- **Platform/technical knowledge applicable to ALL projects** → AI-Learning-CODEX only
- **Mission Control-specific architectural decisions** → MC knowledge base only
- NEVER write the same content in both. Use `see also` links to cross-reference.
- Platform discoveries made WHILE working on MC go to AI-Learning-CODEX (all projects benefit).
- MC-specific implementation discoveries go here.

**Full dedup routing rules:** [build-roadmap.md](build-roadmap.md) → "Codex Deduplication Rule"

---

## Topic Files

| File | Topic | Last Updated | Logged By |
|------|-------|-------------|-----------|
| [architecture-decisions.md](architecture-decisions.md) | Core architectural choices and their rationale | 2026-02-27 | claude |
| [schema-decisions.md](schema-decisions.md) | Database schema choices, field naming, compatibility notes | 2026-02-27 | claude |
| [integration-patterns.md](integration-patterns.md) | Atlas spoke integration, cross-project patterns | 2026-02-27 | claude |
| [build-roadmap.md](build-roadmap.md) | Phase-by-phase build plan, TODO tracking | 2026-02-27 | claude |

---

## Quick-Find by Symptom

**Severity:** 🔴 Will break or block — act before writing code. 🔵 Design reference.

| Symptom / Decision Point | File | Section |
|--------------------------|------|---------|
| 🔴 Does Mission Control need its own ChromaDB? | [architecture-decisions.md](architecture-decisions.md) | No Own ChromaDB |
| 🔵 Which LLM provider abstraction to use | [architecture-decisions.md](architecture-decisions.md) | LiteLLM |
| 🔵 Model capability categories (fast/reasoning/planner) | [architecture-decisions.md](architecture-decisions.md) | Model Classes |
| 🔴 Field named `status` — naming conflict risk | [schema-decisions.md](schema-decisions.md) | status field |
| 🔵 Why `task_status` not `status` | [schema-decisions.md](schema-decisions.md) | status field |
| 🔴 Adding a new column — check ecosystem first | [schema-decisions.md](schema-decisions.md) | Rule 17 |
| 🔵 Where `models` table differs from Atlas `llm_providers` | [schema-decisions.md](schema-decisions.md) | models table |
| 🔵 Port for Mission Control | [integration-patterns.md](integration-patterns.md) | Port |
| 🔵 What to expose to Atlas vs keep internal | [integration-patterns.md](integration-patterns.md) | Atlas Surface |
| 🔵 AI-Learning-CODEX vs Mission Control Codex — which to use | [architecture-decisions.md](architecture-decisions.md) | Codex Separation |
| 🔴 Where to log a new discovery — which Codex system? | [build-roadmap.md](build-roadmap.md) | Codex Deduplication Rule |
| 🔵 Supreme Master Codex — when and how | [build-roadmap.md](build-roadmap.md) | Post-v1 |
| 🔴 Cross-project `status` field naming debt | [build-roadmap.md](build-roadmap.md) | Cross-Project TODO |
| 🔵 Full 8-phase build order and deliverables | [build-roadmap.md](build-roadmap.md) | Phase 0–8 |
| 🔴 Pre-build checklist — what's still pending | [build-roadmap.md](build-roadmap.md) | Phase 0 |

---

## Entry Format

```markdown
### [Short decision/problem title] — Discovered YYYY-MM-DD
**Logged by:** claude | local_worker | human
**Confirmed:** 1 encounter — [context, date]
**Severity:** 🔴 Must act | 🔵 Reference
**Context:** What situation surfaced this
**Decision/Finding:**
[The actual content]
**Rationale:**
[Why this choice was made]
**Alternatives considered:**
[What else was evaluated]
```

---

## DB Migration Tracker

This knowledge base lives as markdown until it outgrows it.
Track metrics here. When a threshold is hit, note it for the user.

**Current metrics:**

| Metric | Current | Threshold |
|--------|---------|-----------|
| Quick-Find entries | 15 | **40** |
| Topic files | 4 | **15** |
| Named entries across all files | ~20 | **75** |

**What the DB enables (when ready):**
- Query by `logged_by` — see what claude discovered vs local worker
- `SELECT * WHERE confirmed_count >= 3` — battle-tested patterns only
- Cross-reference with AI-Learning-CODEX entries by tag
- Staleness detection (entries not confirmed in 90 days)
- Foundation layer of the Supreme Master Codex merge

**Migration target:** Mission Control's own Codex database (Phase 2 of build)
**Not AI-Learning-CODEX** — those stay separate until Supreme Master Codex merge (post-v1)

---

## Version History

| Version | Date | Change |
|---------|------|--------|
| 0.1 | 2026-02-27 | Initial creation — 4 topic files, pre-build knowledge capture |
| 0.2 | 2026-02-27 | Added build-roadmap.md, Rule 5 (dedup routing), 4 new Quick-Find entries |
| 0.3 | 2026-02-27 | Added Rule 1 (Reference KB check), renumbered rules 2–6 |
