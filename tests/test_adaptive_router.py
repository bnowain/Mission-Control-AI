"""
Tests for the AdaptiveRouter — performance-informed model selection (v2).

Changes in v2 vs v1:
  - _ADAPTIVE_MIN_SAMPLES raised to 30 (statistical reliability)
  - _load_stats_for_task queries execution_logs with a 30-day window
    instead of the pre-aggregated routing_stats table
  - _adaptive_select uses success_rate only (no composite)
  - Cold-start guard: if default class has no data in window → no override
  - Epsilon-greedy: 5% of calls skip adaptive for exploration
  - is_feature_enabled → module-level _is_flag_enabled (with TTL cache)

Tests cover:
  - Feature flag gate (disabled → rule-based, enabled → adaptive)
  - Override when better class has sufficient samples and improvement > threshold
  - No override when improvement is below threshold
  - Minimum sample enforcement (HAVING clause filters low-count rows)
  - Cold-start guard: default class absent from stats → no override
  - Epsilon-greedy: random.random() < epsilon → rule-based regardless
  - Graceful degradation: empty stats, DB errors, unavailable hardware classes
  - Retry and force_class bypass paths
  - Reason string content
  - Flag TTL cache: second call within TTL uses cached value

Patch targets:
  - _is_flag_enabled  → "app.router.adaptive._is_flag_enabled"
    (module-level function in adaptive.py; patching directly avoids cache)
  - get_connection    → "app.database.init.get_connection"
    (imported lazily inside _load_stats_for_task)
  - random.random     → "random.random"
    (adaptive.py does 'import random' then calls random.random())
  - time.monotonic    → "app.router.adaptive.time.monotonic"
    (used inside _is_flag_enabled for TTL logic)

Only select() is tested — not complete().
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import app.router.adaptive as adaptive_mod
from app.models.schemas import CapabilityClass, ContextTier, TaskType
from app.router.adaptive import (
    AdaptiveRouter,
    _ADAPTIVE_IMPROVEMENT_THRESHOLD,
    _ADAPTIVE_MIN_SAMPLES,
)

# Patch paths
_FLAG_PATH   = "app.router.adaptive._is_flag_enabled"
_CONN_PATH   = "app.database.init.get_connection"
_RANDOM_PATH = "random.random"
_TIME_PATH   = "app.router.adaptive.time.monotonic"
_INNER_FLAG  = "app.core.feature_flags.is_feature_enabled"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_flag_cache():
    """Ensure the TTL flag cache is empty before and after each test."""
    adaptive_mod._flag_cache.clear()
    yield
    adaptive_mod._flag_cache.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_router(available: list[CapabilityClass] | None = None) -> AdaptiveRouter:
    """Return an AdaptiveRouter with hardware list set directly (no init needed)."""
    router = AdaptiveRouter.__new__(AdaptiveRouter)
    router._config = {}
    router._litellm_router = None
    router._available_classes = available if available is not None else list(CapabilityClass)
    return router


def _make_conn(rows: list[dict]) -> MagicMock:
    """
    Return a mock DB connection whose fetchall() yields plain dicts.
    _load_stats_for_task does [dict(r) for r in rows]; dict(dict) is a no-op copy.
    """
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = rows
    conn.close.return_value = None
    return conn


def _stat(model_id: str, success_rate: float, sample_size: int = 35) -> dict:
    """Minimal stat row as returned by the new execution_logs query."""
    return {
        "model_id":    model_id,
        "success_rate": success_rate,
        "sample_size":  sample_size,
    }


# ---------------------------------------------------------------------------
# 1. Feature flag disabled → pure rule-based routing
# ---------------------------------------------------------------------------

def test_flag_off_uses_default():
    router = _make_router()
    with patch(_FLAG_PATH, return_value=False):
        decision = router.select(TaskType.BUG_FIX, retry_count=0)
    # BUG_FIX maps to CODER_MODEL
    assert decision.selected_model == CapabilityClass.CODER_MODEL.value
    assert "adaptive" not in decision.routing_reason


# ---------------------------------------------------------------------------
# 2. Adaptive override when better class is available
# ---------------------------------------------------------------------------

def test_adaptive_override_when_better():
    """reasoning_model is 40pp higher than coder_model → override applies."""
    router = _make_router()
    rows = [
        _stat(CapabilityClass.CODER_MODEL.value,    success_rate=0.50),
        _stat(CapabilityClass.REASONING_MODEL.value, success_rate=0.90),
    ]
    conn = _make_conn(rows)

    with patch(_FLAG_PATH, return_value=True), \
         patch(_CONN_PATH, return_value=conn), \
         patch(_RANDOM_PATH, return_value=0.5):   # above epsilon — no exploration skip
        decision = router.select(TaskType.BUG_FIX, retry_count=0)

    assert decision.selected_model == CapabilityClass.REASONING_MODEL.value
    assert "adaptive" in decision.routing_reason
    assert "reasoning_model" in decision.routing_reason


# ---------------------------------------------------------------------------
# 3. Below threshold → no override
# ---------------------------------------------------------------------------

def test_below_threshold_no_override():
    """10pp improvement (< 15pp threshold) → keep default."""
    router = _make_router()
    rows = [
        _stat(CapabilityClass.CODER_MODEL.value,    success_rate=0.70),
        _stat(CapabilityClass.REASONING_MODEL.value, success_rate=0.80),
    ]
    conn = _make_conn(rows)

    with patch(_FLAG_PATH, return_value=True), \
         patch(_CONN_PATH, return_value=conn), \
         patch(_RANDOM_PATH, return_value=0.5):
        decision = router.select(TaskType.BUG_FIX, retry_count=0)

    assert decision.selected_model == CapabilityClass.CODER_MODEL.value
    assert "adaptive" not in decision.routing_reason


# ---------------------------------------------------------------------------
# 4. Minimum samples enforced — HAVING clause filters low-count rows → []
# ---------------------------------------------------------------------------

def test_minimum_samples_enforced():
    """SQL HAVING filters models with < 30 samples → fetchall returns [] → default."""
    router = _make_router()
    conn = _make_conn([])  # query returns nothing (all rows had too few samples)

    with patch(_FLAG_PATH, return_value=True), \
         patch(_CONN_PATH, return_value=conn), \
         patch(_RANDOM_PATH, return_value=0.5):
        decision = router.select(TaskType.BUG_FIX, retry_count=0)

    assert decision.selected_model == CapabilityClass.CODER_MODEL.value
    assert "adaptive" not in decision.routing_reason


# ---------------------------------------------------------------------------
# 5. No stats at all → default routing
# ---------------------------------------------------------------------------

def test_no_stats_uses_default():
    """Empty execution_logs for task type → rule-based selection."""
    router = _make_router()
    conn = _make_conn([])

    with patch(_FLAG_PATH, return_value=True), \
         patch(_CONN_PATH, return_value=conn), \
         patch(_RANDOM_PATH, return_value=0.5):
        decision = router.select(TaskType.GENERIC, retry_count=0)

    assert decision.selected_model == CapabilityClass.FAST_MODEL.value
    assert "adaptive" not in decision.routing_reason


# ---------------------------------------------------------------------------
# 6. retry_count >= 3 → escalation path, adaptive never called
# ---------------------------------------------------------------------------

def test_retry_escalation_bypasses_adaptive():
    """High retry_count triggers escalation — adaptive logic is not called."""
    router = _make_router()

    with patch(_FLAG_PATH) as mock_flag, \
         patch(_CONN_PATH) as mock_conn:
        decision = router.select(TaskType.BUG_FIX, retry_count=3)

    mock_flag.assert_not_called()
    mock_conn.assert_not_called()
    # Should have escalated beyond CODER_MODEL
    assert decision.selected_model != CapabilityClass.CODER_MODEL.value
    assert "escalated" in decision.routing_reason


# ---------------------------------------------------------------------------
# 7. force_class bypasses adaptive
# ---------------------------------------------------------------------------

def test_force_class_bypasses_adaptive():
    """force_class overrides everything; adaptive is not consulted."""
    router = _make_router()

    with patch(_FLAG_PATH) as mock_flag, \
         patch(_CONN_PATH) as mock_conn:
        decision = router.select(
            TaskType.BUG_FIX,
            retry_count=0,
            force_class=CapabilityClass.PLANNER_MODEL,
        )

    mock_flag.assert_not_called()
    mock_conn.assert_not_called()
    assert decision.selected_model == CapabilityClass.PLANNER_MODEL.value
    assert "forced" in decision.routing_reason


# ---------------------------------------------------------------------------
# 8. Hardware filtering — class not in _available_classes → skipped
# ---------------------------------------------------------------------------

def test_hardware_filtering():
    """Adaptive wants REASONING_MODEL but it's not in _available_classes → ignored."""
    router = _make_router(available=[
        CapabilityClass.CODER_MODEL,
        CapabilityClass.PLANNER_MODEL,
    ])
    rows = [
        _stat(CapabilityClass.CODER_MODEL.value,    success_rate=0.50),
        _stat(CapabilityClass.REASONING_MODEL.value, success_rate=0.99),
    ]
    conn = _make_conn(rows)

    with patch(_FLAG_PATH, return_value=True), \
         patch(_CONN_PATH, return_value=conn), \
         patch(_RANDOM_PATH, return_value=0.5):
        decision = router.select(TaskType.BUG_FIX, retry_count=0)

    # REASONING_MODEL unavailable → no override (PLANNER would need the threshold too)
    # But PLANNER_MODEL is available — check that coder_model stays
    # (reasoning was the best, but it's unavailable; planner may not appear in stats)
    assert decision.selected_model == CapabilityClass.CODER_MODEL.value
    assert "adaptive" not in decision.routing_reason


