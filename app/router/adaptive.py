"""
Mission Control — Adaptive Router
=====================================
Wraps LiteLLM Router with hardware-aware capability filtering,
context tier management, and escalation logic.

Pattern from: kb-llm-routing-providers.md → LiteLLM Router
Architecture: kb-orchestration-frameworks.md → capability categories

Rules:
  - Never hardcode model names — route by capability class only
  - fast_model    → small edits, bug fixes, file edits
  - reasoning_model → refactor_large, multi-file, complex analysis
  - planner_model → architecture_design, replan
  - Escalate capability class after retry threshold is hit
  - Escalate context tier when ContextWindowExceededError is raised
"""

from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path
from typing import Any, Optional

from app.core.exceptions import FatalError, ModelUnavailableError
from app.core.logging import get_logger
from app.models.schemas import (
    CAPABILITY_CLASSES,
    CONTEXT_TIER_SIZES,
    CapabilityClass,
    ContextTier,
    RoutingDecision,
    TaskType,
)
from app.router.hardware_profiler import available_capability_classes, detect_hardware

log = get_logger("router")

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "models.json"
EXAMPLE_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "models.example.json"

# Adaptive routing thresholds
_ADAPTIVE_MIN_SAMPLES = 30           # need 30+ for CLT-valid statistical reliability
_ADAPTIVE_IMPROVEMENT_THRESHOLD = 0.15  # 15 percentage points better to override
_ADAPTIVE_WINDOW_DAYS = 30           # only consider last 30 days of execution data
_ADAPTIVE_EPSILON = 0.05             # 5% chance to use rule-based for exploration

# ---------------------------------------------------------------------------
# Feature-flag TTL cache — avoids a DB hit on every select() call
# ---------------------------------------------------------------------------

_flag_cache: dict[str, tuple[bool, float]] = {}
_FLAG_CACHE_TTL = 60.0  # seconds


def _is_flag_enabled(flag_name: str) -> bool:
    """Return flag value with a 60-second TTL cache to avoid per-call DB hits."""
    now = time.monotonic()
    cached = _flag_cache.get(flag_name)
    if cached and now < cached[1]:
        return cached[0]
    from app.core.feature_flags import is_feature_enabled
    val = is_feature_enabled(flag_name)
    _flag_cache[flag_name] = (val, now + _FLAG_CACHE_TTL)
    return val

# Hard-coded routing rules: task_type → minimum capability class
# Code tasks route to CODER_MODEL; general tasks to FAST_MODEL.
_TASK_ROUTING: dict[TaskType, CapabilityClass] = {
    TaskType.BUG_FIX:             CapabilityClass.CODER_MODEL,
    TaskType.FILE_EDIT:           CapabilityClass.CODER_MODEL,
    TaskType.TEST_WRITE:          CapabilityClass.CODER_MODEL,
    TaskType.REFACTOR_SMALL:      CapabilityClass.CODER_MODEL,
    TaskType.DOCS:                CapabilityClass.FAST_MODEL,
    TaskType.GENERIC:             CapabilityClass.FAST_MODEL,
    TaskType.REFACTOR_LARGE:      CapabilityClass.REASONING_MODEL,
    TaskType.ARCHITECTURE_DESIGN: CapabilityClass.PLANNER_MODEL,
}

# Main escalation path: fast → reasoning → heavy (optional) → planner
_ESCALATION_PATH: list[CapabilityClass] = [
    CapabilityClass.FAST_MODEL,
    CapabilityClass.REASONING_MODEL,
    CapabilityClass.HEAVY_MODEL,
    CapabilityClass.PLANNER_MODEL,
]

# Coder escalation: coder → reasoning → heavy (optional) → planner
_CODER_ESCALATION_PATH: list[CapabilityClass] = [
    CapabilityClass.CODER_MODEL,
    CapabilityClass.REASONING_MODEL,
    CapabilityClass.HEAVY_MODEL,
    CapabilityClass.PLANNER_MODEL,
]


