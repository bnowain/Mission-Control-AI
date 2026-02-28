"""
CLI command: mission-control status
=====================================
GET /system/status + GET /system/hardware + GET /api/health
"""

from __future__ import annotations

import typer
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cli.api_client import MCClient

app = typer.Typer(help="Show system status, hardware info, and health.")


@app.callback(invoke_without_command=True)
def status_cmd(ctx: typer.Context) -> None:
    """Show system status, hardware profile, and health check."""
    client: MCClient = ctx.obj["client"]
    from cli.output import is_json_mode, print_dict, print_json

    health = client.get("/api/health")
    sys_status = client.get("/system/status")
    hardware = client.get("/system/hardware")

    if is_json_mode():
        print_json({"health": health, "system": sys_status, "hardware": hardware})
        return

    print_dict(
        "System Status",
        {
            "health": health.get("status", "unknown"),
            "schema_version": sys_status.get("schema_version"),
            "active_tasks": sys_status.get("active_task_count"),
            "db_path": sys_status.get("db_path"),
        },
    )
    print_dict(
        "Hardware",
        {
            "gpu": hardware.get("gpu_name") or "none detected",
            "vram_mb": hardware.get("vram_mb") or 0,
            "tokens_per_sec": hardware.get("benchmark_tokens_per_sec") or "n/a",
            "capability_classes": ", ".join(hardware.get("available_capability_classes") or []) or "none",
        },
    )
