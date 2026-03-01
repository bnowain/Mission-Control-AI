"""
Tests for Phase 8 — Platform Hardening
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
All DB operations use temporary in-memory SQLite (via tmp_path).
No live external services required.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def fresh_db(tmp_path):
    """Initialise a fresh schema v8 database and return its path."""
    from app.database.init import init_db, run_migrations
    db_path = tmp_path / "test_v8.db"
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


# ---------------------------------------------------------------------------
# 1. Schema v8
# ---------------------------------------------------------------------------

class TestSchemaV8:
    REQUIRED_TABLES = [
        "ocr_corrections",
        "speaker_resolution_overrides",
        "summary_corrections",
        "tag_overrides",
        "data_lineage",
        "schema_migrations",
    ]

    def test_all_phase8_tables_exist(self, db_conn):
        """Every Phase 8 table must be created by init_db + run_migrations."""
        names = {
            r[0]
            for r in db_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for table in self.REQUIRED_TABLES:
            assert table in names, f"Missing table: {table}"

    def test_artifacts_raw_has_archival_columns(self, db_conn):
        """artifacts_raw must have is_cold_storage and archived_at."""
        cols = [r[1] for r in db_conn.execute("PRAGMA table_info(artifacts_raw)").fetchall()]
        assert "is_cold_storage" in cols
        assert "archived_at" in cols

    def test_schema_version_is_8(self, db_conn):
        """Schema version must be >= 8 after init + migrations."""
        row = db_conn.execute(
            "SELECT version FROM schema_version ORDER BY applied_at DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        assert row[0] >= 8

    def test_ocr_corrections_columns(self, db_conn):
        """ocr_corrections has required columns."""
        cols = [r[1] for r in db_conn.execute("PRAGMA table_info(ocr_corrections)").fetchall()]
        for col in ("id", "artifact_id", "corrected_value", "corrected_by", "reason"):
            assert col in cols, f"Missing column: {col}"

    def test_data_lineage_columns(self, db_conn):
        """data_lineage has required columns."""
        cols = [r[1] for r in db_conn.execute("PRAGMA table_info(data_lineage)").fetchall()]
        for col in ("id", "artifact_id", "derived_from_artifact_id", "pipeline_stage"):
            assert col in cols


# ---------------------------------------------------------------------------
# 2. Audit Log Helper
# ---------------------------------------------------------------------------

class TestAuditLog:
    def test_write_audit_log_returns_id(self, fresh_db):
        """write_audit_log returns a ULID string."""
        from app.core.audit import write_audit_log
        with patch("app.core.audit.get_connection") as mock_conn_fn:
            mock_conn = MagicMock()
            mock_conn_fn.return_value = mock_conn
            record_id = write_audit_log("task.created", task_id="t1")
        assert isinstance(record_id, str)
        assert len(record_id) > 0

    def test_write_audit_log_survives_db_error(self):
        """write_audit_log never raises — swallows DB errors."""
        from app.core.audit import write_audit_log
        with patch("app.core.audit.get_connection", side_effect=Exception("db down")):
            result = write_audit_log("artifact.uploaded")
        assert isinstance(result, str)

    def test_get_audit_log_returns_rows(self, fresh_db):
        """get_audit_log queries and returns list + count."""
        from app.core.audit import get_audit_log, write_audit_log

        with patch("app.core.audit.get_connection") as mock_fn:
            mock_conn = MagicMock()
            # Simulate two audit entries
            mock_conn.execute.return_value.fetchone.return_value = [2]
            mock_conn.execute.return_value.fetchall.return_value = [
                {"id": "1", "action_type": "task.created", "task_id": "t1",
                 "artifact_id": None, "ip_address": None, "api_key_id": None,
                 "result": "success", "metadata_json": None, "timestamp": "2026-01-01"},
                {"id": "2", "action_type": "artifact.uploaded", "task_id": None,
                 "artifact_id": "a1", "ip_address": None, "api_key_id": None,
                 "result": "success", "metadata_json": None, "timestamp": "2026-01-02"},
            ]
            mock_fn.return_value = mock_conn
            rows, total = get_audit_log(limit=10)

        assert isinstance(rows, list)
        assert isinstance(total, int)

    def test_audit_action_constants_are_strings(self):
        """Verify all action constant strings are non-empty."""
        from app.core import audit
        constants = [
            audit.ACTION_ARTIFACT_UPLOADED,
            audit.ACTION_TASK_CREATED,
            audit.ACTION_SQL_QUERY,
            audit.ACTION_CODEX_PROMOTED,
            audit.ACTION_PROMPT_REGISTERED,
        ]
        for c in constants:
            assert isinstance(c, str) and len(c) > 0


# ---------------------------------------------------------------------------
# 3. Feature Flags
# ---------------------------------------------------------------------------

class TestFeatureFlags:
    def test_unknown_flag_returns_false(self):
        """A flag not in the DB returns False (fail closed)."""
        from app.core.feature_flags import is_feature_enabled
        with patch("app.core.feature_flags.get_connection") as mock_fn:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchone.return_value = None
            mock_fn.return_value = mock_conn
            assert is_feature_enabled("nonexistent_flag") is False

    def test_disabled_flag_returns_false(self):
        """A flag with enabled=0 returns False."""
        from app.core.feature_flags import is_feature_enabled
        with patch("app.core.feature_flags.get_connection") as mock_fn:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchone.return_value = {
                "enabled": 0, "rollout_percentage": 100, "project_scope": None
            }
            mock_fn.return_value = mock_conn
            assert is_feature_enabled("my_flag") is False

    def test_enabled_flag_returns_true(self):
        """A flag with enabled=1 and full rollout returns True."""
        from app.core.feature_flags import is_feature_enabled
        with patch("app.core.feature_flags.get_connection") as mock_fn:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchone.return_value = {
                "enabled": 1, "rollout_percentage": 100, "project_scope": None
            }
            mock_fn.return_value = mock_conn
            assert is_feature_enabled("my_flag") is True

    def test_project_scoped_flag_blocked_for_wrong_project(self):
        """Flag scoped to project A is False for project B."""
        from app.core.feature_flags import is_feature_enabled
        with patch("app.core.feature_flags.get_connection") as mock_fn:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchone.return_value = {
                "enabled": 1, "rollout_percentage": 100, "project_scope": "proj-A"
            }
            mock_fn.return_value = mock_conn
            assert is_feature_enabled("my_flag", project_id="proj-B") is False

    def test_db_error_returns_false(self):
        """DB error while checking flag → fail closed (False)."""
        from app.core.feature_flags import is_feature_enabled
        with patch("app.core.feature_flags.get_connection", side_effect=Exception("down")):
            assert is_feature_enabled("my_flag") is False

    def test_get_all_flags_returns_list(self, fresh_db):
        """get_all_flags returns a list (even if empty)."""
        from app.core.feature_flags import get_all_flags
        with patch("app.core.feature_flags.get_connection") as mock_fn:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchall.return_value = []
            mock_fn.return_value = mock_conn
            flags = get_all_flags()
        assert isinstance(flags, list)

    def test_set_flag_calls_db(self):
        """set_flag writes to the DB."""
        from app.core.feature_flags import set_flag
        with patch("app.core.feature_flags.get_connection") as mock_fn:
            mock_conn = MagicMock()
            mock_fn.return_value = mock_conn
            set_flag("test_flag", enabled=True, rollout_percentage=50)
            mock_conn.execute.assert_called_once()
            mock_conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# 4. Metrics Endpoint
# ---------------------------------------------------------------------------

class TestMetricsEndpoint:
    def _make_metrics_conn(self, counts: dict):
        """Build a mock connection that returns specific counts."""
        mock_conn = MagicMock()

        def fake_execute(sql, *args, **kwargs):
            result = MagicMock()
            sql_lower = sql.lower().strip()
            if "from tasks" in sql_lower:
                result.fetchone.return_value = [counts.get("tasks", 0)]
            elif "passed = 0" in sql_lower:
                result.fetchone.return_value = [counts.get("failures", 0)]
            elif "from processing_jobs" in sql_lower and "group by" not in sql_lower:
                if "queued" in sql_lower:
                    result.fetchone.return_value = [counts.get("queued", 0)]
                elif "running" in sql_lower:
                    result.fetchone.return_value = [counts.get("running", 0)]
                else:
                    result.fetchone.return_value = [counts.get("jobs", 0)]
            elif "from audit_log" in sql_lower:
                result.fetchone.return_value = [counts.get("audit", 0)]
            elif "from embeddings" in sql_lower:
                result.fetchone.return_value = [counts.get("embeddings", 0)]
            elif "from master_codex" in sql_lower:
                result.fetchone.return_value = [counts.get("codex", 0)]
            elif "group by pipeline_name" in sql_lower:
                result.fetchall.return_value = []
            else:
                result.fetchone.return_value = [0]
                result.fetchall.return_value = []
            return result

        mock_conn.execute.side_effect = fake_execute
        return mock_conn

    def test_metrics_returns_prometheus_text(self):
        """GET /metrics returns Prometheus text format lines."""
        from app.api.metrics import _collect_metrics
        with patch("app.api.metrics.get_connection") as mock_fn:
            mock_fn.return_value = self._make_metrics_conn({"tasks": 42, "failures": 3})
            lines = _collect_metrics()

        text = "\n".join(lines)
        assert "mc_task_count_total" in text
        assert "mc_task_failures_total" in text
        assert "mc_pipeline_jobs_queued" in text

    def test_metrics_includes_help_comments(self):
        """Prometheus format requires # HELP lines."""
        from app.api.metrics import _collect_metrics
        with patch("app.api.metrics.get_connection") as mock_fn:
            mock_fn.return_value = self._make_metrics_conn({})
            lines = _collect_metrics()

        help_lines = [l for l in lines if l.startswith("# HELP")]
        assert len(help_lines) >= 5

    def test_metrics_includes_type_comments(self):
        """Prometheus format requires # TYPE lines."""
        from app.api.metrics import _collect_metrics
        with patch("app.api.metrics.get_connection") as mock_fn:
            mock_fn.return_value = self._make_metrics_conn({})
            lines = _collect_metrics()

        type_lines = [l for l in lines if l.startswith("# TYPE")]
        assert len(type_lines) >= 5


