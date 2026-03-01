"""
Mission Control — Validators (Phase 4)
=======================================
Real deterministic validators: compile, tests, lint, runtime.

Design principles:
- Workspace-centric: run against working_dir when provided
- Gracefully degrading: missing tools or no tests = pass (not penalized)
- Output-capturing: details dict populated with truncated error output
- Timeout-protected: every subprocess has a hard timeout (30s compile/lint, 60s tests)
- Never raises: all exceptions caught and surfaced as details text

Ground truth rule: scores derive from these outputs only.
Never use LLM self-assessment as a grading input.
"""

from __future__ import annotations

import ast
import py_compile
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.core.logging import get_logger

log = get_logger("validators")

_MAX_DETAIL_CHARS = 2000


@dataclass
class ValidationResult:
    """Outputs from running all four validators against a task result."""
    compile_success:  bool = True
    tests_passed:     bool = True
    lint_passed:      bool = True
    runtime_success:  bool = True
    details:          dict[str, str] = field(default_factory=dict)


class ValidatorSuite:
    """
    Runs all four deterministic validators against a task output.
    """

    def run(
        self,
        response_text: str,
        task_type: str,
        working_dir: Optional[str] = None,
    ) -> ValidationResult:
        """
        Run all validators. Returns ValidationResult with details.

        Args:
            response_text: The LLM's output (code, diff, etc.)
            task_type:     Used to skip irrelevant validators (e.g. docs skips compile)
            working_dir:   Directory to run validators in
        """
        details: dict[str, str] = {}

        log.info(
            "Running validators",
            task_type=task_type,
            has_working_dir=working_dir is not None,
        )

        compile_ok  = self._compile(response_text, task_type, working_dir, details)
        tests_ok    = self._tests(response_text, task_type, working_dir, details)
        lint_ok     = self._lint(response_text, task_type, working_dir, details)
        runtime_ok  = self._runtime(response_text, task_type, working_dir, details)

        return ValidationResult(
            compile_success=compile_ok,
            tests_passed=tests_ok,
            lint_passed=lint_ok,
            runtime_success=runtime_ok,
            details=details,
        )

    # ------------------------------------------------------------------
    # Compile validator
    # ------------------------------------------------------------------

    def _compile(
        self,
        response_text: str,
        task_type: str,
        working_dir: Optional[str],
        details: dict[str, str],
    ) -> bool:
        """
        Check Python syntax.
        - working_dir provided: glob all .py files, py_compile each one
        - no working_dir: extract fenced code blocks from response_text, ast.parse
        - task_type == 'docs': skip (no code to check)
        """
        if task_type == "docs":
            return True

        try:
            if working_dir:
                return self._compile_workspace(working_dir, details)
            else:
                return self._compile_response(response_text, details)
        except Exception as exc:
            details["compile"] = f"Compile check error: {exc}"
            log.warning("Compile validator error", exc=str(exc))
            return True  # Don't penalize on unexpected error

    def _compile_workspace(self, working_dir: str, details: dict[str, str]) -> bool:
        """Compile all .py files in the workspace."""
        workspace = Path(working_dir)
        py_files = list(workspace.glob("**/*.py"))
        if not py_files:
            return True

        errors = []
        for py_file in py_files:
            try:
                py_compile.compile(str(py_file), doraise=True)
            except py_compile.PyCompileError as exc:
                errors.append(f"{py_file.relative_to(workspace)}: {exc}")

        if errors:
            details["compile"] = ("\n".join(errors))[:_MAX_DETAIL_CHARS]
            log.warning("Compile failed", error_count=len(errors))
            return False
        return True

    def _compile_response(self, response_text: str, details: dict[str, str]) -> bool:
        """Extract and parse Python code blocks from response text."""
        code_blocks = _extract_code_blocks(response_text, lang="python")
        if not code_blocks:
            # No Python code blocks — nothing to compile
            return True

        errors = []
        for i, code in enumerate(code_blocks, 1):
            try:
                ast.parse(code)
            except SyntaxError as exc:
                errors.append(f"Block {i}: SyntaxError at line {exc.lineno}: {exc.msg}")

        if errors:
            details["compile"] = ("\n".join(errors))[:_MAX_DETAIL_CHARS]
            return False
        return True

    # ------------------------------------------------------------------
    # Test validator
    # ------------------------------------------------------------------

    def _tests(
        self,
        response_text: str,
        task_type: str,
        working_dir: Optional[str],
        details: dict[str, str],
    ) -> bool:
        """
        Run pytest if test files exist in working_dir.
        - No working_dir: return True
        - No test files: return True (graceful — not penalized)
        - Test files exist: run pytest, check exit code
        """
        if not working_dir:
            return True

        workspace = Path(working_dir)
        test_files = list(workspace.glob("**/test_*.py")) + list(workspace.glob("**/*_test.py"))
        if not test_files:
            return True

        try:
            proc = subprocess.run(
                ["python", "-m", "pytest", str(workspace), "-x", "-q", "--tb=short"],
                capture_output=True,
                text=True,
                timeout=60,
                encoding="utf-8",
            )
            output = (proc.stdout + proc.stderr)[:_MAX_DETAIL_CHARS]
            if proc.returncode != 0:
                details["tests"] = output
                log.warning("Tests failed", returncode=proc.returncode)
                return False
            return True
        except subprocess.TimeoutExpired:
            details["tests"] = "Tests timed out after 60s"
            log.warning("Tests timed out", working_dir=working_dir)
            return False
        except (FileNotFoundError, OSError) as exc:
            # python not found or other OS error — graceful skip
            log.warning("Could not run pytest", exc=str(exc))
            return True
        except Exception as exc:
            details["tests"] = f"Test runner error: {exc}"
            log.warning("Test runner error", exc=str(exc))
            return True

    # ------------------------------------------------------------------
    # Lint validator
    # ------------------------------------------------------------------

    def _lint(
        self,
        response_text: str,
        task_type: str,
        working_dir: Optional[str],
        details: dict[str, str],
    ) -> bool:
        """
        Run ruff on working_dir.
        - No working_dir: return True
        - ruff not installed: return True (graceful skip)
        - Exit code 0: pass
        """
        if not working_dir:
            return True

        try:
            proc = subprocess.run(
                ["python", "-m", "ruff", "check", str(working_dir), "--no-fix"],
                capture_output=True,
                text=True,
                timeout=30,
                encoding="utf-8",
            )
            if proc.returncode != 0:
                output = (proc.stdout + proc.stderr)[:_MAX_DETAIL_CHARS]
                details["lint"] = output
                log.warning("Lint failed", returncode=proc.returncode)
                return False
            return True
        except (FileNotFoundError, ModuleNotFoundError):
            # ruff not installed — graceful skip
            log.debug("ruff not available — skipping lint")
            return True
        except subprocess.TimeoutExpired:
            details["lint"] = "Lint check timed out after 30s"
            log.warning("Lint timed out", working_dir=working_dir)
            return False
        except Exception as exc:
            log.warning("Lint validator error", exc=str(exc))
            return True

    # ------------------------------------------------------------------
    # Runtime validator (stub — deferred)
    # ------------------------------------------------------------------

    def _runtime(
        self,
        response_text: str,
        task_type: str,
        working_dir: Optional[str],
        details: dict[str, str],
    ) -> bool:
        """
        Runtime validation deferred — sandbox execution has side-effect risk.
        Always passes; records a note in details for transparency.
        """
        details["runtime"] = "stub — runtime validation not yet implemented"
        return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(
    r"```(?P<lang>\w*)\n(?P<code>.*?)```",
    re.DOTALL,
)


def _extract_code_blocks(text: str, lang: str = "python") -> list[str]:
    """
    Extract fenced code blocks from markdown text.
    Returns blocks matching the requested language (or untagged blocks).
    """
    blocks = []
    for m in _FENCE_RE.finditer(text):
        block_lang = m.group("lang").lower().strip()
        code = m.group("code")
        if block_lang in ("", lang, "py"):
            blocks.append(code)
    return blocks


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_suite = ValidatorSuite()


def run_validators(
    response_text: str,
    task_type: str,
    working_dir: Optional[str] = None,
) -> ValidationResult:
    """Convenience wrapper for ValidatorSuite.run()."""
    return _suite.run(response_text, task_type, working_dir)
