"""
Mission Control CLI — Config Loader
=====================================
Priority: CLI flags > env vars > config file > defaults.
Config file: ~/.mission-control/config.json
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

CONFIG_DIR = Path.home() / ".mission-control"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_ENDPOINT = "http://localhost:8860"


@dataclass
class CLIConfig:
    api_endpoint: str = DEFAULT_ENDPOINT
    api_key: Optional[str] = None
    default_project: Optional[str] = None
    default_model: Optional[str] = None


def load_config(
    endpoint: Optional[str] = None,
    api_key: Optional[str] = None,
    project: Optional[str] = None,
    model: Optional[str] = None,
) -> CLIConfig:
    """
    Load config with priority: CLI flags > env vars > config file > defaults.
    Call this once at the start of each command callback.
    """
    # Start with defaults
    cfg = CLIConfig()

    # Config file layer
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if "api_endpoint" in data:
                cfg.api_endpoint = data["api_endpoint"]
            if "api_key" in data:
                cfg.api_key = data["api_key"]
            if "default_project" in data:
                cfg.default_project = data["default_project"]
            if "default_model" in data:
                cfg.default_model = data["default_model"]
        except (json.JSONDecodeError, OSError):
            pass  # Silently ignore malformed config

    # Env var layer
    if env_key := os.environ.get("MISSION_CONTROL_API_KEY"):
        cfg.api_key = env_key
    if env_ep := os.environ.get("MISSION_CONTROL_ENDPOINT"):
        cfg.api_endpoint = env_ep

    # CLI flags layer (highest priority)
    if endpoint:
        cfg.api_endpoint = endpoint
    if api_key:
        cfg.api_key = api_key
    if project:
        cfg.default_project = project
    if model:
        cfg.default_model = model

    return cfg


def save_config(cfg: CLIConfig) -> None:
    """Persist config to ~/.mission-control/config.json."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "api_endpoint": cfg.api_endpoint,
        "api_key": cfg.api_key,
        "default_project": cfg.default_project,
        "default_model": cfg.default_model,
    }
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