# ---------------------------------------------------------------------------
# 5. Enhanced Health Endpoint
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_health_ok_when_db_up(self):
        """health_check returns status=ok when DB is reachable."""
        from app.api.health import health_check
        import asyncio

        with patch("app.api.health._check_db", return_value=True), \
             patch("app.api.health._check_workers", return_value="online"), \
             patch("app.api.health._check_gpu", return_value={"available": False}):
            result = asyncio.get_event_loop().run_until_complete(health_check())

        assert result.status == "ok"
        assert result.db_connectivity is True
        assert result.worker_status == "online"

    def test_health_degraded_when_db_down(self):
        """health_check returns status=degraded when DB is unreachable."""
        from app.api.health import health_check
        import asyncio

        with patch("app.api.health._check_db", return_value=False), \
             patch("app.api.health._check_workers", return_value="online"), \
             patch("app.api.health._check_gpu", return_value={"available": False}):
            result = asyncio.get_event_loop().run_until_complete(health_check())

        assert result.status == "degraded"
        assert result.db_connectivity is False

    def test_health_includes_gpu_status(self):
        """health_check response includes gpu_status dict."""
        from app.api.health import health_check
        import asyncio

        gpu = {"available": True, "vram_mb": 8192, "utilization_percent": 22.5}
        with patch("app.api.health._check_db", return_value=True), \
             patch("app.api.health._check_workers", return_value="online"), \
             patch("app.api.health._check_gpu", return_value=gpu):
            result = asyncio.get_event_loop().run_until_complete(health_check())

        assert result.gpu_status is not None
        assert result.gpu_status["available"] is True

    def test_check_db_returns_bool(self):
        """_check_db returns True or False (never raises)."""
        from app.api.health import _check_db
        # _check_db does a local import so patch at the source module
        with patch("app.database.init.get_connection") as mock_fn:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchone.return_value = (1,)
            mock_fn.return_value = mock_conn
            assert _check_db() is True

    def test_check_db_returns_false_on_error(self):
        """_check_db returns False when DB connection fails."""
        from app.api.health import _check_db
        with patch("app.database.init.get_connection", side_effect=Exception("no db")):
            assert _check_db() is False


