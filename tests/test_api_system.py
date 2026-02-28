"""
Phase 2 API smoke tests.

Uses FastAPI TestClient (sync) — no running server needed.
Verifies status codes and response shapes for every Phase 2 endpoint.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Health (Phase 1 — must still pass)
# ---------------------------------------------------------------------------

def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------

def test_system_status():
    r = client.get("/system/status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "schema_version" in body
    assert "active_task_count" in body
    assert "db_path" in body


def test_system_hardware():
    r = client.get("/system/hardware")
    assert r.status_code == 200
    body = r.json()
    assert "available_capability_classes" in body
    assert isinstance(body["available_capability_classes"], list)


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

def test_sql_select_one():
    r = client.post("/sql/query", json={"sql": "SELECT 1 AS n", "params": []})
    assert r.status_code == 200
    body = r.json()
    assert body["columns"] == ["n"]
    assert body["rows"] == [[1]]


def test_sql_blocked_drop():
    r = client.post("/sql/query", json={"sql": "DROP TABLE tasks", "params": [], "write_mode": False})
    assert r.status_code == 400


def test_sql_blocked_pragma():
    r = client.post("/sql/query", json={"sql": "PRAGMA journal_mode", "params": []})
    assert r.status_code == 400


def test_sql_blocked_alter():
    r = client.post("/sql/query", json={"sql": "ALTER TABLE tasks ADD COLUMN x TEXT", "params": []})
    assert r.status_code == 400


def test_sql_read_tasks_table():
    r = client.post("/sql/query", json={"sql": "SELECT COUNT(*) AS cnt FROM tasks", "params": []})
    assert r.status_code == 200
    body = r.json()
    assert body["columns"] == ["cnt"]
    assert isinstance(body["rows"][0][0], int)


# ---------------------------------------------------------------------------
# Codex (Atlas-exposed)
# ---------------------------------------------------------------------------

def test_codex_search_atlas_shape():
    r = client.get("/api/codex/search?q=test")
    assert r.status_code == 200
    body = r.json()
    assert "results" in body
    assert "total" in body
    assert "limit" in body
    assert "offset" in body


def test_codex_search_with_limit_offset():
    r = client.get("/api/codex/search?q=null+pointer&limit=5&offset=0")
    assert r.status_code == 200
    body = r.json()
    assert body["limit"] == 5
    assert body["offset"] == 0


def test_codex_query_post():
    r = client.post("/codex/query", json={"issue_text": "missing import", "limit": 3})
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_codex_stats():
    r = client.get("/codex/stats")
    assert r.status_code == 200
    body = r.json()
    assert "master_codex_count" in body
    assert "candidate_count" in body


def test_codex_promote_no_body():
    # Real endpoint — no body → 422 validation error
    r = client.post("/codex/promote")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Router (Atlas-exposed)
# ---------------------------------------------------------------------------

def test_router_stats_atlas():
    r = client.get("/api/router/stats")
    assert r.status_code == 200
    body = r.json()
    assert "rows" in body
    assert "total" in body


def test_router_stats_internal():
    r = client.get("/router/stats")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

def test_models_list():
    r = client.get("/models")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------

def test_telemetry_runs():
    r = client.get("/telemetry/runs")
    assert r.status_code == 200
    body = r.json()
    assert "runs" in body
    assert "total" in body


def test_telemetry_models():
    r = client.get("/telemetry/models")
    assert r.status_code == 200
    body = r.json()
    assert "models" in body


def test_telemetry_performance():
    r = client.get("/telemetry/performance")
    assert r.status_code == 200
    body = r.json()
    assert "total_runs" in body
    assert "total_tasks" in body


def test_telemetry_hardware():
    r = client.get("/telemetry/hardware")
    assert r.status_code == 200
    body = r.json()
    assert "profiles" in body


# ---------------------------------------------------------------------------
# Phase 3 endpoints — now real implementations (previously 501 stubs)
# ---------------------------------------------------------------------------

def test_plans_create_validates_schema():
    # Missing required fields → 422 (real validation, not stub)
    r = client.post("/plans", json={})
    assert r.status_code == 422


def test_plans_get_not_found():
    # Non-existent plan → 404 (real implementation)
    r = client.get("/plans/fake-id")
    assert r.status_code == 404


def test_plans_execute_not_found():
    r = client.post("/plans/fake-id/execute")
    assert r.status_code == 404


def test_plans_replan_validates_schema():
    r = client.post("/plans/fake-id/replan", json={})
    assert r.status_code in (404, 422)


def test_context_chunk_validates_schema():
    # Missing required fields → 422
    r = client.post("/context/chunk", json={})
    assert r.status_code == 422


def test_context_compress_validates_schema():
    r = client.post("/context/compress", json={})
    assert r.status_code == 422


def test_validate_endpoint_real():
    # Now a real endpoint — validates and returns grading
    r = client.post("/validate", json={"response_text": "x = 1", "task_type": "generic"})
    assert r.status_code == 200
    body = r.json()
    assert "compile_success" in body


def test_replay_not_found():
    # Real implementation — 404 for unknown run_id
    r = client.post("/runs/fake-id/replay")
    assert r.status_code == 404


def test_codex_promote_real_validates():
    # Real promote endpoint — validates request shape
    r = client.post("/codex/promote", json={})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Tasks (create + fetch + cancel)
# ---------------------------------------------------------------------------

def test_task_lifecycle():
    # Pre-insert a project so FK constraint is satisfied
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    client.post("/sql/query", json={
        "sql": "INSERT OR IGNORE INTO projects (id, name, created_at) VALUES (?, ?, ?)",
        "params": ["test-project-api", "Test Project (API tests)", now],
        "write_mode": True,
    })

    r = client.post("/tasks", json={
        "project_id": "test-project-api",
        "task_type": "generic",
        "relevant_files": [],
    })
    assert r.status_code == 201, r.text
    body = r.json()
    task_id = body["id"]
    assert body["task_status"] == "pending"
    assert len(body["signature"]) == 64  # SHA256 hex

    # Fetch it
    r2 = client.get(f"/tasks/{task_id}")
    assert r2.status_code == 200
    assert r2.json()["id"] == task_id

    # Cancel it
    r3 = client.post(f"/tasks/{task_id}/cancel")
    assert r3.status_code == 200
    assert r3.json()["task_status"] == "cancelled"

    # Cancel again → 409 (task already cancelled)
    r4 = client.post(f"/tasks/{task_id}/cancel")
    assert r4.status_code == 409


def test_task_not_found():
    r = client.get("/tasks/nonexistent-id")
    assert r.status_code == 404
