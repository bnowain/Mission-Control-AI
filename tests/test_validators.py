"""
Tests for real validators (Phase 4 / schema v9).

Covers:
  - Compile: valid/invalid .py files in workspace; code blocks in response text; docs skip
  - Tests: pytest pass/fail; no test files; no working_dir
  - Lint: ruff pass/fail; ruff missing; no working_dir
  - Runtime: always True (stub)
  - run_validators() convenience wrapper
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.grading.validators import ValidatorSuite, ValidationResult, run_validators


@pytest.fixture
def suite() -> ValidatorSuite:
    return ValidatorSuite()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_py(tmp_path: Path, filename: str, code: str) -> Path:
    """Write a Python file into tmp_path and return its path."""
    p = tmp_path / filename
    p.write_text(code, encoding="utf-8")
    return p


def write_test(tmp_path: Path, filename: str, code: str) -> Path:
    """Write a pytest test file into tmp_path."""
    return write_py(tmp_path, filename, code)


# ===========================================================================
# Compile validator
# ===========================================================================

class TestCompile:

    def test_compile_valid_python_workspace(self, suite, tmp_path):
        """Valid .py files in working_dir → compile_success=True."""
        write_py(tmp_path, "foo.py", "def hello():\n    return 42\n")
        details: dict = {}
        result = suite._compile("", "generic", str(tmp_path), details)
        assert result is True
        assert "compile" not in details

    def test_compile_syntax_error_workspace(self, suite, tmp_path):
        """Broken .py file → compile_success=False + error in details."""
        write_py(tmp_path, "bad.py", "def foo(\n    return 1\n")
        details: dict = {}
        result = suite._compile("", "generic", str(tmp_path), details)
        assert result is False
        assert "compile" in details
        assert len(details["compile"]) > 0

    def test_compile_no_py_files_workspace(self, suite, tmp_path):
        """Workspace with no .py files → compile_success=True (nothing to check)."""
        (tmp_path / "README.txt").write_text("hello", encoding="utf-8")
        details: dict = {}
        result = suite._compile("", "generic", str(tmp_path), details)
        assert result is True

    def test_compile_code_blocks_in_response(self, suite):
        """No working_dir: valid Python code block in response → pass."""
        response = "```python\ndef add(a, b):\n    return a + b\n```"
        details: dict = {}
        result = suite._compile(response, "generic", None, details)
        assert result is True

    def test_compile_invalid_code_block_in_response(self, suite):
        """No working_dir: broken Python code block → fail + details."""
        response = "```python\ndef foo(\n    return 1\n```"
        details: dict = {}
        result = suite._compile(response, "generic", None, details)
        assert result is False
        assert "compile" in details

    def test_compile_no_working_dir_no_code_block(self, suite):
        """No working_dir, no code blocks → nothing to check, pass."""
        details: dict = {}
        result = suite._compile("Just some prose text.", "generic", None, details)
        assert result is True

    def test_compile_docs_skipped(self, suite, tmp_path):
        """task_type='docs' always skips compile, even with broken files."""
        write_py(tmp_path, "bad.py", "def foo(\n    return 1\n")
        details: dict = {}
        result = suite._compile("", "docs", str(tmp_path), details)
        assert result is True
        assert "compile" not in details

    def test_compile_multiple_errors_truncated(self, suite, tmp_path):
        """Multiple syntax errors: details['compile'] must be ≤ 2000 chars."""
        for i in range(10):
            write_py(tmp_path, f"bad{i}.py", f"def foo{i}(\n    return 1\n")
        details: dict = {}
        suite._compile("", "generic", str(tmp_path), details)
        assert len(details.get("compile", "")) <= 2000


# ===========================================================================
# Test validator
# ===========================================================================

class TestTests:

    def test_tests_no_working_dir(self, suite):
        """No working_dir → always True."""
        details: dict = {}
        result = suite._tests("", "generic", None, details)
        assert result is True
        assert "tests" not in details

    def test_tests_no_test_files(self, suite, tmp_path):
        """working_dir with no test files → True (graceful, not penalized)."""
        write_py(tmp_path, "app.py", "x = 1\n")
        details: dict = {}
        result = suite._tests("", "generic", str(tmp_path), details)
        assert result is True

    def test_tests_pass_when_tests_exist(self, suite, tmp_path):
        """Passing pytest test files → True."""
        write_test(tmp_path, "test_hello.py", "def test_ok():\n    assert 1 + 1 == 2\n")
        details: dict = {}
        result = suite._tests("", "generic", str(tmp_path), details)
        assert result is True

    def test_tests_fail_captures_output(self, suite, tmp_path):
        """Failing test → False + output in details."""
        write_test(tmp_path, "test_fail.py", "def test_bad():\n    assert 1 == 2\n")
        details: dict = {}
        result = suite._tests("", "generic", str(tmp_path), details)
        assert result is False
        assert "tests" in details
        assert len(details["tests"]) > 0

    def test_tests_output_truncated(self, suite, tmp_path):
        """Test output is truncated to ≤ 2000 chars in details."""
        # Write a test that produces verbose output
        write_test(tmp_path, "test_verbose.py",
                   "def test_verbose():\n    assert 'a' * 5000 == 'b' * 5000\n")
        details: dict = {}
        suite._tests("", "generic", str(tmp_path), details)
        assert len(details.get("tests", "")) <= 2000


# ===========================================================================
# Lint validator
# ===========================================================================

class TestLint:

    def test_lint_no_working_dir(self, suite):
        """No working_dir → always True."""
        details: dict = {}
        result = suite._lint("", "generic", None, details)
        assert result is True

    def test_lint_ruff_missing(self, suite, tmp_path):
        """ruff not installed → True (graceful skip)."""
        write_py(tmp_path, "app.py", "x = 1\n")
        details: dict = {}
        with patch("subprocess.run", side_effect=FileNotFoundError("ruff not found")):
            result = suite._lint("", "generic", str(tmp_path), details)
        assert result is True
        assert "lint" not in details

    def test_lint_clean_code(self, suite, tmp_path):
        """Clean Python → lint passes."""
        write_py(tmp_path, "clean.py", "x = 1\n")
        details: dict = {}
        # Simulate ruff returning exit code 0
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        with patch("subprocess.run", return_value=mock_proc):
            result = suite._lint("", "generic", str(tmp_path), details)
        assert result is True
        assert "lint" not in details

    def test_lint_violations(self, suite, tmp_path):
        """ruff finds violations → False + output in details."""
        write_py(tmp_path, "bad.py", "import os\nx=1\n")
        details: dict = {}
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = "bad.py:1:1: F401 `os` imported but unused\n"
        mock_proc.stderr = ""
        with patch("subprocess.run", return_value=mock_proc):
            result = suite._lint("", "generic", str(tmp_path), details)
        assert result is False
        assert "lint" in details
        assert "F401" in details["lint"]

    def test_lint_timeout(self, suite, tmp_path):
        """Lint timeout → False + message in details."""
        import subprocess
        write_py(tmp_path, "app.py", "x = 1\n")
        details: dict = {}
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ruff", timeout=30)):
            result = suite._lint("", "generic", str(tmp_path), details)
        assert result is False
        assert "lint" in details
        assert "timed out" in details["lint"]


# ===========================================================================
# Runtime validator (stub)
# ===========================================================================

class TestRuntime:

    def test_runtime_stub_returns_true(self, suite):
        """Runtime always returns True (stub)."""
        details: dict = {}
        result = suite._runtime("", "generic", None, details)
        assert result is True

    def test_runtime_stub_note_in_details(self, suite):
        """Runtime stub records a note in details."""
        details: dict = {}
        suite._runtime("", "generic", "/some/dir", details)
        assert "runtime" in details
        assert "stub" in details["runtime"]


# ===========================================================================
# ValidatorSuite.run() integration
# ===========================================================================

class TestValidatorSuiteRun:

    def test_run_returns_validation_result(self, suite):
        result = suite.run("print('hello')", "generic")
        assert isinstance(result, ValidationResult)

    def test_run_details_dict_populated(self, suite):
        """runtime always adds a detail; run() should return it in the result."""
        result = suite.run("", "generic")
        assert isinstance(result.details, dict)
        assert "runtime" in result.details

    def test_run_all_pass_on_valid_code(self, suite, tmp_path):
        """Clean workspace → all four validators pass."""
        write_py(tmp_path, "app.py", "x = 1\n")
        # No test files → tests pass; lint mocked clean
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        with patch("subprocess.run", return_value=mock_proc):
            result = suite.run("", "generic", str(tmp_path))
        assert result.compile_success is True
        assert result.tests_passed is True
        assert result.lint_passed is True
        assert result.runtime_success is True


# ===========================================================================
# run_validators() convenience wrapper
# ===========================================================================

def test_run_validators_wrapper():
    """run_validators() delegates to the module-level singleton."""
    result = run_validators("print('hi')", "generic")
    assert isinstance(result, ValidationResult)
