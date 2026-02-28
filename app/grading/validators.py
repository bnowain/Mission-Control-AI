"""
Mission Control — Validation Stubs (Phase 1)
=============================================
Phase 1: all validators return True.
Phase 4: replace with real compile/test/lint/runtime checks.

The GradingEngine consumes these bool results — it does not care
whether they came from real validators or stubs. This means the
execution loop, grading, and telemetry are all fully exercised
in Phase 1 even though actual validation is deferred.

Ground truth rule: scores derive from these outputs only.
Never use LLM self-assessment as a grading input.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.core.logging import get_logger

log = get_logger("validators")


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

    Phase 1: stubs only — all return True.
    Phase 4: each validator will call real tools (compiler, pytest,
    ruff/mypy, runtime sandbox) and parse their output.
    """

    def run(
        self,
        response_text: str,
        task_type: str,
        working_dir: Optional[str] = None,
    ) -> ValidationResult:
        """
        Run all validators. Returns ValidationResult.

        Args:
            response_text: The LLM's output (code, diff, etc.)
            task_type:     Used to skip irrelevant validators (e.g. docs skips compile)
            working_dir:   Directory to run validators in (Phase 4)
        """
        log.info(
            "Running validators (Phase 1 stubs — all pass)",
            task_type=task_type,
        )

        compile_success = self._compile(response_text, task_type, working_dir)
        tests_passed    = self._tests(response_text, task_type, working_dir)
        lint_passed     = self._lint(response_text, task_type, working_dir)
        runtime_success = self._runtime(response_text, task_type, working_dir)

        return ValidationResult(
            compile_success=compile_success,
            tests_passed=tests_passed,
            lint_passed=lint_passed,
            runtime_success=runtime_success,
        )

    # ------------------------------------------------------------------
    # Phase 1 stubs — replace in Phase 4
    # ------------------------------------------------------------------

    def _compile(self, response_text: str, task_type: str, working_dir: Optional[str]) -> bool:
        """Phase 4: run compiler/parser, check exit code."""
        return True

    def _tests(self, response_text: str, task_type: str, working_dir: Optional[str]) -> bool:
        """Phase 4: run pytest/jest/cargo test, parse results."""
        return True

    def _lint(self, response_text: str, task_type: str, working_dir: Optional[str]) -> bool:
        """Phase 4: run ruff/mypy/eslint, check for errors."""
        return True

    def _runtime(self, response_text: str, task_type: str, working_dir: Optional[str]) -> bool:
        """Phase 4: run in sandbox, check for runtime exceptions."""
        return True


# Module-level singleton
_suite = ValidatorSuite()


def run_validators(
    response_text: str,
    task_type: str,
    working_dir: Optional[str] = None,
) -> ValidationResult:
    """Convenience wrapper for ValidatorSuite.run()."""
    return _suite.run(response_text, task_type, working_dir)
