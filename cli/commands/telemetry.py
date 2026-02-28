"""
CLI command group: mission-control telemetry
=============================================
telemetry runs        → GET /telemetry/runs
telemetry models      → GET /telemetry/models
telemetry performance → GET /telemetry/performance
telemetry hardware    → GET /telemetry/hardware
"""

from __future__ import annotations

from typing import Optional

import typer

app = typer.Typer(help="View telemetry: runs, model metrics, performance, hardware.")


@app.command("runs")
def telemetry_runs(
    ctx: typer.Context,
    limit: int = typer.Option(20, "--limit"),
    task_id: Optional[str] = typer.Option(None, "--task-id"),
    model_id: Optional[str] = typer.Option(None, "--model-id"),
) -> None:
    """List recent execution runs."""
    client = ctx.obj["client"]
    from cli.output import is_json_mode, print_json, print_table

    params: dict = {"limit": limit}
    if task_id:
        params["task_id"] = task_id
    if model_id:
        params["model_id"] = model_id

    result = client.get("/telemetry/runs", params=params)
    runs = result if isinstance(result, list) else result.get("runs", [])

    if is_json_mode():
        print_json(result)
        return
    rows = [
        [
            r.get("id", ""),
            r.get("task_id", ""),
            r.get("model_id", ""),
            r.get("score", ""),
            r.get("passed", ""),
            r.get("duration_ms", ""),
            r.get("created_at", ""),
        ]
        for r in runs
    ]
    print_table(
        "Execution Runs",
        ["Run ID", "Task ID", "Model", "Score", "Passed", "Duration (ms)", "Created At"],
        rows,
    )


@app.command("models")
def telemetry_models(ctx: typer.Context) -> None:
    """Show per-model telemetry aggregates."""
    client = ctx.obj["client"]
    from cli.output import is_json_mode, print_json, print_table

    result = client.get("/telemetry/models")
    entries = result if isinstance(result, list) else result.get("models", [])

    if is_json_mode():
        print_json(result)
        return
    if entries:
        columns = list(entries[0].keys())
        rows = [[str(e.get(c, "")) for c in columns] for e in entries]
        print_table("Model Telemetry", columns, rows)
    else:
        from cli.output import print_success
        print_success("No model telemetry recorded yet.")


@app.command("performance")
def telemetry_performance(ctx: typer.Context) -> None:
    """Show aggregate performance metrics."""
    client = ctx.obj["client"]
    from cli.output import is_json_mode, print_dict, print_json

    result = client.get("/telemetry/performance")
    if is_json_mode():
        print_json(result)
        return
    print_dict("Performance Metrics", result if isinstance(result, dict) else {"data": str(result)})


@app.command("hardware")
def telemetry_hardware(ctx: typer.Context) -> None:
    """Show hardware telemetry snapshots."""
    client = ctx.obj["client"]
    from cli.output import is_json_mode, print_dict, print_json

    result = client.get("/telemetry/hardware")
    if is_json_mode():
        print_json(result)
        return
    print_dict("Hardware Telemetry", result if isinstance(result, dict) else {"data": str(result)})