# ---------------------------------------------------------------------------
# 6. Governance API — Prompt Registry
# ---------------------------------------------------------------------------

class TestPromptRegistry:
    def test_register_prompt_returns_id(self):
        """_register_prompt_db returns a dict with id and template_hash."""
        from app.api.governance import _register_prompt_db
        with patch("app.api.governance.get_connection") as mock_fn:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchone.return_value = None  # no duplicate
            mock_fn.return_value = mock_conn
            result = _register_prompt_db("test_prompt", "1.0", "You are a helpful assistant.")
        assert "id" in result
        assert "template_hash" in result
        assert len(result["template_hash"]) == 64  # SHA256 hex

    def test_register_duplicate_prompt_raises(self):
        """Registering same (name, version) twice raises ValueError."""
        from app.api.governance import _register_prompt_db
        with patch("app.api.governance.get_connection") as mock_fn:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchone.return_value = {"id": "existing"}
            mock_fn.return_value = mock_conn
            with pytest.raises(ValueError, match="already exists"):
                _register_prompt_db("test_prompt", "1.0", "template")

    def test_list_prompts_returns_list(self):
        """_list_prompts_db returns a list of dicts."""
        from app.api.governance import _list_prompts_db
        with patch("app.api.governance.get_connection") as mock_fn:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchall.return_value = []
            mock_fn.return_value = mock_conn
            result = _list_prompts_db()
        assert isinstance(result, list)

    def test_template_hash_is_deterministic(self):
        """Same template text always produces the same SHA256."""
        import hashlib
        text = "You are a coder."
        h1 = hashlib.sha256(text.encode("utf-8")).hexdigest()
        h2 = hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert h1 == h2


