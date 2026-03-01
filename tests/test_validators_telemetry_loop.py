"""
Tests for schema v9, telemetry (validator_details + routing_stats),
and execution loop retry feedback injection.

All DB operations use temporary SQLite via tmp_path.
No live external services required.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fresh_db(tmp_path):
    """Initialise a fresh schema v9 database and return its path."""
    from app.database.init import init_db, run_migrations
    db_path = tmp_path / "test_v9.db"
    init_db(db_path)
    run_migrations(db_path)
    return db_path


@pytest.fixture()
def db_conn(fresh_db):
    """Open a connection to the fresh DB; close after test."""
    from app.database.init import get_connection
    conn = get_connection(fresh_db)
    yield conn
    conn.close()


def _make_decision():
    """Return a minimal RoutingDecision for testing."""
    from app.models.schemas import ContextTier, RoutingDecision
    return RoutingDecision(
        selected_model="fast_model",
        context_size=16384,
        context_tier=ContextTier.EXECUTION,
        temperature=0.1,
        routing_reason="test",
    )


def _make_grading(score: float = 100.0, passed: bool = True, retries: int = 0):
    """Return a GradingResult for testing."""
    from app.grading.engine import GradingEngine
    return GradingEngine().grade(
        compile_result=passed,
        test_result=passed,
        lint_result=passed,
        runtime_result=passed,
        retry_count=retries,
    )


def _insert_project_and_task(conn, project_id: str, task_id: str, task_type: str = "generic"):
    """Insert minimal project + task rows for FK satisfaction."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO projects (id, name, created_at) VALUES (?, ?, ?)",
        (project_id, "Test Project", now),
    )
    conn.execute(
        """INSERT OR IGNORE INTO tasks
           (id, project_id, task_type, signature, task_status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (task_id, project_id, task_type, "sig123", "running", now, now),
    )
    conn.commit()


# ===========================================================================
# 1. Schema v9
# ===========================================================================

class TestSchemaV9:

    def test_execution_logs_has_validator_details(self, db_conn):
        """execution_logs must have validator_details column after v9 migration."""
        cols = [r[1] for r in db_conn.execute("PRAGMA table_info(execution_logs)").fetchall()]
        assert "validator_details" in cols

    def test_execution_logs_has_actual_model(self, db_conn):
        """execution_logs must have actual_model column after v9 migration."""
        cols = [r[1] for r in db_conn.execute("PRAGMA table_info(execution_logs)").fetchall()]
        assert "actual_model" in cols

    def test_routing_stats_unique_index_exists(self, db_conn):
        """routing_stats must have unique index on (model_id, task_type)."""
        indexes = {
            r[1]
            for r in db_conn.execute(
                "SELECT * FROM sqlite_master WHERE type='index' AND tbl_name='routing_stats'"
            ).fetchall()
        }
        assert "idx_routing_stats_model_task" in indexes

    def test_schema_version_is_9(self, db_conn):
        """Schema version must be >= 9 after init + migrations."""
        row = db_conn.execute(
            "SELECT version FROM schema_version ORDER BY applied_at DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        assert row[0] >= 9


# ===========================================================================
# 2. Telemetry — validator_details stored
# ===========================================================================

class TestValidatorDetailsTelemetry:

    def test_validator_details_stored_in_execution_logs(self, fresh_db):
        """
        log_execution() with validator_details → JSON stored in execution_logs.
        """
        from app.telemetry.logger import TelemetryLogger
        from app.database.init import get_connection

        # Set up project + task
        conn = get_connection(fresh_db)
        _insert_project_and_task(conn, "proj-1", "task-1", "generic")
        conn.close()

        logger = TelemetryLogger()
        decision = _make_decision()
        grading = _make_grading()

        with patch("app.telemetry.logger.get_connection") as mock_conn_factory:
            real_conn = get_connection(fresh_db)
            mock_conn_factory.return_value = real_conn

            log_id = logger.log_execution(
                task_id="task-1",
                project_id="proj-1",
                decision=decision,
                grading=grading,
                validator_details={"compile": "SyntaxError at line 5", "runtime": "stub — not yet"},
                task_type="generic",
            )

        # Verify stored
        conn2 = get_connection(fresh_db)
        row = conn2.execute(
            "SELECT validator_details FROM execution_logs WHERE id = ?", (log_id,)
        ).fetchone()
        conn2.close()

        assert row is not None
        stored = json.loads(row[0])
        assert stored["compile"] == "SyntaxError at line 5"
        assert "runtime" in stored

    def test_validator_details_none_when_not_provided(self, fresh_db):
        """log_execution() without validator_details → NULL in column."""
        from app.telemetry.logger import TelemetryLogger
        from app.database.init import get_connection

        conn = get_connection(fresh_db)
        _insert_project_and_task(conn, "proj-2", "task-2", "generic")
        conn.close()

        logger = TelemetryLogger()
        decision = _make_decision()
        grading = _make_grading()

        with patch("app.telemetry.logger.get_connection") as mock_conn_factory:
            real_conn = get_connection(fresh_db)
            mock_conn_factory.return_value = real_conn

            log_id = logger.log_execution(
                task_id="task-2",
                project_id="proj-2",
                decision=decision,
                grading=grading,
                task_type="generic",
            )

        conn2 = get_connection(fresh_db)
        row = conn2.execute(
            "SELECT validator_details FROM execution_logs WHERE id = ?", (log_id,)
        ).fetchone()
        conn2.close()

        assert row is not None
        assert row[0] is None

    def test_actual_model_stored(self, fresh_db):
        """log_execution() with actual_model → stored in column."""
        from app.telemetry.logger import TelemetryLogger
        from app.database.init import get_connection

        conn = get_connection(fresh_db)
        _insert_project_and_task(conn, "proj-3", "task-3", "generic")
        conn.close()

        logger = TelemetryLogger()
        decision = _make_decision()
        grading = _make_grading()

        with patch("app.telemetry.logger.get_connection") as mock_conn_factory:
            real_conn = get_connection(fresh_db)
            mock_conn_factory.return_value = real_conn

            log_id = logger.log_execution(
                task_id="task-3",
                project_id="proj-3",
                decision=decision,
                grading=grading,
                actual_model="ollama/qwen2.5:32b",
                task_type="generic",
            )

        conn2 = get_connection(fresh_db)
        row = conn2.execute(
            "SELECT actual_model FROM execution_logs WHERE id = ?", (log_id,)
        ).fetchone()
        conn2.close()

        assert row is not None
        assert row[0] == "ollama/qwen2.5:32b"

    def test_validator_details_values_truncated(self, fresh_db):
        """Values longer than 2000 chars in validator_details are truncated."""
        from app.telemetry.logger import TelemetryLogger
        from app.database.init import get_connection

        conn = get_connection(fresh_db)
        _insert_project_and_task(conn, "proj-4", "task-4", "generic")
        conn.close()

        logger = TelemetryLogger()
        decision = _make_decision()
        grading = _make_grading()

        long_detail = "E" * 5000

        with patch("app.telemetry.logger.get_connection") as mock_conn_factory:
            real_conn = get_connection(fresh_db)
            mock_conn_factory.return_value = real_conn

            log_id = logger.log_execution(
                task_id="task-4",
                project_id="proj-4",
                decision=decision,
                grading=grading,
                validator_details={"compile": long_detail},
                task_type="generic",
            )

        conn2 = get_connection(fresh_db)
        row = conn2.execute(
            "SELECT validator_details FROM execution_logs WHERE id = ?", (log_id,)
        ).fetchone()
        conn2.close()

        stored = json.loads(row[0])
        assert len(stored["compile"]) <= 2000


# ===========================================================================
# 3. Telemetry — routing_stats populated
# ===========================================================================

class TestRoutingStatsPopulated:

    def test_routing_stats_row_created_after_log_execution(self, fresh_db):
        """
        After log_execution() with task_type, routing_stats gets a row
        for (model_id, task_type).
        """
        from app.telemetry.logger import TelemetryLogger
        from app.database.init import get_connection

        conn = get_connection(fresh_db)
        _insert_project_and_task(conn, "proj-5", "task-5", "bug_fix")
        conn.close()

        logger = TelemetryLogger()
        decision = _make_decision()
        grading = _make_grading(score=85.0, passed=True)

        with patch("app.telemetry.logger.get_connection") as mock_conn_factory:
            # Need two connections: one for log_execution, one for _update_routing_stats
            real_conn1 = get_connection(fresh_db)
            real_conn2 = get_connection(fresh_db)
            mock_conn_factory.side_effect = [real_conn1, real_conn2]

            logger.log_execution(
                task_id="task-5",
                project_id="proj-5",
                decision=decision,
                grading=grading,
                task_type="bug_fix",
            )

        conn2 = get_connection(fresh_db)
        row = conn2.execute(
            "SELECT * FROM routing_stats WHERE model_id = ? AND task_type = ?",
            ("fast_model", "bug_fix"),
        ).fetchone()
        conn2.close()

        assert row is not None

    def test_routing_stats_upsert_updates_existing(self, fresh_db):
        """
        Second log_execution() for same (model_id, task_type) updates
        the existing routing_stats row rather than creating a second one.
        """
        from app.telemetry.logger import TelemetryLogger
        from app.database.init import get_connection

        now = datetime.now(timezone.utc).isoformat()
        conn = get_connection(fresh_db)
        _insert_project_and_task(conn, "proj-6", "task-6a", "generic")
        _insert_project_and_task(conn, "proj-6", "task-6b", "generic")
        conn.close()

        logger = TelemetryLogger()
        decision = _make_decision()
        grading = _make_grading()

        # First execution
        with patch("app.telemetry.logger.get_connection") as mock_conn_factory:
            mock_conn_factory.side_effect = [
                get_connection(fresh_db),
                get_connection(fresh_db),
            ]
            logger.log_execution(
                task_id="task-6a",
                project_id="proj-6",
                decision=decision,
                grading=grading,
                task_type="generic",
            )

        # Second execution
        with patch("app.telemetry.logger.get_connection") as mock_conn_factory:
            mock_conn_factory.side_effect = [
                get_connection(fresh_db),
                get_connection(fresh_db),
            ]
            logger.log_execution(
                task_id="task-6b",
                project_id="proj-6",
                decision=decision,
                grading=grading,
                task_type="generic",
            )

        # Should be exactly one routing_stats row
        conn2 = get_connection(fresh_db)
        count = conn2.execute(
            "SELECT COUNT(*) FROM routing_stats WHERE model_id = ? AND task_type = ?",
            ("fast_model", "generic"),
        ).fetchone()[0]
        conn2.close()

        assert count == 1

    def test_routing_stats_not_updated_without_task_type(self, fresh_db):
        """
        log_execution() without task_type → no routing_stats row created.
        """
        from app.telemetry.logger import TelemetryLogger
        from app.database.init import get_connection

        conn = get_connection(fresh_db)
        _insert_project_and_task(conn, "proj-7", "task-7")
        conn.close()

        logger = TelemetryLogger()
        decision = _make_decision()
        grading = _make_grading()

        with patch("app.telemetry.logger.get_connection") as mock_conn_factory:
            real_conn = get_connection(fresh_db)
            mock_conn_factory.return_value = real_conn

            logger.log_execution(
                task_id="task-7",
                project_id="proj-7",
                decision=decision,
                grading=grading,
                # task_type NOT provided
            )

        conn2 = get_connection(fresh_db)
        count = conn2.execute("SELECT COUNT(*) FROM routing_stats").fetchone()[0]
        conn2.close()

        assert count == 0


# ===========================================================================
# 4. Execution loop — retry feedback injection
# ===========================================================================

class TestRetryFeedbackInjection:

    def _make_failed_validation(self, **details):
        """Build a ValidationResult with specified failures."""
        from app.grading.validators import ValidationResult
        return ValidationResult(
            compile_success=details.get("compile_success", True),
            tests_passed=details.get("tests_passed", True),
            lint_passed=details.get("lint_passed", True),
            runtime_success=details.get("runtime_success", True),
            details=details.get("details", {}),
        )

    def _make_failed_grading(self):
        from app.grading.engine import GradingEngine
        return GradingEngine().grade(
            compile_result=False,
            test_result=False,
            lint_result=False,
            runtime_result=True,
            retry_count=0,
        )

    def test_feedback_injected_on_compile_failure(self):
        """Failed compile check → user message appended to messages list."""
        from app.core.execution_loop import _inject_validation_feedback

        validation = self._make_failed_validation(
            compile_success=False,
            details={"compile": "SyntaxError at line 5: unexpected indent"},
        )
        grading = self._make_failed_grading()
        messages = [{"role": "user", "content": "Fix this"}]

        _inject_validation_feedback(messages, validation, grading)

        assert len(messages) == 2
        injected = messages[-1]
        assert injected["role"] == "user"
        assert "FAILED" in injected["content"]
        assert "compile" in injected["content"]
        assert "SyntaxError" in injected["content"]

    def test_feedback_injected_on_test_failure(self):
        """Failed tests → test output in injected message."""
        from app.core.execution_loop import _inject_validation_feedback

        validation = self._make_failed_validation(
            tests_passed=False,
            details={"tests": "FAILED test_foo.py::test_bar - AssertionError"},
        )
        grading = self._make_failed_grading()
        messages = [{"role": "user", "content": "Do the thing"}]

        _inject_validation_feedback(messages, validation, grading)

        assert len(messages) == 2
        assert "tests" in messages[-1]["content"]
        assert "FAILED" in messages[-1]["content"]

    def test_no_feedback_when_all_passed(self):
        """No failures → no message injected."""
        from app.core.execution_loop import _inject_validation_feedback

        validation = self._make_failed_validation(
            compile_success=True,
            tests_passed=True,
            lint_passed=True,
            runtime_success=True,
            details={"runtime": "stub — runtime validation not yet implemented"},
        )
        grading = self._make_failed_grading()
        messages = [{"role": "user", "content": "original"}]

        _inject_validation_feedback(messages, validation, grading)

        # Nothing injected — only the runtime stub is in details but runtime passed
        assert len(messages) == 1

    def test_no_feedback_when_details_empty(self):
        """Empty details dict → no message injected."""
        from app.core.execution_loop import _inject_validation_feedback
        from app.grading.validators import ValidationResult

        validation = ValidationResult(
            compile_success=False,
            tests_passed=False,
            details={},  # empty
        )
        grading = self._make_failed_grading()
        messages = [{"role": "user", "content": "original"}]

        _inject_validation_feedback(messages, validation, grading)

        assert len(messages) == 1

    def test_feedback_output_truncated_to_500_chars(self):
        """Detail output truncated to 500 chars in injected message."""
        from app.core.execution_loop import _inject_validation_feedback

        long_output = "X" * 2000
        validation = self._make_failed_validation(
            compile_success=False,
            details={"compile": long_output},
        )
        grading = self._make_failed_grading()
        messages = []

        _inject_validation_feedback(messages, validation, grading)

        assert len(messages) == 1
        content = messages[0]["content"]
        # Output: should not contain more than 500 "X" chars in the output line
        output_part = content[content.find("Output:"):] if "Output:" in content else ""
        assert len(output_part) <= 600  # some slack for the "Output: " prefix

    def test_feedback_message_contains_fix_instruction(self):
        """Injected message ends with fix instruction."""
        from app.core.execution_loop import _inject_validation_feedback

        validation = self._make_failed_validation(
            lint_passed=False,
            details={"lint": "E501 line too long"},
        )
        grading = self._make_failed_grading()
        messages = []

        _inject_validation_feedback(messages, validation, grading)

        assert len(messages) == 1
        assert "Fix these specific issues" in messages[0]["content"]
