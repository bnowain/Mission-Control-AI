"""
Tests for app.router.report.generate_routing_report

Uses a real (temp) SQLite database with a minimal schema so that
datetime arithmetic in SQLite (e.g. datetime('now', '-30 days')) works
correctly — particularly for the window-filtering test.

Patch target:
  - "app.database.init.get_connection" → factory that opens the temp DB

All queries in generate_routing_report() are read-only so the temp DB
approach is safe and clean.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from unittest.mock import patch

import pytest

from app.router.report import generate_routing_report

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_MINIMAL_DDL = """
CREATE TABLE IF NOT EXISTS tasks (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL DEFAULT 'proj1',
    task_type   TEXT NOT NULL,
    signature   TEXT NOT NULL DEFAULT 'sig',
    task_status TEXT NOT NULL DEFAULT 'completed',
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS execution_logs (
    id           TEXT PRIMARY KEY,
    task_id      TEXT NOT NULL,
    project_id   TEXT NOT NULL DEFAULT 'proj1',
    model_id     TEXT NOT NULL,
    context_size INTEGER NOT NULL DEFAULT 16000,
    retries      INTEGER DEFAULT 0,
    score        REAL,
    passed       INTEGER,
    duration_ms  INTEGER,
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


@pytest.fixture()
def tmp_db():
    """Create a temp SQLite DB with minimal schema; yield its path; clean up."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.executescript(_MINIMAL_DDL)
    conn.commit()
    conn.close()
    yield path
    os.unlink(path)


def _conn_factory(path: str):
    """Return a no-arg callable that opens a Row-enabled connection to path."""
    def factory():
        c = sqlite3.connect(path, check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c
    return factory


def _insert_task(conn, task_id: str, task_type: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO tasks (id, task_type) VALUES (?, ?)",
        (task_id, task_type),
    )


def _insert_log(
    conn,
    log_id: str,
    task_id: str,
    model_id: str,
    passed: int,
    score: float = 70.0,
    duration_ms: int = 3000,
    retries: int = 0,
    created_at: str = "CURRENT_TIMESTAMP",
) -> None:
    if created_at == "CURRENT_TIMESTAMP":
        conn.execute(
            "INSERT INTO execution_logs "
            "(id, task_id, model_id, passed, score, duration_ms, retries) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (log_id, task_id, model_id, passed, score, duration_ms, retries),
        )
    else:
        conn.execute(
            "INSERT INTO execution_logs "
            "(id, task_id, model_id, passed, score, duration_ms, retries, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (log_id, task_id, model_id, passed, score, duration_ms, retries, created_at),
        )


# ---------------------------------------------------------------------------
# 1. Empty DB → valid zero-count structure
# ---------------------------------------------------------------------------

def test_report_empty_db(tmp_db):
    """Empty execution_logs → report has 0 executions and empty lists."""
    with patch("app.database.init.get_connection", side_effect=_conn_factory(tmp_db)):
        result = generate_routing_report(30)

    assert result["total_executions"] == 0
    assert result["window_days"] == 30
    assert "generated_at" in result
    assert result["per_model"] == []
    assert result["per_task_type"] == []
    assert result["summary"]["models_active"] == 0
    assert result["summary"]["task_types_seen"] == 0


# ---------------------------------------------------------------------------
# 2. Per-model summary aggregation
# ---------------------------------------------------------------------------

def test_report_per_model_summary(tmp_db):
    """
    Two models across two tasks — check that per_model entries
    contain correct execution counts and success rates.
    """
    conn = sqlite3.connect(tmp_db)
    _insert_task(conn, "t1", "bug_fix")
    _insert_task(conn, "t2", "bug_fix")
    # coder_model: 2 executions, 1 passed (50%)
    _insert_log(conn, "e1", "t1", "coder_model",    passed=1, score=80.0, duration_ms=2000)
    _insert_log(conn, "e2", "t2", "coder_model",    passed=0, score=40.0, duration_ms=4000)
    # reasoning_model: 1 execution, 1 passed (100%)
    _insert_log(conn, "e3", "t1", "reasoning_model", passed=1, score=95.0, duration_ms=6000)
    conn.commit()
    conn.close()

    with patch("app.database.init.get_connection", side_effect=_conn_factory(tmp_db)):
        result = generate_routing_report(30)

    assert result["total_executions"] == 3
    assert result["summary"]["models_active"] == 2

    by_model = {m["model_id"]: m for m in result["per_model"]}
    assert "coder_model" in by_model
    assert "reasoning_model" in by_model

    cm = by_model["coder_model"]
    assert cm["executions"] == 2
    assert abs(cm["success_rate"] - 0.5) < 0.01
    assert abs(cm["avg_score"] - 60.0) < 0.1

    rm = by_model["reasoning_model"]
    assert rm["executions"] == 1
    assert abs(rm["success_rate"] - 1.0) < 0.01


# ---------------------------------------------------------------------------
# 3. Per-task-type cross-model comparison
# ---------------------------------------------------------------------------

def test_report_cross_model_comparison(tmp_db):
    """
    bug_fix task with two models → per_task_type entry contains both models
    in models_compared.
    """
    conn = sqlite3.connect(tmp_db)
    _insert_task(conn, "t1", "bug_fix")
    for i in range(3):
        _insert_log(conn, f"e_c{i}", "t1", "coder_model",    passed=1, score=70.0)
    for i in range(3):
        _insert_log(conn, f"e_r{i}", "t1", "reasoning_model", passed=1, score=90.0)
    conn.commit()
    conn.close()

    with patch("app.database.init.get_connection", side_effect=_conn_factory(tmp_db)):
        result = generate_routing_report(30)

    assert len(result["per_task_type"]) == 1
    bug_fix_entry = result["per_task_type"][0]
    assert bug_fix_entry["task_type"] == "bug_fix"
    model_ids = {m["model_id"] for m in bug_fix_entry["models_compared"]}
    assert "coder_model" in model_ids
    assert "reasoning_model" in model_ids


# ---------------------------------------------------------------------------
# 4. Recommendation generated when improvement ≥ 15pp and n ≥ 10
# ---------------------------------------------------------------------------

def test_report_recommendation_generated(tmp_db):
    """
    reasoning_model beats coder_model by ≥ 15pp with ≥ 10 executions
    → recommendation appears in per_task_type and in recommendations list.
    """
    conn = sqlite3.connect(tmp_db)
    _insert_task(conn, "t1", "bug_fix")
    # coder_model: 10 executions, 50% success (5 passed)
    for i in range(10):
        _insert_log(conn, f"e_c{i}", "t1", "coder_model", passed=(1 if i < 5 else 0))
    # reasoning_model: 10 executions, 80% success (8 passed) → +30pp
    for i in range(10):
        _insert_log(conn, f"e_r{i}", "t1", "reasoning_model", passed=(1 if i < 8 else 0))
    conn.commit()
    conn.close()

    with patch("app.database.init.get_connection", side_effect=_conn_factory(tmp_db)):
        result = generate_routing_report(30)

    # Global recommendations list should mention the improvement
    assert len(result["recommendations"]) >= 1
    combined = " ".join(result["recommendations"])
    assert "reasoning_model" in combined

    # Per-task-type entry should also carry a recommendation
    bug_fix_entry = next(
        (t for t in result["per_task_type"] if t["task_type"] == "bug_fix"), None
    )
    assert bug_fix_entry is not None
    assert bug_fix_entry["recommendation"] is not None
    assert "reasoning_model" in bug_fix_entry["recommendation"]


# ---------------------------------------------------------------------------
# 5. No recommendation when total executions < _REC_MIN_SAMPLES
# ---------------------------------------------------------------------------

def test_report_no_recommendation_low_data(tmp_db):
    """
    Only 4 total executions for a task type → 'Insufficient data' note,
    not a routing recommendation in the global list.
    """
    conn = sqlite3.connect(tmp_db)
    _insert_task(conn, "t1", "bug_fix")
    for i in range(4):
        _insert_log(conn, f"e{i}", "t1", "coder_model", passed=1)
    conn.commit()
    conn.close()

    with patch("app.database.init.get_connection", side_effect=_conn_factory(tmp_db)):
        result = generate_routing_report(30)

    # No routing recommendations in global list
    assert result["recommendations"] == []

    # per_task_type entry should note insufficient data
    bug_fix_entry = next(
        (t for t in result["per_task_type"] if t["task_type"] == "bug_fix"), None
    )
    assert bug_fix_entry is not None
    rec = bug_fix_entry.get("recommendation") or ""
    assert "Insufficient" in rec or "insufficient" in rec


# ---------------------------------------------------------------------------
# 6. Window filtering — old data excluded
# ---------------------------------------------------------------------------

def test_report_window_filtering(tmp_db):
    """
    One recent execution and one 40-day-old execution.
    Only the recent one should appear in the 30-day window report.
    """
    conn = sqlite3.connect(tmp_db)
    _insert_task(conn, "t1", "bug_fix")
    # Recent row
    _insert_log(conn, "e_recent", "t1", "coder_model", passed=1, score=90.0)
    # Old row — well outside the 30-day window
    _insert_log(
        conn, "e_old", "t1", "coder_model",
        passed=0, score=10.0,
        created_at="2000-01-01 00:00:00",   # clearly outside any window
    )
    conn.commit()
    conn.close()

    with patch("app.database.init.get_connection", side_effect=_conn_factory(tmp_db)):
        result = generate_routing_report(30)

    # Only the recent row should be counted
    assert result["total_executions"] == 1
    assert len(result["per_model"]) == 1
    model_entry = result["per_model"][0]
    assert model_entry["executions"] == 1
    assert abs(model_entry["avg_score"] - 90.0) < 0.1
    assert abs(model_entry["success_rate"] - 1.0) < 0.01
