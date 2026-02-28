"""
Mission Control — Grading Engine
==================================
Deterministic scoring of task execution results.
Pattern from: kb-execution-validation-telemetry.md → GradingEngine

Score range: 0–100
Base scores:  +40 compile, +30 tests, +15 lint, +15 runtime
Penalties:    -10/retry (capped at 30), -20 human, -25 downstream, -30 arch change

Weights are configurable per project via GradingWeights.
The default weights match the spec in 1-Buildout.txt.

Ground truth rule: scores derive from compiler/test/lint output only.
Never use LLM self-assessment as a grading input.
"""

from app.models.schemas import GradingResult, GradingWeights

# Default passing threshold — tasks below this are marked failed
DEFAULT_PASSING_THRESHOLD: float = 70.0

# Maximum retry penalty (prevents score going negative from retries alone)
MAX_RETRY_PENALTY: float = 30.0


class GradingEngine:
    """
    Stateless grading engine. Instantiate with weights, call grade() per execution.

    Example:
        engine = GradingEngine()
        result = engine.grade(
            compile_result=True,
            test_result=True,
            lint_result=False,
            runtime_result=True,
            retry_count=1,
        )
        # result.score == 80.0 (40+30+15 base, -10 retry, lint not earned)
        # result.passed == True (80 >= 70)
    """

    def __init__(
        self,
        weights: GradingWeights | None = None,
        passing_threshold: float = DEFAULT_PASSING_THRESHOLD,
    ) -> None:
        self.weights = weights or GradingWeights()
        self.passing_threshold = passing_threshold

    def grade(
        self,
        compile_result: bool,
        test_result: bool,
        lint_result: bool,
        runtime_result: bool,
        retry_count: int = 0,
        human_intervention: bool = False,
        downstream_impact: bool = False,
        architecture_change_required: bool = False,
    ) -> GradingResult:
        """
        Compute a deterministic score from validator outputs.

        Args:
            compile_result:              Did compilation succeed?
            test_result:                 Did all tests pass?
            lint_result:                 Did lint/typecheck pass?
            runtime_result:              Did runtime validation pass?
            retry_count:                 Number of retries consumed.
            human_intervention:          Did a human have to intervene?
            downstream_impact:           Did this break downstream tasks?
            architecture_change_required: Was an unplanned arch change needed?

        Returns:
            GradingResult with score, pass/fail, and per-component breakdown.
        """
        w = self.weights
        score: float = 0.0
        components: dict[str, float] = {}

        # --- Base scores ---
        if compile_result:
            components["compile"] = w.compile_success
            score += w.compile_success

        if test_result:
            components["tests"] = w.tests_pass
            score += w.tests_pass

        if lint_result:
            components["lint"] = w.lint_pass
            score += w.lint_pass

        if runtime_result:
            components["runtime"] = w.runtime_success
            score += w.runtime_success

        # --- Penalties ---
        retry_penalty = min(retry_count * w.retry_penalty, MAX_RETRY_PENALTY)
        if retry_penalty > 0:
            components["retry_penalty"] = -retry_penalty
            score -= retry_penalty

        if human_intervention:
            components["human_penalty"] = -w.human_intervention
            score -= w.human_intervention

        if downstream_impact:
            components["downstream_penalty"] = -w.downstream_breakage
            score -= w.downstream_breakage

        if architecture_change_required:
            components["architecture_penalty"] = -w.architecture_change
            score -= w.architecture_change

        # Clamp to [0, 100]
        score = max(0.0, min(100.0, score))

        return GradingResult(
            score=round(score, 2),
            passed=score >= self.passing_threshold,
            compile_success=compile_result,
            tests_passed=test_result,
            lint_passed=lint_result,
            runtime_success=runtime_result,
            retry_count=retry_count,
            human_flag=human_intervention,
            downstream_impact_flag=downstream_impact,
            grade_components=components,
        )

    def passing_threshold_for(self, task_type: str) -> float:
        """
        Allow per-task-type thresholds in future.
        Currently returns the global threshold.
        """
        return self.passing_threshold
