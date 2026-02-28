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
        for deployment in config.get("deployments", []):
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
            # Filter out deployments with missing api_key
            params = deployment.get("litellm_params", {})
            if params.get("api_key") is None and "anthropic" in params.get("model", ""):
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

        # Capability escalation on repeated retry
        capability = force_class or self._maybe_escalate_class(base_class, retry_count)

        # Filter to hardware-available (cloud planner always available)
        if capability not in self._available_classes:
            capability = self._best_available(capability)

        # Context tier
        tier = force_tier or self._tier_for_class(capability)
        context_size = CONTEXT_TIER_SIZES[tier]

        reason = self._build_reason(task_type, base_class, capability, retry_count, force_class, force_tier)

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
    ) -> str:
        if force_class:
            return f"forced to {force_class.value}"
        if force_tier:
            return f"context tier forced to {force_tier.value}"
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
    """Return the initialised router singleton."""
    global _router_instance
    if _router_instance is None:
        _router_instance = AdaptiveRouter()
        _router_instance.initialise()
    return _router_instance