# ---------------------------------------------------------------------------
# 7. Governance API — Human Overrides
# ---------------------------------------------------------------------------

class TestHumanOverrides:
    def test_add_ocr_correction_returns_id(self):
        """_add_ocr_correction inserts a row and returns id."""
        from app.api.governance import _add_ocr_correction, OverrideCreate
        req = OverrideCreate(
            original_value="teh",
            corrected_value="the",
            corrected_by="alice@example.com",
            reason="typo",
        )
        with patch("app.api.governance.get_connection") as mock_fn:
            mock_conn = MagicMock()
            mock_fn.return_value = mock_conn
            result = _add_ocr_correction("artifact-uuid", req)
        assert "id" in result
        assert result["artifact_id"] == "artifact-uuid"
        mock_conn.execute.assert_called_once()
        mock_conn.commit.assert_called_once()

    def test_get_overrides_returns_list(self):
        """_get_overrides returns a list of dicts."""
        from app.api.governance import _get_overrides
        with patch("app.api.governance.get_connection") as mock_fn:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchall.return_value = []
            mock_fn.return_value = mock_conn
            rows = _get_overrides("ocr_corrections", "artifact-uuid")
        assert isinstance(rows, list)

    def test_add_tag_override_serialises_json(self):
        """_add_tag_override writes JSON arrays for tags."""
        from app.api.governance import _add_tag_override, TagOverrideCreate
        req = TagOverrideCreate(
            original_tags=["city", "meeting"],
            corrected_tags=["city", "meeting", "budget"],
            corrected_by="bob",
        )
        captured: list = []
        with patch("app.api.governance.get_connection") as mock_fn:
            mock_conn = MagicMock()
            def fake_execute(sql, params=None):
                if params:
                    captured.extend(params)
                return MagicMock()
            mock_conn.execute.side_effect = fake_execute
            mock_fn.return_value = mock_conn
            _add_tag_override("art-1", req)

        # Check that tags were serialised as JSON
        json_params = [p for p in captured if isinstance(p, str) and p.startswith("[")]
        assert len(json_params) >= 1
        parsed = json.loads(json_params[0])
        assert isinstance(parsed, list)