# ---------------------------------------------------------------------------
# 9. DB error → graceful fallback to default
# ---------------------------------------------------------------------------

def test_db_error_graceful_fallback():
    """Exception in _load_stats_for_task → silent fallback to rule-based routing."""
    router = _make_router()

    with patch(_FLAG_PATH, return_value=True), \
         patch(_CONN_PATH, side_effect=RuntimeError("simulated DB failure")), \
         patch(_RANDOM_PATH, return_value=0.5):
        decision = router.select(TaskType.BUG_FIX, retry_count=0)

    assert decision.selected_model == CapabilityClass.CODER_MODEL.value
    assert "adaptive" not in decision.routing_reason


# ---------------------------------------------------------------------------
# 10. Reason string contains "adaptive" when override applied
# ---------------------------------------------------------------------------

def test_routing_reason_shows_adaptive():
    router = _make_router()
    rows = [
        _stat(CapabilityClass.CODER_MODEL.value,   success_rate=0.40),
        _stat(CapabilityClass.PLANNER_MODEL.value, success_rate=0.95),
    ]
    conn = _make_conn(rows)

    with patch(_FLAG_PATH, return_value=True), \
         patch(_CONN_PATH, return_value=conn), \
         patch(_RANDOM_PATH, return_value=0.5):
        decision = router.select(TaskType.BUG_FIX, retry_count=0)

    reason = decision.routing_reason
    assert "adaptive" in reason
    assert CapabilityClass.PLANNER_MODEL.value in reason
    assert CapabilityClass.CODER_MODEL.value in reason