class AdaptiveRouter:
    """
    Hardware-aware model router backed by LiteLLM Router.

    Lifecycle:
        router = AdaptiveRouter()
        router.initialise()          # load config, build LiteLLM router
        decision = router.select(task_type, retry_count)
        response = router.complete(decision, messages)
    """

    def __init__(self, config_path: Path = CONFIG_PATH) -> None:
        self._config_path = config_path
        self._config: dict[str, Any] = {}
        self._litellm_router: Any = None          # litellm.Router
        self._available_classes: list[CapabilityClass] = []

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def initialise(self) -> None:
        """Load config, detect hardware, build LiteLLM Router."""
        self._config = self._load_config()
        hardware = detect_hardware()
        self._available_classes = available_capability_classes(hardware)

        log.info(
            "Hardware profile loaded",
            gpu=hardware.gpu_name,
            vram_mb=hardware.vram_mb,
            available_classes=[c.value for c in self._available_classes],
        )

        self._litellm_router = self._build_litellm_router()
        log.info("AdaptiveRouter initialised", deployments=len(self._config.get("deployments", [])))

    def _load_config(self) -> dict[str, Any]:
        if self._config_path.exists():
            with open(self._config_path, encoding="utf-8") as f:
                config = json.load(f)
        elif EXAMPLE_CONFIG_PATH.exists():
            log.warning(
                "models.json not found — using example config (local models only)",
                path=str(self._config_path),
            )
            with open(EXAMPLE_CONFIG_PATH, encoding="utf-8") as f:
                config = json.load(f)
        else:
            raise FatalError(
                f"No model config found at {self._config_path}. "
                f"Copy config/models.example.json to config/models.json and configure your models."
            )

        # Expand environment variable placeholders in litellm_params
        # Skip string entries — the example config uses strings as inline comments
        for deployment in config.get("deployments", []):
            if not isinstance(deployment, dict):
                continue
            params = deployment.get("litellm_params", {})
            for key, val in params.items():
                if isinstance(val, str) and val.startswith("${") and val.endswith("}"):
                    env_var = val[2:-1]
                    resolved = os.environ.get(env_var)
                    if resolved:
                        params[key] = resolved
                    else:
                        log.warning("Env var not set", var=env_var, deployment=deployment.get("model_name"))
                        params[key] = None

        return config

    def _build_litellm_router(self) -> Any:
        from litellm import Router

        model_list = []
        for deployment in self._config.get("deployments", []):
            # Skip string comment entries in deployments list
            if not isinstance(deployment, dict):
                continue
            # Skip explicitly disabled deployments
            if deployment.get("_disabled"):
                continue
            # Filter out cloud deployments with missing api_key.
            # Cloud models use "provider/model" format (e.g. "anthropic/claude-opus-4-6").
            # Local models use "ollama/..." or just a model name — never need api_key.
            params = deployment.get("litellm_params", {})
            api_key = params.get("api_key")
            model_name = params.get("model", "")
            # Detect cloud by prefix before the first slash
            provider_prefix = model_name.split("/")[0] if "/" in model_name else ""
            cloud_providers = {"anthropic", "openai", "deepseek"}
            if api_key is None and provider_prefix in cloud_providers:
                log.warning(
                    "Skipping deployment — API key not set",
                    model=deployment.get("model_name"),
                )
                continue
            model_list.append({
                "model_name":    deployment["model_name"],
                "litellm_params": params,
            })

        if not model_list:
            raise FatalError("No valid model deployments configured. Check config/models.json.")

        retry_cfg = self._config.get("retry", {})
        return Router(
            model_list=model_list,
            routing_strategy=self._config.get("routing_strategy", "latency-based-routing"),
            fallbacks=self._config.get("fallbacks", []),
            num_retries=retry_cfg.get("num_retries", 3),
            timeout=retry_cfg.get("timeout_seconds", 60),
        )

    # ------------------------------------------------------------------
    # Adaptive routing (data-driven overrides)
    # ------------------------------------------------------------------

    def _load_stats_for_task(self, task_type: TaskType) -> list[dict]:
        """
        Query execution_logs (JOIN tasks) for all models with enough samples in
        the last _ADAPTIVE_WINDOW_DAYS days for this task type.

        Uses the raw execution log rather than the pre-aggregated routing_stats
        table so that stale historical data is automatically excluded by the
        time window, and fresh data is always reflected immediately.

        Returns empty list on any error (graceful degradation).
        """
        from app.database.init import get_connection
        try:
            conn = get_connection()
            try:
                rows = conn.execute(
                    f"""
                    SELECT e.model_id,
                           AVG(CASE WHEN e.passed THEN 1.0 ELSE 0.0 END) AS success_rate,
                           COUNT(*) AS sample_size
                    FROM execution_logs e
                    JOIN tasks t ON e.task_id = t.id
                    WHERE t.task_type = ?
                      AND e.created_at >= datetime('now', '-{_ADAPTIVE_WINDOW_DAYS} days')
                    GROUP BY e.model_id
                    HAVING COUNT(*) >= ?
                    """,
                    (task_type.value, _ADAPTIVE_MIN_SAMPLES),
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()
        except Exception as exc:
            log.warning("Failed to load routing stats", exc=str(exc))
            return []

    def _adaptive_select(
        self, task_type: TaskType, base_class: CapabilityClass
    ) -> Optional[CapabilityClass]:
        """
        Check execution_logs to see if a different capability class outperforms
        the rule-based default by at least _ADAPTIVE_IMPROVEMENT_THRESHOLD.

        Uses epsilon-greedy exploration: _ADAPTIVE_EPSILON (5%) of calls skip
        adaptive logic and fall back to rule-based, ensuring losing models still
        get evaluated over time.

        Cold-start guard: if the default class has no data in the current window,
        do not override (insufficient baseline to measure against).

        Returns the better CapabilityClass, or None to keep the default.
        """
        # Epsilon-greedy: occasionally defer to rule-based for exploration
        if random.random() < _ADAPTIVE_EPSILON:
            return None

        stats = self._load_stats_for_task(task_type)
        if not stats:
            return None

        # Build model_id → success_rate mapping (single metric — avoids
        # double-counting correlated success_rate and average_score)
        model_rates: dict[str, float] = {
            row["model_id"]: float(row["success_rate"] or 0.0)
            for row in stats
        }

        # Cold-start guard: require baseline data for the default class
        if base_class.value not in model_rates:
            return None

        default_rate = model_rates[base_class.value]

        # Find best available alternative
        best_class: Optional[CapabilityClass] = None
        best_rate = default_rate
        for model_id, rate in model_rates.items():
            if model_id == base_class.value:
                continue
            try:
                candidate = CapabilityClass(model_id)
            except ValueError:
                continue
            if candidate not in self._available_classes:
                continue
            if rate > best_rate:
                best_class = candidate
                best_rate = rate

        # Only override if improvement clears the threshold
        if best_class is not None and (best_rate - default_rate) >= _ADAPTIVE_IMPROVEMENT_THRESHOLD:
            log.info(
                "Adaptive override",
                task_type=task_type.value,
                from_class=base_class.value,
                to_class=best_class.value,
                improvement=round(best_rate - default_rate, 3),
            )
            return best_class

        return None

    # ------------------------------------------------------------------
    # Routing decisions
    # ------------------------------------------------------------------

    def select(
        self,
        task_type: TaskType,
        retry_count: int = 0,
        force_tier: Optional[ContextTier] = None,
        force_class: Optional[CapabilityClass] = None,
    ) -> RoutingDecision:
        """
        Select model capability class and context tier for a task.

        Escalation rules:
          - retry_count >= 3 → escalate capability class by one tier
          - force_tier / force_class override (used after ContextEscalationRequired)
        """
        base_class = _TASK_ROUTING.get(task_type, CapabilityClass.FAST_MODEL)
        original_base = base_class  # saved for reason string

        # ── Adaptive override (data-driven) ─────────────────────────────────
        adaptive_override = False
        if force_class is None and retry_count < 3:
            if _is_flag_enabled("adaptive_router_v2"):
                override = self._adaptive_select(task_type, base_class)
                if override is not None:
                    base_class = override
                    adaptive_override = True

        # Capability escalation on repeated retry
        capability = force_class or self._maybe_escalate_class(base_class, retry_count)

        # Filter to hardware-available (cloud planner always available)
        if capability not in self._available_classes:
            capability = self._best_available(capability)

        # Context tier
        tier = force_tier or self._tier_for_class(capability)
        context_size = CONTEXT_TIER_SIZES[tier]

        reason = self._build_reason(
            task_type, original_base, capability, retry_count,
            force_class, force_tier, adaptive_override,
        )

        log.info(
            "Routing decision",
            task_type=task_type.value,
            capability=capability.value,
            tier=tier.value,
            context_size=context_size,
            retry_count=retry_count,
            reason=reason,
        )

        return RoutingDecision(
            selected_model=capability.value,
            context_size=context_size,
            context_tier=tier,
            temperature=self._temperature_for(task_type),
            routing_reason=reason,
        )

    def _maybe_escalate_class(
        self, base: CapabilityClass, retry_count: int
    ) -> CapabilityClass:
        """Escalate capability class after 3 retries.
        CODER uses its own escalation path; all others use the main path.
        HEAVY_MODEL is skipped if not available on this hardware.
        """
        if retry_count < 3:
            return base

        path = (
            _CODER_ESCALATION_PATH
            if base == CapabilityClass.CODER_MODEL
            else _ESCALATION_PATH
        )

        idx = path.index(base) if base in path else 0
        # Scan forward — skip HEAVY_MODEL if not available on this hardware
        for candidate in path[idx + 1:]:
            if candidate == CapabilityClass.HEAVY_MODEL and candidate not in self._available_classes:
                continue
            if candidate != base:
                log.info("Capability escalation", from_class=base.value, to_class=candidate.value, retries=retry_count)
            return candidate

        return base  # already at top of path

    def _best_available(self, desired: CapabilityClass) -> CapabilityClass:
        """Return the best available class at or above desired.
        Uses coder escalation path when desired is CODER_MODEL.
        HEAVY_MODEL is skipped gracefully if not configured.
        """
        path = (
            _CODER_ESCALATION_PATH
            if desired == CapabilityClass.CODER_MODEL
            else _ESCALATION_PATH
        )
        idx = path.index(desired) if desired in path else 0
        for cls in path[idx:]:
            if cls in self._available_classes:
                return cls
        # Always fall back to whatever is available (planner is always in list)
        return self._available_classes[-1]

    def _tier_for_class(self, cls: CapabilityClass) -> ContextTier:
        tiers = {
            CapabilityClass.FAST_MODEL:      ContextTier.EXECUTION,
            CapabilityClass.CODER_MODEL:     ContextTier.EXECUTION,
            CapabilityClass.REASONING_MODEL: ContextTier.HYBRID,
            CapabilityClass.HEAVY_MODEL:     ContextTier.PLANNING,
            CapabilityClass.PLANNER_MODEL:   ContextTier.PLANNING,
        }
        return tiers.get(cls, ContextTier.EXECUTION)

    def _temperature_for(self, task_type: TaskType) -> float:
        """Lower temperature for deterministic/code tasks."""
        low_temp = {
            TaskType.BUG_FIX,
            TaskType.FILE_EDIT,
            TaskType.TEST_WRITE,
            TaskType.REFACTOR_SMALL,
            TaskType.REFACTOR_LARGE,
        }
        return 0.1 if task_type in low_temp else 0.3

    def _build_reason(
        self,
        task_type: TaskType,
        base: CapabilityClass,
        selected: CapabilityClass,
        retries: int,
        force_class: Optional[CapabilityClass],
        force_tier: Optional[ContextTier],
        adaptive_override: bool = False,
    ) -> str:
        if force_class:
            return f"forced to {force_class.value}"
        if force_tier:
            return f"context tier forced to {force_tier.value}"
        if adaptive_override:
            return f"adaptive: {selected.value} outperforms {base.value} for {task_type.value}"
        if selected != base:
            return f"escalated from {base.value} after {retries} retries"
        return f"task_type={task_type.value} maps to {base.value}"

    # ------------------------------------------------------------------
    # Completion
    # ------------------------------------------------------------------

    def complete(
        self,
        decision: RoutingDecision,
        messages: list[dict],
        **kwargs: Any,
    ) -> Any:
        """
        Call the LiteLLM Router with the routing decision.
        Returns a standard OpenAI-compatible response object.
        Caller is responsible for retry/escalation via execute_with_retry.
        """
        if self._litellm_router is None:
            raise FatalError("Router not initialised. Call router.initialise() first.")

        return self._litellm_router.completion(
            model=decision.selected_model,
            messages=messages,
            temperature=decision.temperature,
            max_tokens=decision.context_size // 4,  # conservative output budget
            **kwargs,
        )

    async def acomplete(
        self,
        decision: RoutingDecision,
        messages: list[dict],
        **kwargs: Any,
    ) -> Any:
        """Async version of complete()."""
        if self._litellm_router is None:
            raise FatalError("Router not initialised.")

        return await self._litellm_router.acompletion(
            model=decision.selected_model,
            messages=messages,
            temperature=decision.temperature,
            max_tokens=decision.context_size // 4,
            **kwargs,
        )


# ---------------------------------------------------------------------------
# Module-level singleton — initialised once at app startup
# ---------------------------------------------------------------------------

_router_instance: Optional[AdaptiveRouter] = None


def get_router() -> AdaptiveRouter:
    """Return the initialised router singleton.

    Only assigns the singleton AFTER initialise() succeeds, so a failed
    initialisation doesn't leave a permanently broken instance.
    On the next call it will retry from scratch.
    """
    global _router_instance
    if _router_instance is None:
        instance = AdaptiveRouter()
        instance.initialise()       # raises on failure — _router_instance stays None
        _router_instance = instance  # only set after successful init
    return _router_instance
