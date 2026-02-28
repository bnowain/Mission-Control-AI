"""
Tests for GradingEngine.

Spec (1-Buildout.txt / kb-execution-validation-telemetry.md):
  Base scores:  +40 compile, +30 tests, +15 lint, +15 runtime
  Penalties:    -10/retry (capped at 30), -20 human, -25 downstream, -30 arch change
  Passing threshold: 70.0 (default)
"""

import pytest

from app.grading.engine import GradingEngine, DEFAULT_PASSING_THRESHOLD, MAX_RETRY_PENALTY
from app.models.schemas import GradingWeights


@pytest.fixture
def engine() -> GradingEngine:
    return GradingEngine()


# ---------------------------------------------------------------------------
# Perfect execution
# ---------------------------------------------------------------------------

def test_perfect_score(engine):
    result = engine.grade(
        compile_result=True,
        test_result=True,
        lint_result=True,
        runtime_result=True,
    )
    assert result.score == 100.0
    assert result.passed is True
    assert result.compile_success is True
    assert result.tests_passed is True
    assert result.lint_passed is True
    assert result.runtime_success is True
    assert result.retry_count == 0


# ---------------------------------------------------------------------------
# Single-component failures
# ---------------------------------------------------------------------------

def test_compile_fail_only(engine):
    result = engine.grade(
        compile_result=False,
        test_result=True,
        lint_result=True,
        runtime_result=True,
    )
    assert result.score == 60.0        # 100 - 40 compile
    assert result.passed is False       # 60 < 70


def test_tests_fail_only(engine):
    result = engine.grade(
        compile_result=True,
        test_result=False,
        lint_result=True,
        runtime_result=True,
    )
    assert result.score == 70.0        # 100 - 30 tests = 70 → exactly on threshold
    assert result.passed is True        # 70 >= 70


def test_lint_fail_only(engine):
    result = engine.grade(
        compile_result=True,
        test_result=True,
        lint_result=False,
        runtime_result=True,
    )
    assert result.score == 85.0        # 100 - 15 lint
    assert result.passed is True


def test_runtime_fail_only(engine):
    result = engine.grade(
        compile_result=True,
        test_result=True,
        lint_result=True,
        runtime_result=False,
    )
    assert result.score == 85.0        # 100 - 15 runtime
    assert result.passed is True


# ---------------------------------------------------------------------------
# Retry penalties
# ---------------------------------------------------------------------------

def test_single_retry_penalty(engine):
    result = engine.grade(
        compile_result=True,
        test_result=True,
        lint_result=True,
        runtime_result=True,
        retry_count=1,
    )
    assert result.score == 90.0        # 100 - 10 (1 retry)
    assert result.passed is True


def test_three_retry_penalty(engine):
    result = engine.grade(
        compile_result=True,
        test_result=True,
        lint_result=True,
        runtime_result=True,
        retry_count=3,
    )
    assert result.score == 70.0        # 100 - 30 (3 retries)
    assert result.passed is True


def test_retry_penalty_capped_at_30(engine):
    """4 retries at -10/retry = -40, but capped at 30."""
    result = engine.grade(
        compile_result=True,
        test_result=True,
        lint_result=True,
        runtime_result=True,
        retry_count=4,
    )
    assert result.score == 70.0        # 100 - 30 (cap)
    assert "retry_penalty" in result.grade_components
    assert result.grade_components["retry_penalty"] == -30.0


def test_retry_penalty_capped_large(engine):
    """100 retries should still only deduct 30."""
    result = engine.grade(
        compile_result=True,
        test_result=True,
        lint_result=True,
        runtime_result=True,
        retry_count=100,
    )
    assert result.score == 70.0


# ---------------------------------------------------------------------------
# Penalty combinations
# ---------------------------------------------------------------------------

def test_human_intervention_penalty(engine):
    result = engine.grade(
        compile_result=True,
        test_result=True,
        lint_result=True,
        runtime_result=True,
        human_intervention=True,
    )
    assert result.score == 80.0        # 100 - 20 human
    assert result.passed is True
    assert result.human_flag is True


