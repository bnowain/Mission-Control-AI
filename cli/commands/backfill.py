"""
CLI command: mission-control backfill
=======================================
POST /backfill

Registered directly on the main app (not as a sub-typer) to avoid Click
Group + Argument parsing issues with invoke_without_command.
"""

from __future__ import annotations

import typer


def backfill_cmd(
    ctx: typer.Context,
    pipeline_name: str = typer.Argument(..., help="Pipeline name to backfill"),
    simulate: bool = typer.Option(False, "--simulate/--no-simulate", help="Dry-run — report what would be processed"),
) -> None:
    """Trigger a backfill run for a given pipeline."""
    client = ctx.obj["client"]
    from cli.output import is_json_mode, print_dict, print_json

    body: dict = {"pipeline_name": pipeline_name}
    if simulate:
        body["simulate"] = True

    result = client.post("/backfill", json=body)
    if is_json_mode():
        print_json(result)
        return
    print_dict(
        f"Backfill — {pipeline_name}",
        {
            "pipeline_name": result.get("pipeline_name"),
            "simulate": result.get("simulate", simulate),
            "eligible_count": result.get("eligible_count", "n/a"),
            "jobs_enqueued": result.get("jobs_enqueued", "n/a"),
            "message": result.get("message", ""),
        },
    )
