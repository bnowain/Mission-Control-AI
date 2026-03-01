# Mission Control — How the AI Works
**A plain-language guide to the execution engine, learning system, and multi-model routing**

---

## What Mission Control Actually Is

Mission Control is not a chatbot. It is an **execution operating system for LLM-based engineering work**.

You give it a task — fix a bug, write a test, refactor a module. It:
1. Picks the right model for that task
2. Runs the model against your prompt
3. Scores the output with a real compiler/linter/test runner (not the model's own judgment)
4. Retries or escalates if the score is too low
5. Stores what went wrong in a persistent memory (the Codex) so future tasks benefit

The models are workers. The framework is the decision-maker.

---

## The Execution Loop

Every task runs through this sequence:

```
Task created
    ↓
[Codex query] — has this type of problem been seen before?
    ↓
[RAG injection] — inject relevant code context, past artifacts, web pages
    ↓
[Router] — select the right model and context window size
    ↓
[Model call] — LiteLLM sends the prompt to the selected model
    ↓
[Chain-of-thought extraction] — strip <think> blocks before grading
    ↓
[Grading Engine] — compiler + tests + linter = score 0–100
    ↓
Score ≥ threshold?
    Yes → log result, update Codex candidate, done
    No  → retry (up to 5 times) or escalate context window
              ↓
         Max retries hit → promote failure to Codex candidate
```

The key principle: **deterministic validators are ground truth**, not the model's self-assessment. A score of 100 means the compiler accepted it, tests passed, and linter is clean.

---

## How the System Learns (The Codex)

The Codex is a persistent failure memory. It has two levels:

### Level 1 — Candidates (`codex_candidates`)
When a task fails after exhausting retries, the system creates a candidate entry:
- Issue signature (SHA256 hash of the stack trace or failure type)
- Proposed root cause
- Proposed resolution

Candidates are unverified. They're hypotheses.

### Level 2 — Master Codex (`master_codex`)
A candidate is promoted to the master Codex when one of three conditions is met:
- The same failure pattern recurs **and** a subsequent run with the resolution succeeds (automated verification)
- A human explicitly promotes it via the API (`POST /codex/candidate/{id}/promote`)
- Downstream breakage is detected after a "successful" run (score was high but broke something else)

Once in the master Codex, every future task of the same type gets that lesson injected into its prompt before the model runs:

```
[CODEX LESSON — confidence 0.87]
Root cause: Missing null check before accessing .children property
Prevention: Always guard array access with Array.isArray() in recursive traversal functions
```

The model sees this before it ever generates a line of code.

### What Gets Stored Per Entry
- `issue_signature` — hashed fingerprint of the failure class
- `root_cause` — what actually caused the failure
- `prevention_guideline` — the instruction injected into future prompts
- `confidence_score` — 0.0–1.0, rises with each verified resolution
- `model_source` — which model or human authored the entry (`cloud:anthropic`, `local:ollama`, `human`)
- `occurrence_count` — how many times this pattern has appeared
- `verified` — only promoted entries are used for injection

### The Loop Over Time
```
Task fails → candidate created
    ↓
Next similar task runs → candidate injected as hint (tentative)
    ↓
Task succeeds using that hint → candidate promoted, confidence rises
    ↓
Future tasks get a verified, high-confidence lesson
```

The system gets better at specific failure patterns it has actually seen. It does not generalize speculatively — only verified resolutions propagate.

---

## Multi-Model Routing

Mission Control talks to multiple models simultaneously and routes each task to the most appropriate one.

### The Five Capability Classes

| Class | Purpose | Typical Models |
|---|---|---|
| `fast_model` | Simple edits, doc generation, quick tasks | Qwen 2.5 7B, Llama 3.2 3B |
| `coder_model` | Code-specialized tasks | DeepSeek Coder V2, Qwen Coder |
| `reasoning_model` | Complex bugs, architecture analysis | DeepSeek R1, QwQ, phi4-reasoning |
| `heavy_model` | 70B+ local models for hard problems | Llama 3.1 70B (if VRAM allows) |
| `planner_model` | Planning, no VRAM requirement | Claude Code, GPT-4o |

### How a Model Gets Selected

1. **Task type** determines the base capability class:
   - `bug_fix` → `coder_model`
   - `architecture_design` → `planner_model`
   - `generic` → `fast_model`

2. **Retry count** escalates the class:
   - First attempt → selected class
   - After 2 failures → step up one class (fast → coder → reasoning)

3. **Hardware detection** constrains local options:
   - On startup, Mission Control detects GPU, VRAM, and measures tokens/sec
   - A 12GB GPU can run reasoning models; a 4GB GPU is limited to fast models
   - Cloud models have no VRAM constraint

4. **Router stats** refine selection over time:
   - Average score per model per task type is tracked
   - If `deepseek-r1:7b` consistently scores 85+ on `bug_fix` tasks, it becomes preferred
   - If it drops below threshold, another model from the same class is tried

### Context Window Escalation

Models have three context tiers:

| Tier | Size | When used |
|---|---|---|
| Execution | ~16k tokens | Default |
| Hybrid | ~24k tokens | After first context overflow |
| Planning | ~32k tokens | After second overflow |

If a model returns a `ContextWindowExceededError`, the system automatically escalates to the next tier — it does **not** retry at the same tier. After three escalations it raises a fatal error.

---

## Chain-of-Thought Handling

Reasoning models (DeepSeek R1, QwQ, phi4-reasoning) emit visible thinking before their answer. This comes in two forms:

**Form 1 — `<think>` blocks in the response text:**
```
<think>
The user wants to fix a null pointer. Let me trace the call stack...
The issue is in line 42 where children is accessed without a guard.
</think>

Here is the fix:
```python
if node.children is not None:
    for child in node.children:
```
```

**Form 2 — `reasoning_content` field** in the API response (DeepSeek R1 via LiteLLM).

In both cases, Mission Control:
1. Extracts the thinking text into `ExecutionResult.thinking_text`
2. Strips it from `response_text` before sending to the grading engine
3. The grading engine scores only the actual code output

The thinking is stored separately and visible in the Planner UI's collapsible thinking section. It is never sent back to the model as part of future prompts (that would inflate context unnecessarily).

---

## Online Models (Claude, GPT-4o, DeepSeek Cloud)

Mission Control abstracts all model providers behind a single interface using **LiteLLM**. Adding an online model requires only:
1. Setting the API key in `.env`
2. Adding the model to the `models` table with its capability class and provider
3. The router handles it identically to a local model

**Current supported providers:**

| Provider | Model format | Auth |
|---|---|---|
| Ollama (local) | `ollama/qwen2.5:32b` | None (localhost) |
| Anthropic | `anthropic/claude-opus-4-6` | `ANTHROPIC_API_KEY` |
| OpenAI | `openai/gpt-4o` | `OPENAI_API_KEY` |
| DeepSeek (cloud) | `deepseek/deepseek-chat` | `DEEPSEEK_API_KEY` |
| vLLM (local server) | `openai/model-name` | Optional |
| Claude Code CLI | subprocess `claude -p` | User's Claude subscription |

**The Claude Code provider** is special — it uses the `claude -p` CLI rather than the API. This means:
- Uses the user's existing Claude subscription (no API billing per token)
- Can access Claude's full tool-use capabilities (Read, Edit, Bash, etc.) the same way Claude Code does interactively
- Output streams line-by-line via subprocess stdout
- Used specifically for planning mode — not for ordinary task execution

---

## The Planner

The planner is a specialized mode for generating implementation plans before writing any code. Two variants:

### Claude Planning Mode
Spawns `claude -p --verbose` as a subprocess. The verbose flag makes Claude emit intermediate thinking steps as it works — tool uses, file reads, reasoning steps. These are parsed and forwarded to the browser as Server-Sent Events in real time.

You see exactly what Claude is doing: which files it reads, what it's reasoning about, each step of the plan as it forms.

### Local Reasoning Mode
Streams output from a local reasoning model (DeepSeek R1, QwQ) via LiteLLM. The stream is parsed token-by-token:
- Tokens inside `<think>...</think>` → emitted as `thinking` SSE events (shown in collapsible panel)
- Tokens outside `<think>` → emitted as `output` events (shown as the plan)

Both modes support:
- **Cancel via ESC** or the Cancel button — terminates the subprocess or closes the LiteLLM stream
- **Client disconnect detection** — if you close the browser tab, the backend terminates the session
- **Live streaming** — no buffering, events arrive as they're generated

---

## RAG — Retrieval-Augmented Generation

Before every task execution, Mission Control automatically injects relevant context from three sources:

**1. Codebase index** — your project's source files, indexed as overlapping 512-token chunks. Top-5 most similar chunks to the task prompt are injected.

**2. Artifacts** — previously processed documents (PDFs, audio transcripts, web pages). Top-3 most relevant chunks.

**3. Web pages** — any URLs you've ingested via `mission-control artifacts ingest --url <url>`. Top-2 chunks.

All embedding and search runs locally via Ollama (`nomic-embed-text` model). If Ollama is offline, RAG is silently skipped — execution continues without it.

The injected context looks like:
```
[RAG CONTEXT — 8 chunks from codebase:5, artifact:3]
# From src/parser.py (chunk 3)
def parse_node(node, depth=0):
    if depth > MAX_DEPTH:
        return None
    ...
[END RAG CONTEXT]
```

This arrives in the prompt before the task description, giving the model grounded knowledge about your actual codebase rather than relying on general training data.

---

## Grading Engine

The grading engine produces a score from 0–100 based entirely on deterministic outputs:

| Component | Weight | What it checks |
|---|---|---|
| Compile success | +40 | Does the code parse and compile without errors? |
| Tests pass | +30 | Do the existing test suite pass? |
| Lint pass | +15 | Does it pass the configured linter (ruff, eslint, etc.)? |
| Runtime success | +15 | Does the code run without crashing? |
| Retry penalty | −10/retry | Capped at −30 |
| Human intervention | −20 | If a human had to manually fix the output |
| Downstream breakage | −25 | If the change broke another test or module |
| Architecture change | −30 | If an unapproved architectural change was made |

**Score ≥ 70 = pass** (configurable). Below that, the execution loop retries or escalates.

The model never self-grades. It has no input into its own score.

---

## Data Flow Summary

```
User prompt
    │
    ├── [Codex] Inject prevention guidelines from past failures
    ├── [RAG] Inject relevant code/artifact/web context
    │
    ▼
Prompt sent to model (via LiteLLM → Ollama / Anthropic / OpenAI / etc.)
    │
    ▼
Raw response
    │
    ├── [CoT extractor] Strip <think> blocks → store as thinking_text
    │
    ▼
Clean response_text
    │
    ▼
[Grading Engine] Compile + test + lint → score 0–100
    │
    ├── Pass → log to execution_logs, update router stats, store Codex candidate
    └── Fail → retry with escalated model/context, or raise fatal error
                    │
                    └── Failure stored as Codex candidate for future learning
```

---

## Where Everything Lives

| What | Where |
|---|---|
| SQLite database | `database/mission_control.db` (WAL mode) |
| Model routing logic | `app/router/adaptive.py` |
| Execution loop | `app/core/execution_loop.py` |
| Grading engine | `app/grading/engine.py` |
| Codex engine | `app/codex/engine.py` |
| RAG engine | `app/rag/engine.py` |
| CoT extraction | `app/models/executor.py` → `_extract_thinking()` |
| Claude Code provider | `app/models/claude_code_provider.py` |
| Planner logic | `app/models/planner.py` |
| Planner API (SSE) | `app/api/planner_api.py` |
| REST API entry point | `app/main.py` (port 8860) |
| Frontend | `frontend/` (React + Vite, port 5174) |
| CLI | `cli/` (`mission-control` command) |

---

## Running It

```bash
# Start backend
uvicorn app.main:app --port 8860 --reload

# Start frontend (separate terminal)
cd frontend && npm run dev

# CLI
mission-control --help
mission-control task run --prompt "Fix the null pointer in parser.py"
mission-control rag index --path ./src --project my-project
```

Open `http://localhost:5174` for the UI. The Planner is at `/planner`.

---

## Coder Communication Style — Progress Notifications

When the AI coder is executing a build session, it should send human-readable progress updates at natural checkpoints — not on every file write, but when something meaningful has happened or a decision point has been reached.

### When to Send a Progress Update

- After completing a logical chunk of work (e.g., finishing a module, all tests passing)
- When something unexpected is found that changes the approach
- When blocked and needing to choose between options
- At the end of a session to summarize what changed

### What Makes a Good Update

**Be concrete.** Name the actual file, endpoint, test count, or model:
- "33 tests passing, build clean at 333KB" — not "tests look good"
- "Added `_extract_thinking()` to `app/models/executor.py`" — not "updated the executor"

**State what was found, not just what was done.** If you checked the roadmap, say what you found. If a test failed for a specific reason, say the reason.

**When there are choices, lay them out plainly:**
```
Blocked on X. Options:
- (a) patch at the source module instead — fixes the mock target issue
- (b) restructure the import — cleaner but touches more files
Going with (a) unless you prefer otherwise.
```

**At session end, summarize briefly:**
```
Files changed: executor.py, schemas.py, claude_code_provider.py (new),
               planner.py (new), planner_api.py (new), test_planner.py (33 tests)
Tests: 284 passed, 15 skipped, 0 failures
Build: 333KB, 0 TypeScript errors
Next: end-to-end smoke test against live Ollama
```

### What to Skip
- Filler ("Great!", "Certainly!", "I'll now proceed to...")
- Explaining what common tools do
- Repeating back what the user just said
- Updates on individual file reads/searches — those are too granular