# ---------------------------------------------------------------------------
# 11. Cold-start guard: default class absent from stats → no override
# ---------------------------------------------------------------------------

def test_cold_start_guard_no_override():
    """
    Stats only exist for reasoning_model; coder_model (default) has no data
    in the current window → cold-start guard fires → no override.
    """
    router = _make_router()
    rows = [
        # coder_model absent from stats (e.g. hasn't run in the last 30 days)
        _stat(CapabilityClass.REASONING_MODEL.value, success_rate=0.95),
    ]
    conn = _make_conn(rows)

    with patch(_FLAG_PATH, return_value=True), \
         patch(_CONN_PATH, return_value=conn), \
         patch(_RANDOM_PATH, return_value=0.5):
        decision = router.select(TaskType.BUG_FIX, retry_count=0)

    assert decision.selected_model == CapabilityClass.CODER_MODEL.value
    assert "adaptive" not in decision.routing_reason


# ---------------------------------------------------------------------------
# 12. Same success_rate → no override
# ---------------------------------------------------------------------------

def test_same_score_no_override():
    """All classes have identical success rates → no override."""
    router = _make_router()
    rows = [
        _stat(CapabilityClass.CODER_MODEL.value,   success_rate=0.70),
        _stat(CapabilityClass.FAST_MODEL.value,    success_rate=0.70),
        _stat(CapabilityClass.PLANNER_MODEL.value, success_rate=0.70),
    ]
    conn = _make_conn(rows)

    with patch(_FLAG_PATH, return_value=True), \
         patch(_CONN_PATH, return_value=conn), \
         patch(_RANDOM_PATH, return_value=0.5):
        decision = router.select(TaskType.BUG_FIX, retry_count=0)

    assert decision.selected_model == CapabilityClass.CODER_MODEL.value
    assert "adaptive" not in decision.routing_reason


# ---------------------------------------------------------------------------
# 13. Epsilon-greedy: random.random() < epsilon → rule-based
# ---------------------------------------------------------------------------

def test_epsilon_skip():
    """
    random.random() returns 0.01 (< 0.05 epsilon) → _adaptive_select returns
    None immediately without loading stats → rule-based routing.
    """
    router = _make_router()
    rows = [
        _stat(CapabilityClass.CODER_MODEL.value,    success_rate=0.50),
        _stat(CapabilityClass.REASONING_MODEL.value, success_rate=0.90),
    ]
    conn = _make_conn(rows)

    with patch(_FLAG_PATH, return_value=True), \
         patch(_CONN_PATH, return_value=conn), \
         patch(_RANDOM_PATH, return_value=0.01):   # below epsilon threshold
        decision = router.select(TaskType.BUG_FIX, retry_count=0)

    # Epsilon triggered → rule-based → CODER_MODEL
    assert decision.selected_model == CapabilityClass.CODER_MODEL.value
    assert "adaptive" not in decision.routing_reason
    # get_connection should NOT have been called (epsilon short-circuits before DB)
    conn.execute.assert_not_called()


# ---------------------------------------------------------------------------
# 14. Flag TTL cache: second call within TTL skips DB
# ---------------------------------------------------------------------------

def test_flag_cache_ttl():
    """
    Second call to _is_flag_enabled within TTL uses cached value —
    is_feature_enabled is called only once despite two invocations.
    """
    adaptive_mod._flag_cache.clear()

    with patch(_INNER_FLAG, return_value=True) as mock_fe, \
         patch(_TIME_PATH, return_value=0.0):
        r1 = adaptive_mod._is_flag_enabled("adaptive_router_v2")
        r2 = adaptive_mod._is_flag_enabled("adaptive_router_v2")

    assert r1 is True
    assert r2 is True
    mock_fe.assert_called_once()  # second call hit the cache