def test_downstream_impact_penalty(engine):
    result = engine.grade(
        compile_result=True,
        test_result=True,
        lint_result=True,
        runtime_result=True,
        downstream_impact=True,
    )
    assert result.score == 75.0        # 100 - 25 downstream
    assert result.passed is True


def test_architecture_change_penalty(engine):
    result = engine.grade(
        compile_result=True,
        test_result=True,
        lint_result=True,
        runtime_result=True,
        architecture_change_required=True,
    )
    assert result.score == 70.0        # 100 - 30 arch
    assert result.passed is True


def test_all_penalties_applied(engine):
    """All penalties + all failures = score clamped at 0."""
    result = engine.grade(
        compile_result=False,
        test_result=False,
        lint_result=False,
        runtime_result=False,
        retry_count=10,
        human_intervention=True,
        downstream_impact=True,
        architecture_change_required=True,
    )
    assert result.score == 0.0
    assert result.passed is False


# ---------------------------------------------------------------------------
# Spec example from docstring
# ---------------------------------------------------------------------------

def test_spec_docstring_example(engine):
    """From GradingEngine docstring: compile+tests+runtime, no lint, 1 retry → 80."""
    result = engine.grade(
        compile_result=True,
        test_result=True,
        lint_result=False,
        runtime_result=True,
        retry_count=1,
    )
    # 40 + 30 + 15(runtime) = 85, -10 retry = 75 ... wait, spec says 80
    # spec: +40 compile, +30 tests, +15 runtime (lint not earned), -10 retry = 75
    # Actually the docstring says 80 — let me re-check:
    # compile=True: +40, test=True: +30, lint=False: 0, runtime=True: +15 = 85
    # minus -10 retry = 75.0
    # The docstring comment says 80 but that's an error in the docstring's comment
    # (it says "40+30+15 base" which is compile+tests+lint, not including runtime)
    # The correct value is 75.0 given our weights.
    assert result.score == 75.0
    assert result.passed is True


# ---------------------------------------------------------------------------
# Score clamping
# ---------------------------------------------------------------------------

def test_score_never_negative(engine):
    result = engine.grade(
        compile_result=False,
        test_result=False,
        lint_result=False,
        runtime_result=False,
        retry_count=100,
        human_intervention=True,
        downstream_impact=True,
        architecture_change_required=True,
    )
    assert result.score >= 0.0


def test_score_never_above_100():
    """Custom weights that sum above 100 should still clamp at 100."""
    big_weights = GradingWeights(
        compile_success=60.0,
        tests_pass=60.0,
        lint_pass=60.0,
        runtime_success=60.0,
    )
    engine = GradingEngine(weights=big_weights)
    result = engine.grade(
        compile_result=True,
        test_result=True,
        lint_result=True,
        runtime_result=True,
    )
    assert result.score == 100.0


# ---------------------------------------------------------------------------
# Custom weights and threshold
# ---------------------------------------------------------------------------

def test_custom_passing_threshold():
    engine = GradingEngine(passing_threshold=90.0)
    result = engine.grade(
        compile_result=True,
        test_result=True,
        lint_result=True,
        runtime_result=True,
        retry_count=1,
    )
    assert result.score == 90.0
    assert result.passed is True


def test_custom_passing_threshold_fail():
    engine = GradingEngine(passing_threshold=95.0)
    result = engine.grade(
        compile_result=True,
        test_result=True,
        lint_result=True,
        runtime_result=True,
        retry_count=1,
    )
    assert result.score == 90.0
    assert result.passed is False


def test_grade_components_audit_trail(engine):
    """grade_components must include all earned and penalised components."""
    result = engine.grade(
        compile_result=True,
        test_result=False,
        lint_result=True,
        runtime_result=False,
        retry_count=2,
        human_intervention=True,
    )
    assert "compile" in result.grade_components
    assert "lint" in result.grade_components
    assert "retry_penalty" in result.grade_components
    assert "human_penalty" in result.grade_components
    assert "tests" not in result.grade_components
    assert "runtime" not in result.grade_components
