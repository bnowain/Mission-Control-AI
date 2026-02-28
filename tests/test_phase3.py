"""
Phase 3 tests — Plan DAG, Codex Promotion, Context OS, Instructions, Replay stubs.

All tests use TestClient (no running server). DB is shared with other tests —
cleanup is handled by using unique IDs and INSERT OR IGNORE.
"""

import json
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_project(project_id: str) -> None:
    """Pre-insert a project so FK constraints pass."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    client.post("/sql/query", json={
        "sql": "INSERT OR IGNORE INTO projects (id, name, created_at) VALUES (?, ?, ?)",
        "params": [project_id, f"Test ({project_id})", now],
        "write_mode": True,
    })


# ---------------------------------------------------------------------------
# Schema — verify v4 tables exist
# ---------------------------------------------------------------------------

def test_schema_v4_tables():
    r = client.post("/sql/query", json={
        "sql": "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name",
        "params": [],
    })
    assert r.status_code == 200
    table_names = [row[0] for row in r.json()["rows"]]
    for expected in ["plans", "plan_phases", "plan_steps", "execution_checkpoints",
                     "failure_clusters", "project_instructions", "context_compressions"]:
        assert expected in table_names, f"Missing table: {expected}"


def test_schema_version_is_4():
    r = client.post("/sql/query", json={
        "sql": "SELECT MAX(version) AS v FROM schema_version",
        "params": [],
    })
    assert r.status_code == 200
    assert r.json()["rows"][0][0] >= 4


# ---------------------------------------------------------------------------
# Plan DAG — full lifecycle
# ---------------------------------------------------------------------------

def test_create_plan():
    _ensure_project("p3-test-project")
    r = client.post("/plans", json={
        "project_id": "p3-test-project",
        "plan_title": "Test Plan",
        "phases": [
            {
                "phase_title": "Phase A",
                "steps": [
                    {"step_title": "Step 1", "step_type": "generic", "step_prompt": "Do step 1"},
                    {"step_title": "Step 2", "step_type": "generic", "depends_on": []},
                ]
            }
        ]
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["plan_status"] == "pending"
    assert body["plan_version"] == 1
    assert len(body["phases"]) == 1
    assert len(body["phases"][0]["steps"]) == 2
    return body["id"]


def test_get_plan():
    plan_id = test_create_plan()
    r = client.get(f"/plans/{plan_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == plan_id
    assert body["plan_title"] == "Test Plan"


def test_get_plan_not_found():
    r = client.get("/plans/nonexistent-plan-id")
    assert r.status_code == 404


def test_plan_execute_next_step():
    plan_id = test_create_plan()

    # Execute first step
    r = client.post(f"/plans/{plan_id}/execute")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["step_status"] == "running"
    assert body["step_title"] == "Step 1"
    step_id = body["id"]

    # Complete the step
    r2 = client.post(f"/plans/{plan_id}/steps/{step_id}/complete", params={"result_summary": "Done"})
    assert r2.status_code == 200
    assert r2.json()["step_status"] == "completed"

    # Execute second step
    r3 = client.post(f"/plans/{plan_id}/execute")
    assert r3.status_code == 200
    assert r3.json()["step_title"] == "Step 2"


def test_plan_dependency_blocks_step():
    """Step 2 depends on Step 1 — should not be runnable until Step 1 completes."""
    _ensure_project("p3-dep-test")
    r = client.post("/plans", json={
        "project_id": "p3-dep-test",
        "plan_title": "Dep Plan",
        "phases": [{
            "phase_title": "Phase A",
            "steps": [
                {"step_title": "Step 1", "step_type": "generic"},
                # Step 2 will get Step 1's id as a dependency — we test after creation
            ]
        }]
    })
    assert r.status_code == 201
    body = r.json()
    plan_id = body["id"]
    step1_id = body["phases"][0]["steps"][0]["id"]

    # Add Step 2 with dependency on Step 1 via SQL
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    from ulid import ULID
    step2_id = str(ULID())
    phase_id = body["phases"][0]["id"]
    client.post("/sql/query", json={
        "sql": "INSERT INTO plan_steps (id, phase_id, plan_id, step_index, step_title, step_type, step_status, depends_on, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        "params": [step2_id, phase_id, plan_id, 1, "Step 2", "generic", "pending", json.dumps([step1_id]), now, now],
        "write_mode": True,
    })

    # Execute — should get Step 1 (Step 2 is blocked)
    r2 = client.post(f"/plans/{plan_id}/execute")
    assert r2.status_code == 200
    assert r2.json()["id"] == step1_id


def test_plan_replan():
    plan_id = test_create_plan()
    r = client.post(f"/plans/{plan_id}/replan", json={
        "reason": "Requirements changed",
        "new_phases": None,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["plan_version"] == 2
    assert len(body["plan_diff_history"]) == 1
    assert body["plan_diff_history"][0]["diff"] == "Requirements changed"


def test_plan_diff():
    plan_id = test_create_plan()
    # Trigger replan first
    client.post(f"/plans/{plan_id}/replan", json={"reason": "v2 change"})
    r = client.get(f"/plans/{plan_id}/diff")
    assert r.status_code == 200
    body = r.json()
    assert "diff_history" in body
    assert body["plan_version"] == 2


def test_fail_step():
    plan_id = test_create_plan()
    r = client.post(f"/plans/{plan_id}/execute")
    assert r.status_code == 200
    step_id = r.json()["id"]

    r2 = client.post(f"/plans/{plan_id}/steps/{step_id}/fail", params={"reason": "compile error"})
    assert r2.status_code == 200
    assert r2.json()["step_status"] == "failed"


# ---------------------------------------------------------------------------
# Codex — real promote endpoint
# ---------------------------------------------------------------------------

def test_codex_promote_real():
    _ensure_project("p3-codex-test")
    from datetime import datetime, timezone
    import uuid
    now = datetime.now(timezone.utc).isoformat()

    # Create a task
    task_id_resp = client.post("/sql/query", json={
        "sql": "INSERT INTO tasks (id, project_id, task_type, signature, task_status, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        "params": ["p3-task-promote-test", "p3-codex-test", "generic", "sig-promote-test", "completed", now, now],
        "write_mode": True,
    })

    # Create a candidate
    candidate_id = str(uuid.uuid4())
    client.post("/sql/query", json={
        "sql": "INSERT INTO codex_candidates (id, task_id, issue_signature, proposed_root_cause, proposed_resolution, human_verified, codex_promoted, created_at) VALUES (?,?,?,?,?,1,0,?)",
        "params": [candidate_id, "p3-task-promote-test", "null-ptr-phase3", "Missing None check", "Add guard", now],
        "write_mode": True,
    })

    # Promote it
    r = client.post("/codex/promote", json={
        "candidate_id": candidate_id,
        "promoted_by": "human",
        "category": "null_handling",
        "scope": "global",
        "confidence_score": 0.9,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["candidate_id"] == candidate_id
    assert "master_codex_id" in body
    assert body["action"] in ("created", "updated")


def test_codex_promote_not_found():
    r = client.post("/codex/promote", json={
        "candidate_id": "nonexistent-candidate-id",
        "promoted_by": "human",
    })
    assert r.status_code == 404


def test_codex_promote_eligible_check():
    import uuid
    candidate_id = str(uuid.uuid4())
    r = client.get(f"/codex/promote/{candidate_id}/eligible")
    assert r.status_code == 200
    body = r.json()
    assert "eligible" in body
    assert "reason" in body


# ---------------------------------------------------------------------------
# Codex — failure clusters
# ---------------------------------------------------------------------------

def test_codex_clusters_empty():
    r = client.get("/codex/clusters")
    assert r.status_code == 200
    body = r.json()
    assert "clusters" in body
    assert "total" in body


def test_codex_cluster_upsert_and_fetch():
    from app.codex.clustering import upsert_cluster
    test_hash = "deadbeef12345678"
    upsert_cluster(test_hash)
    upsert_cluster(test_hash)  # Second upsert increments count

    r = client.get(f"/codex/clusters/{test_hash}")
    assert r.status_code == 200
    body = r.json()
    assert body["stack_trace_hash"] == test_hash
    assert body["occurrence_count"] >= 2


def test_codex_cluster_not_found():
    r = client.get("/codex/clusters/nonexistent-hash-xyz")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Context OS — chunk, compress, working set
# ---------------------------------------------------------------------------

def test_context_chunk():
    _ensure_project("p3-ctx-test")
    content = "line " * 600  # ~3000 chars, should produce 2+ chunks
    r = client.post("/context/chunk", json={
        "file_path": "test/file.py",
        "content": content,
        "project_id": "p3-ctx-test",
        "chunk_size": 1000,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["chunk_count"] >= 2
    assert len(body["chunk_ids"]) == body["chunk_count"]


def test_context_chunk_idempotent():
    """Same content → same chunk IDs (content-addressed)."""
    _ensure_project("p3-ctx-test")
    content = "idempotent test content " * 100
    r1 = client.post("/context/chunk", json={
        "file_path": "test/idempotent.py",
        "content": content,
        "project_id": "p3-ctx-test",
    })
    r2 = client.post("/context/chunk", json={
        "file_path": "test/idempotent.py",
        "content": content,
        "project_id": "p3-ctx-test",
    })
    assert r1.json()["chunk_ids"] == r2.json()["chunk_ids"]


def test_context_compress_under_budget():
    """Messages already within budget — returned unchanged."""
    messages = [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi"}]
    r = client.post("/context/compress", json={
        "task_id": "p3-compress-test-1",
        "messages": messages,
        "max_tokens": 10000,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["messages"]) == 2
    assert body["summary"] == ""


def test_context_compress_over_budget():
    """Messages over budget — should be compressed."""
    long_content = "word " * 3000  # ~15000 tokens
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": long_content},
        {"role": "assistant", "content": "I understand."},
        {"role": "user", "content": long_content},
        {"role": "assistant", "content": "Processing..."},
    ]
    r = client.post("/context/compress", json={
        "task_id": "p3-compress-test-2",
        "messages": messages,
        "max_tokens": 1000,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    # System message always kept; at least some compression happened
    assert body["original_messages"] == 5
    assert body["compressed_tokens"] < body["original_messages"] * 3000


def test_context_workingset():
    _ensure_project("p3-ctx-test")
    # First chunk a file
    content = "def foo():\n    pass\n" * 200
    client.post("/context/chunk", json={
        "file_path": "test/workingset.py",
        "content": content,
        "project_id": "p3-ctx-test",
        "chunk_size": 500,
    })

    r = client.post("/context/workingset", json={
        "task_id": "p3-ws-test",
        "file_paths": ["test/workingset.py"],
        "project_id": "p3-ctx-test",
        "token_budget": 2000,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["chunk_count"] >= 1
    assert body["total_tokens"] <= 2000 + 100  # small tolerance


def test_context_workingset_empty_file():
    """File not chunked yet — returns empty working set."""
    _ensure_project("p3-ctx-test")
    r = client.post("/context/workingset", json={
        "task_id": "p3-ws-empty",
        "file_paths": ["nonexistent/file.py"],
        "project_id": "p3-ctx-test",
        "token_budget": 4000,
    })
    assert r.status_code == 200
    assert r.json()["chunk_count"] == 0


# ---------------------------------------------------------------------------
# Instructions — persistent instruction layer
# ---------------------------------------------------------------------------

def test_create_and_list_instructions():
    _ensure_project("p3-inst-test")
    r = client.post("/instructions", json={
        "project_id": "p3-inst-test",
        "instruction_type": "project_rule",
        "content": "Always use WAL mode for SQLite.",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["instruction_type"] == "project_rule"
    assert body["active"] is True
    assert body["instruction_version"] == 1
    inst_id = body["id"]

    # List
    r2 = client.get("/instructions/p3-inst-test")
    assert r2.status_code == 200
    ids = [i["id"] for i in r2.json()]
    assert inst_id in ids


def test_deactivate_instruction():
    _ensure_project("p3-inst-test")
    r = client.post("/instructions", json={
        "project_id": "p3-inst-test",
        "instruction_type": "naming_convention",
        "content": "Use snake_case for all variables.",
    })
    assert r.status_code == 201
    inst_id = r.json()["id"]

    # Deactivate
    r2 = client.delete(f"/instructions/{inst_id}")
    assert r2.status_code == 204

    # Should no longer appear in active list
    r3 = client.get("/instructions/p3-inst-test")
    ids = [i["id"] for i in r3.json()]
    assert inst_id not in ids


# ---------------------------------------------------------------------------
# Validate endpoint (real — Phase 3 stubs still pass)
# ---------------------------------------------------------------------------

def test_validate_endpoint():
    r = client.post("/validate", json={
        "response_text": "def foo(): return 42",
        "task_type": "bug_fix",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert "compile_success" in body
    assert "tests_passed" in body
    # Phase 3: all validators are stubs that return True
    assert body["compile_success"] is True


# ---------------------------------------------------------------------------
# Replay stub → 404 for nonexistent run
# ---------------------------------------------------------------------------

def test_replay_nonexistent_run():
    r = client.post("/runs/nonexistent-run-id/replay")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Execution checkpoint — internal module test
# ---------------------------------------------------------------------------

def test_checkpoint_save_and_load():
    from app.core.plan_dag import CheckpointStore
    store = CheckpointStore()
    store.save("thread-123", "step-abc", {"status": "running", "attempt": 1})
    state = store.load("thread-123", "step-abc")
    assert state is not None
    assert state["status"] == "running"
    assert state["attempt"] == 1

    # Overwrite
    store.save("thread-123", "step-abc", {"status": "completed", "attempt": 1})
    state2 = store.load("thread-123", "step-abc")
    assert state2["status"] == "completed"


# ---------------------------------------------------------------------------
# Codex promotion — module-level unit test
# ---------------------------------------------------------------------------

def test_codex_promoter_unit():
    from app.codex.promotion import CodexPromoter
    from app.models.schemas import ModelSource
    import uuid
    from datetime import datetime, timezone

    promoter = CodexPromoter()
    _ensure_project("p3-unit-test")
    now = datetime.now(timezone.utc).isoformat()

    task_id = f"p3-unit-task-{uuid.uuid4().hex[:8]}"
    client.post("/sql/query", json={
        "sql": "INSERT OR IGNORE INTO tasks (id, project_id, task_type, signature, task_status, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        "params": [task_id, "p3-unit-test", "generic", f"sig-{task_id}", "completed", now, now],
        "write_mode": True,
    })

    candidate_id = str(uuid.uuid4())
    client.post("/sql/query", json={
        "sql": "INSERT INTO codex_candidates (id, task_id, issue_signature, proposed_root_cause, proposed_resolution, human_verified, codex_promoted, created_at) VALUES (?,?,?,?,?,1,0,?)",
        "params": [candidate_id, task_id, f"sig-unit-{candidate_id[:8]}", "Root cause", "Fix it", now],
        "write_mode": True,
    })

    master_id, action = promoter.promote(candidate_id, promoted_by=ModelSource.HUMAN)
    assert len(master_id) == 36  # UUID
    assert action in ("created", "updated")

    # Promoting again should update, not duplicate
    # Create another candidate for the same issue_signature
    cid2 = str(uuid.uuid4())
    client.post("/sql/query", json={
        "sql": "INSERT INTO codex_candidates (id, task_id, issue_signature, proposed_root_cause, proposed_resolution, human_verified, codex_promoted, created_at) VALUES (?,?,?,?,?,1,0,?)",
        "params": [cid2, task_id, f"sig-unit-{candidate_id[:8]}", "Same issue", "Same fix", now],
        "write_mode": True,
    })
    master_id2, action2 = promoter.promote(cid2, promoted_by=ModelSource.HUMAN)
    assert master_id2 == master_id  # Same entry updated
    assert action2 == "updated"


# ---------------------------------------------------------------------------
# Context chunker — unit tests
# ---------------------------------------------------------------------------

def test_chunker_split_logic():
    from app.context.chunker import FileChunker
    chunker = FileChunker()
    content = "x" * 5000
    chunks = chunker._split(content, chunk_size=2000, overlap=200)
    assert len(chunks) >= 2
    # Each chunk <= chunk_size
    for c in chunks:
        assert len(c) <= 2000 + 50  # +50 tolerance for boundary search


def test_chunker_empty_content():
    from app.context.chunker import FileChunker
    chunker = FileChunker()
    chunks = chunker._split("", chunk_size=2000, overlap=200)
    assert chunks == []


# ---------------------------------------------------------------------------
# Context compressor — unit tests
# ---------------------------------------------------------------------------

def test_compressor_within_budget():
    from app.context.compressor import ContextCompressor
    compressor = ContextCompressor()
    messages = [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi"}]
    result = compressor.compress("task-compress-unit", messages, max_tokens=10000)
    assert result["messages"] == messages
    assert result["summary"] == ""


def test_compressor_over_budget():
    from app.context.compressor import ContextCompressor
    compressor = ContextCompressor()
    big = "word " * 1000  # ~5000 chars ~1250 tokens
    messages = [
        {"role": "system", "content": "Instructions"},
        {"role": "user", "content": big},
        {"role": "assistant", "content": big},
        {"role": "user", "content": big},
        {"role": "assistant", "content": big},
        {"role": "user", "content": big},
    ]
    result = compressor.compress("task-compress-big", messages, max_tokens=500)
    # System message always preserved
    assert any(m["role"] == "system" for m in result["messages"])
    assert result["compressed_tokens"] < result["original_messages"] * 1250
