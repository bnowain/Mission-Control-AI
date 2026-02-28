"""
Tests for Mission Control CLI (Phase 6)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Uses typer.testing.CliRunner + unittest.mock to avoid needing a live backend.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from cli.main import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def mock_client_get(responses: dict):
    """Return a mock MCClient whose .get() returns the given response dict."""
    client = MagicMock()
    client.get.side_effect = lambda path, **kwargs: responses.get(path, {})
    return client


def mock_client_post(response: Any):
    client = MagicMock()
    client.post.return_value = response
    client.post_execute.return_value = response
    return client


def _make_context_obj(client=None, config=None):
    if client is None:
        client = MagicMock()
        client.base_url = "http://localhost:8860"
    return {"client": client, "config": config or MagicMock(), "debug": False}


# ---------------------------------------------------------------------------
# 1. Config loading
# ---------------------------------------------------------------------------

class TestConfigLoading:
    def test_defaults(self):
        from cli.config import load_config, DEFAULT_ENDPOINT
        cfg = load_config()
        assert cfg.api_endpoint == DEFAULT_ENDPOINT
        assert cfg.api_key is None

    def test_env_var_overrides(self, monkeypatch):
        monkeypatch.setenv("MISSION_CONTROL_ENDPOINT", "http://testhost:9999")
        monkeypatch.setenv("MISSION_CONTROL_API_KEY", "secret123")
        from cli.config import load_config
        cfg = load_config()
        assert cfg.api_endpoint == "http://testhost:9999"
        assert cfg.api_key == "secret123"

    def test_cli_flag_beats_env(self, monkeypatch):
        monkeypatch.setenv("MISSION_CONTROL_ENDPOINT", "http://env:8860")
        from cli.config import load_config
        cfg = load_config(endpoint="http://cli:7777")
        assert cfg.api_endpoint == "http://cli:7777"

    def test_config_file_loading(self, tmp_path, monkeypatch):
        cfg_dir = tmp_path / ".mission-control"
        cfg_dir.mkdir()
        cfg_file = cfg_dir / "config.json"
        cfg_file.write_text(
            json.dumps({"api_endpoint": "http://file:1234", "api_key": "filekey"}),
            encoding="utf-8",
        )
        monkeypatch.setattr("cli.config.CONFIG_FILE", cfg_file)
        from cli.config import load_config
        cfg = load_config()
        assert cfg.api_endpoint == "http://file:1234"
        assert cfg.api_key == "filekey"


# ---------------------------------------------------------------------------
# 2. API Client construction
# ---------------------------------------------------------------------------

class TestAPIClient:
    def test_base_url_stripped(self):
        from cli.config import CLIConfig
        from cli.api_client import MCClient
        cfg = CLIConfig(api_endpoint="http://localhost:8860/")
        client = MCClient(cfg)
        assert client.base_url == "http://localhost:8860"

    def test_api_key_in_headers(self):
        from cli.config import CLIConfig
        from cli.api_client import MCClient
        cfg = CLIConfig(api_endpoint="http://localhost:8860", api_key="my-key")
        client = MCClient(cfg)
        assert client._headers.get("X-API-Key") == "my-key"

    def test_no_api_key_no_header(self):
        from cli.config import CLIConfig
        from cli.api_client import MCClient
        cfg = CLIConfig(api_endpoint="http://localhost:8860")
        client = MCClient(cfg)
        assert "X-API-Key" not in client._headers


# ---------------------------------------------------------------------------
# 3. Output helpers
# ---------------------------------------------------------------------------

class TestOutputHelpers:
    def test_json_mode_flag(self, capsys):
        from cli.output import set_json_mode, is_json_mode
        set_json_mode(True)
        assert is_json_mode() is True
        set_json_mode(False)
        assert is_json_mode() is False

    def test_print_json(self, capsys):
        from cli import output
        output.set_json_mode(False)
        # Should not raise
        output.print_json({"key": "value"})

    def test_print_table_json_mode(self, capsys):
        from cli import output
        output.set_json_mode(True)
        output.print_table("Test", ["Col1", "Col2"], [["a", "b"]])
        # In json mode, output is a JSON array — no exception
        output.set_json_mode(False)

    def test_print_success(self, capsys):
        from cli import output
        output.set_json_mode(False)
        output.print_success("All good")
        # Should not raise


# ---------------------------------------------------------------------------
# 4. status command
# ---------------------------------------------------------------------------

class TestStatusCommand:
    def test_status_json(self):
        client = MagicMock()
        client.base_url = "http://localhost:8860"
        client.get.side_effect = lambda path, **kwargs: {
            "/api/health": {"status": "ok"},
            "/system/status": {"schema_version": 6, "active_task_count": 2, "db_path": "/db"},
            "/system/hardware": {"gpu_name": "RTX 4090", "vram_mb": 24000, "available_capability_classes": []},
        }[path]

        with patch("cli.config.load_config") as mock_cfg, \
             patch("cli.api_client.MCClient", return_value=client):
            result = runner.invoke(app, ["--json", "status"])
        assert result.exit_code == 0

    def test_status_rich(self):
        client = MagicMock()
        client.base_url = "http://localhost:8860"
        client.get.side_effect = lambda path, **kwargs: {
            "/api/health": {"status": "ok"},
            "/system/status": {"schema_version": 6, "active_task_count": 0, "db_path": "/db"},
            "/system/hardware": {"gpu_name": None, "vram_mb": 0, "available_capability_classes": []},
        }[path]

        with patch("cli.api_client.MCClient", return_value=client):
            result = runner.invoke(app, ["status"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# 5. task view
# ---------------------------------------------------------------------------

class TestTaskView:
    def test_task_view_json(self):
        task_data = {
            "id": "01J123456789",
            "project_id": "test-proj",
            "task_type": "bug_fix",
            "task_status": "pending",
            "signature": "abc123",
            "created_at": "2026-02-27T00:00:00Z",
            "updated_at": "2026-02-27T00:00:00Z",
        }
        client = MagicMock()
        client.get.return_value = task_data

        with patch("cli.api_client.MCClient", return_value=client):
            result = runner.invoke(app, ["--json", "task", "view", "01J123456789"])
        assert result.exit_code == 0

    def test_task_create_json(self):
        task_data = {
            "id": "01JNEW",
            "project_id": "my-proj",
            "task_type": "bug_fix",
            "task_status": "pending",
            "signature": "abc",
            "created_at": "2026-02-27T00:00:00Z",
            "updated_at": "2026-02-27T00:00:00Z",
        }
        client = MagicMock()
        client.post.return_value = task_data

        with patch("cli.api_client.MCClient", return_value=client):
            result = runner.invoke(
                app,
                ["--json", "task", "create", "--type", "bug_fix", "--project", "my-proj"],
            )
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# 6. artifacts list
# ---------------------------------------------------------------------------

class TestArtifactsList:
    def test_artifacts_list_json(self):
        artifacts_data = {
            "artifacts": [
                {
                    "id": "uuid-1",
                    "source_type": "pdf",
                    "processing_state": "PROCESSED",
                    "mime_type": "application/pdf",
                    "file_size_bytes": 1024,
                    "ingest_at": "2026-02-27T00:00:00",
                }
            ],
            "total": 1,
            "limit": 20,
            "offset": 0,
        }
        client = MagicMock()
        client.get.return_value = artifacts_data

        with patch("cli.api_client.MCClient", return_value=client):
            result = runner.invoke(app, ["--json", "artifacts", "list", "--limit", "5"])
        assert result.exit_code == 0

    def test_artifacts_list_rich(self):
        client = MagicMock()
        client.get.return_value = {"artifacts": [], "total": 0, "limit": 20, "offset": 0}

        with patch("cli.api_client.MCClient", return_value=client):
            result = runner.invoke(app, ["artifacts", "list"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# 7. workers stats
# ---------------------------------------------------------------------------

class TestWorkersStats:
    def test_workers_stats_json(self):
        client = MagicMock()
        client.get.return_value = {
            "queued": 5, "running": 1, "completed": 42, "failed": 2, "cancelled": 0
        }
        with patch("cli.api_client.MCClient", return_value=client):
            result = runner.invoke(app, ["--json", "workers", "stats"])
        assert result.exit_code == 0

    def test_workers_stats_rich(self):
        client = MagicMock()
        client.get.return_value = {"queued": 0, "running": 0, "completed": 10, "failed": 0, "cancelled": 0}
        with patch("cli.api_client.MCClient", return_value=client):
            result = runner.invoke(app, ["workers", "stats"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# 8. codex stats
# ---------------------------------------------------------------------------

class TestCodexStats:
    def test_codex_stats_json(self):
        client = MagicMock()
        client.get.return_value = {"total": 10, "promoted": 3, "candidates": 7}
        with patch("cli.api_client.MCClient", return_value=client):
            result = runner.invoke(app, ["--json", "codex", "stats"])
        assert result.exit_code == 0

    def test_codex_stats_rich(self):
        client = MagicMock()
        client.get.return_value = {"total": 10, "promoted": 3, "candidates": 7}
        with patch("cli.api_client.MCClient", return_value=client):
            result = runner.invoke(app, ["codex", "stats"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# 9. sql command
# ---------------------------------------------------------------------------

class TestSQLCommand:
    def test_sql_read_query_json(self):
        client = MagicMock()
        client.post.return_value = {
            "columns": ["count(*)"],
            "rows": [[42]],
            "rows_affected": 0,
        }
        with patch("cli.api_client.MCClient", return_value=client):
            result = runner.invoke(
                app,
                ["--json", "sql", "SELECT COUNT(*) FROM tasks"],
            )
        assert result.exit_code == 0
        client.post.assert_called_once()
        call_args = client.post.call_args
        assert call_args[0][0] == "/sql/query"

    def test_sql_no_query_exits(self):
        client = MagicMock()
        with patch("cli.api_client.MCClient", return_value=client):
            result = runner.invoke(app, ["sql"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# 10. backfill command
# ---------------------------------------------------------------------------

class TestBackfillCommand:
    def test_backfill_json(self):
        client = MagicMock()
        client.post.return_value = {
            "pipeline_name": "ocr",
            "eligible_count": 5,
            "jobs_enqueued": 5,
            "simulated": False,
            "artifacts": [],
        }
        with patch("cli.api_client.MCClient", return_value=client):
            result = runner.invoke(app, ["--json", "backfill", "ocr"])
        assert result.exit_code == 0

    def test_backfill_simulate(self):
        client = MagicMock()
        client.post.return_value = {
            "pipeline_name": "ocr",
            "eligible_count": 3,
            "jobs_enqueued": 0,
            "simulated": True,
            "artifacts": [],
        }
        with patch("cli.api_client.MCClient", return_value=client):
            result = runner.invoke(app, ["backfill", "ocr", "--simulate"])
        assert result.exit_code == 0
        body = client.post.call_args[1]["json"]
        assert body.get("simulate") is True


# ---------------------------------------------------------------------------
# 11. coder REPL — slash commands
# ---------------------------------------------------------------------------

class TestCoderREPL:
    def test_coder_quit(self):
        client = MagicMock()
        client.base_url = "http://localhost:8860"
        with patch("cli.api_client.MCClient", return_value=client):
            result = runner.invoke(app, ["coder"], input="/quit\n")
        assert result.exit_code == 0

    def test_coder_status_command(self):
        client = MagicMock()
        client.base_url = "http://localhost:8860"
        client.get.side_effect = lambda path, **kwargs: {
            "/api/health": {"status": "ok"},
            "/system/status": {"schema_version": 6, "active_task_count": 0},
        }.get(path, {})

        with patch("cli.api_client.MCClient", return_value=client):
            result = runner.invoke(app, ["coder"], input="/status\n/quit\n")
        assert result.exit_code == 0

    def test_coder_project_command(self):
        client = MagicMock()
        client.base_url = "http://localhost:8860"
        with patch("cli.api_client.MCClient", return_value=client):
            result = runner.invoke(app, ["coder"], input="/project my-project\n/quit\n")
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# 12. --version flag
# ---------------------------------------------------------------------------

class TestVersion:
    def test_version_flag(self):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output


# ---------------------------------------------------------------------------
# 13. --help shows all command groups
# ---------------------------------------------------------------------------

class TestHelp:
    def test_help_shows_commands(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for cmd in ("task", "status", "artifacts", "backfill", "workers", "events",
                    "router", "telemetry", "codex", "sql", "coder"):
            assert cmd in result.output