# ---------------------------------------------------------------------------
# 8. Data Lineage
# ---------------------------------------------------------------------------

class TestDataLineage:
    def test_record_lineage_returns_id(self):
        """_record_lineage_db inserts and returns id."""
        from app.api.governance import _record_lineage_db, LineageCreate
        req = LineageCreate(
            artifact_id="art-1",
            derived_from_artifact_id=None,
            pipeline_stage="ocr",
            model_version="surya-v1",
        )
        with patch("app.api.governance.get_connection") as mock_fn:
            mock_conn = MagicMock()
            mock_fn.return_value = mock_conn
            result = _record_lineage_db(req)
        assert "id" in result
        assert result["artifact_id"] == "art-1"

    def test_get_lineage_returns_list(self):
        """_get_lineage_db returns an ordered list."""
        from app.api.governance import _get_lineage_db
        with patch("app.api.governance.get_connection") as mock_fn:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchall.return_value = []
            mock_fn.return_value = mock_conn
            rows = _get_lineage_db("art-1")
        assert isinstance(rows, list)


# ---------------------------------------------------------------------------
# 9. Archive Endpoint
# ---------------------------------------------------------------------------

class TestArtifactArchive:
    def test_archive_sets_cold_storage_flag(self):
        """_archive_artifact sets is_cold_storage=1 and archived_at."""
        from app.api.artifacts import _archive_artifact

        # _archive_artifact does a local import of get_connection — patch at source
        with patch("app.database.init.get_connection") as mock_fn:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchone.return_value = {
                "id": "art-1", "processing_state": "PROCESSED"
            }
            mock_fn.return_value = mock_conn
            result = _archive_artifact("art-1")

        assert result["archived"] is True
        assert "archived_at" in result

    def test_archive_not_found_raises(self):
        """_archive_artifact raises ArtifactNotFoundError when artifact missing."""
        from app.api.artifacts import _archive_artifact
        from app.processing.registry import ArtifactNotFoundError

        with patch("app.database.init.get_connection") as mock_fn:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchone.return_value = None
            mock_fn.return_value = mock_conn
            with pytest.raises(ArtifactNotFoundError):
                _archive_artifact("nonexistent")


# ---------------------------------------------------------------------------
# 10. Schema Migration — v7 → v8
# ---------------------------------------------------------------------------

class TestMigrationV8:
    def test_migration_adds_phase8_tables(self, tmp_path):
        """run_migrations creates all Phase 8 tables on a v7 database."""
        from app.database.init import init_db, run_migrations, get_connection, SCHEMA_VERSION

        # Verify SCHEMA_VERSION is at least 8 (bumped to 9 in Phase 9)
        assert SCHEMA_VERSION >= 8

        db_path = tmp_path / "test_v8_mig.db"
        init_db(db_path)
        run_migrations(db_path)

        conn = get_connection(db_path)
        try:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        finally:
            conn.close()

        for table in (
            "ocr_corrections",
            "speaker_resolution_overrides",
            "summary_corrections",
            "tag_overrides",
            "data_lineage",
            "schema_migrations",
        ):
            assert table in tables, f"Phase 8 migration missing table: {table}"

    def test_migration_idempotent(self, tmp_path):
        """Running migrations twice does not raise."""
        from app.database.init import init_db, run_migrations
        db_path = tmp_path / "test_idempotent.db"
        init_db(db_path)
        run_migrations(db_path)
        run_migrations(db_path)  # second run must not raise
