"""
Replay System — Comprehensive Tests (Phase 10)

Tests:
  1.  test_replay_success              — Happy path: load, run, grade, compare
  2.  test_replay_not_found            — 404 for nonexistent run (API)
  3.  test_replay_uses_original_prompt — Stored prompt used, not generic
  4.  test_replay_prompt_fallback_registry  — original_prompt NULL → prompt_registry
  5.  test_replay_prompt_fallback_generic   — both NULL → generic fallback
  6.  test_replay_task_type_from_join   — task_type from JOIN, not "generic"
  7.  test_replay_logs_new_execution    — log_execution called with correct args
  8.  test_replay_stream_events         — SSE emits started/model_response/grading/done
  9.  test_replay_db_error              — DB failure → 500
  10. test_replay_model_error           — Model call failure → propagates

Mock targets:
  - app.core.replay.get_connection   (imported directly into replay module)
  - app.core.replay.get_router
  - app.core.replay.log_execution
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Minimal execution_log row returned by _load_log() (includes task_type from JOIN)
_BASE_LOG: dict = {
    "id":                    "01REPLAY0000000000000000A1",
    "task_id":               "01TASK00000000000000000001",
    "project_id":            "proj-replay-test",
    "model_id":              "ollama/qwen2.5:32b",
    "context_size":          16000,
    "context_tier":          "execution",
    "temperature":           0.1,
    "tokens_in":             500,
    "tokens_generated":      200,
    "tokens_per_second":     25.0,
    "retries":               0,
    "score":                 72.5,
    "passed":                1,
    "compile_success":       1,
    "tests_passed":          1,
    "lint_passed":           1,
    "runtime_success":       1,
    "human_intervention":    0,
    "downstream_impact":     0,
    "duration_ms":           4000,
    "routing_reason":        "perf",
    "stack_trace_hash":      None,
    "prompt_id":             None,
    "prompt_version":        None,
    "injected_chunk_hashes": None,
    "original_prompt":       "Fix the bug in utils.py",
    "rag_chunks_injected":   0,
    "rag_source_ids":        None,
    "validator_details":     None,
    "actual_model":          None,
    "created_at":            "2026-01-01T00:00:00+00:00",
    # From JOIN with tasks table:
    "task_type":             "bug_fix",
}


def _conn_factory(row_data: dict | None):
    """
    Return a no-arg callable that produces a fresh mock connection each call.
    The connection's execute().fetchone() returns row_data as a plain dict.
    (dict supports the mapping protocol so dict(row) works correctly.)
    """
    def factory():
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = row_data
        return conn
    return factory


def _make_model_response(text: str = "Fixed the bug."):
    """Return a mock LiteLLM-style completion response."""
    choice = MagicMock()
    choice.message.content = text
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage.prompt_tokens = 100
    resp.usage.completion_tokens = 50
    return resp


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------

def test_replay_success():
    """ReplayEngine.replay() returns a full ReplayResponse with correct fields."""
    from app.core.replay import ReplayEngine

    engine = ReplayEngine()
    mock_router = MagicMock()
    mock_router.complete.return_value = _make_model_response("Fixed the bug.")

    with (
        patch("app.core.replay.get_connection", side_effect=_conn_factory(_BASE_LOG)),
        patch("app.core.replay.get_router", return_value=mock_router),
        patch("app.core.replay.log_execution", return_value="01NEWLOG00000000000000001"),
    ):
        result = engine.replay(_BASE_LOG["id"])

    assert result.original_run_id == _BASE_LOG["id"]
    assert result.new_run_id == "01NEWLOG00000000000000001"
    assert result.model_id == _BASE_LOG["model_id"]
    assert result.context_size == _BASE_LOG["context_size"]
    assert result.original_score == 72.5
    assert isinstance(result.new_score, float)
    assert result.original_passed is True
    assert result.task_type == "bug_fix"
    assert result.response_text == "Fixed the bug."
    assert result.duration_ms is not None


# ---------------------------------------------------------------------------
# 2. Not found → ValueError → 404
# ---------------------------------------------------------------------------

def test_replay_not_found():
    """API returns 404 when run_id does not exist in execution_logs."""
    # _load_log returns None (fetchone returns None) → ValueError → 404
    with patch("app.core.replay.get_connection", side_effect=_conn_factory(None)):
        r = client.post("/runs/nonexistent-run-id-xyz/replay")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 3. Uses stored original_prompt (tier 1 priority)
# ---------------------------------------------------------------------------

def test_replay_uses_original_prompt():
    """_load_prompt returns original_prompt from the log row directly."""
    from app.core.replay import ReplayEngine

    engine = ReplayEngine()
    log_row = {**_BASE_LOG, "original_prompt": "Stored prompt text", "prompt_id": None}

    # _load_prompt doesn't call the DB when original_prompt is set
    prompt = engine._load_prompt(log_row)
    assert prompt == "Stored prompt text"


# ---------------------------------------------------------------------------
# 4. Prompt fallback → prompt_registry (tier 2)
# ---------------------------------------------------------------------------

def test_replay_prompt_fallback_registry():
    """When original_prompt is NULL, _load_prompt fetches from prompt_registry."""
    from app.core.replay import ReplayEngine

    engine = ReplayEngine()

    log_row = {
        **_BASE_LOG,
        "original_prompt": None,
        "prompt_id": "prompt-abc-123",
        "prompt_version": "v1",
    }

    # fetchone returns a dict (supports dict protocol)
    registry_row = {"template_text": "Registry prompt text"}
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = registry_row

    with patch("app.core.replay.get_connection", return_value=conn):
        prompt = engine._load_prompt(log_row)

    assert prompt == "Registry prompt text"

    # Verify SQL targeted prompt_registry
    sql_called = conn.execute.call_args[0][0]
    assert "prompt_registry" in sql_called


# ---------------------------------------------------------------------------
# 5. Prompt fallback → generic (tier 3)
# ---------------------------------------------------------------------------

def test_replay_prompt_fallback_generic():
    """When original_prompt and prompt_id are both NULL, generic fallback is used."""
    from app.core.replay import ReplayEngine

    engine = ReplayEngine()
    log_row = {**_BASE_LOG, "original_prompt": None, "prompt_id": None}

    prompt = engine._load_prompt(log_row)

    assert "[Replay of execution" in prompt
    assert "Please produce the best possible output" in prompt


# ---------------------------------------------------------------------------
# 6. task_type from JOIN (not always "generic")
# ---------------------------------------------------------------------------

def test_replay_task_type_from_join():
    """_load_log() JOINs the tasks table so task_type is populated from tasks.task_type."""
    from app.core.replay import ReplayEngine

    engine = ReplayEngine()
    row_data = {**_BASE_LOG, "task_type": "refactor_small"}

    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = row_data

    with patch("app.core.replay.get_connection", return_value=conn):
        loaded = engine._load_log("some-run-id")

    assert loaded is not None
    assert loaded["task_type"] == "refactor_small"

    # Confirm the SQL uses JOIN and references the tasks table
    sql_called = conn.execute.call_args[0][0]
    assert "JOIN" in sql_called.upper()
    assert "tasks" in sql_called.lower()


# ---------------------------------------------------------------------------
# 7. log_execution called with correct args
# ---------------------------------------------------------------------------

def test_replay_logs_new_execution():
    """replay() calls log_execution with task_type and original_prompt populated."""
    from app.core.replay import ReplayEngine

    engine = ReplayEngine()
    mock_router = MagicMock()
    mock_router.complete.return_value = _make_model_response("output")

    log_row = {**_BASE_LOG, "original_prompt": "My stored prompt", "task_type": "bug_fix"}

    with (
        patch("app.core.replay.get_connection", side_effect=_conn_factory(log_row)),
        patch("app.core.replay.get_router", return_value=mock_router),
        patch("app.core.replay.log_execution", return_value="new-log-id") as mock_log,
    ):
        engine.replay(log_row["id"])

    mock_log.assert_called_once()
    kwargs = mock_log.call_args.kwargs
    assert kwargs.get("task_type") == "bug_fix"
    assert kwargs.get("original_prompt") == "My stored prompt"
    assert kwargs.get("task_id") == _BASE_LOG["task_id"]
    assert kwargs.get("project_id") == _BASE_LOG["project_id"]


# ---------------------------------------------------------------------------
# 8. SSE stream events — correct order and payloads
# ---------------------------------------------------------------------------

def test_replay_stream_events():
    """POST /runs/{id}/replay/stream emits: started → model_response → grading → done."""
    from app.core.replay import ReplayResponse

    fake_response = ReplayResponse(
        original_run_id="orig-id",
        new_run_id="new-id",
        model_id="ollama/qwen2.5:32b",
        context_size=16000,
        original_score=72.5,
        new_score=80.0,
        original_passed=True,
        new_passed=True,
        task_type="bug_fix",
        response_text="Fixed.",
        duration_ms=1234,
    )

    with patch("app.api.validate_api.replay_run", return_value=fake_response):
        with client.stream("POST", "/runs/orig-id/replay/stream") as response:
            assert response.status_code == 200
            events: list[tuple[str, dict]] = []
            current_event: str | None = None
            for line in response.iter_lines():
                if line.startswith("event:"):
                    current_event = line.split(":", 1)[1].strip()
                elif line.startswith("data:") and current_event:
                    data = json.loads(line.split(":", 1)[1].strip())
                    events.append((current_event, data))
                    current_event = None

    event_types = [e[0] for e in events]
    assert "started" in event_types
    assert "model_response" in event_types
    assert "grading" in event_types
    assert "done" in event_types

    # Validate ordering
    assert event_types.index("started") < event_types.index("model_response")
    assert event_types.index("model_response") < event_types.index("grading")
    assert event_types.index("grading") < event_types.index("done")

    # Validate done payload fields
    done_data = next(d for t, d in events if t == "done")
    assert done_data["original_run_id"] == "orig-id"
    assert done_data["new_run_id"] == "new-id"
    assert done_data["original_score"] == 72.5
    assert done_data["new_score"] == 80.0

    # Validate grading payload
    grading_data = next(d for t, d in events if t == "grading")
    assert grading_data["original_score"] == 72.5
    assert grading_data["new_score"] == 80.0


# ---------------------------------------------------------------------------
# 9. DB error → 500
# ---------------------------------------------------------------------------

def test_replay_db_error():
    """If the DB execute() raises, the API returns 500."""
    def _bad_conn():
        conn = MagicMock()
        conn.execute.side_effect = Exception("DB is locked")
        return conn

    with patch("app.core.replay.get_connection", side_effect=_bad_conn):
        r = client.post("/runs/some-run-id/replay")

    assert r.status_code == 500


# ---------------------------------------------------------------------------
# 10. Model call failure propagates
# ---------------------------------------------------------------------------

def test_replay_model_error():
    """If the model call raises, ReplayEngine.replay() re-raises (not silenced)."""
    from app.core.replay import ReplayEngine

    engine = ReplayEngine()
    mock_router = MagicMock()
    mock_router.complete.side_effect = RuntimeError("Model unavailable")

    with (
        patch("app.core.replay.get_connection", side_effect=_conn_factory(_BASE_LOG)),
        patch("app.core.replay.get_router", return_value=mock_router),
        patch("app.core.replay.log_execution", return_value="irrelevant"),
    ):
        with pytest.raises(RuntimeError, match="Model unavailable"):
            engine.replay(_BASE_LOG["id"])
