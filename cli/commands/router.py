"""
CLI command group: mission-control router
==========================================
router stats   → GET  /router/stats
router select  → POST /router/select
router report  → GET  /router/report
"""

from __future__ import annotations

import typer

app = typer.Typer(help="Router stats and model selection.")


@app.command("stats")
def router_stats(ctx: typer.Context) -> None:
    """Show model performance statistics from the router."""
    client = ctx.obj["client"]
    from cli.output import is_json_mode, print_json, print_table

    result = client.get("/router/stats")
    # result may be a list of model stats or a dict with a key
    entries = result if isinstance(result, list) else result.get("stats", [result])

    if is_json_mode():
        print_json(result)
        return

    if isinstance(entries, list) and entries:
        # Build rows from whatever keys are present in first entry
        first = entries[0]
        columns = list(first.keys())
        rows = [[str(e.get(c, "")) for c in columns] for e in entries]
        print_table("Router Stats", columns, rows)
    else:
        from cli.output import print_dict
        print_dict("Router Stats", result if isinstance(result, dict) else {})


@app.command("report")
def router_report(
    ctx: typer.Context,
    window_days: int = typer.Option(30, "--window-days", "-w", help="Days of history to include"),
) -> None:
    """Routing performance report: per-model and per-task-type success rates + recommendations."""
    client = ctx.obj["client"]
    from cli.output import is_json_mode, print_json, print_table, print_dict
    from rich.console import Console
    from rich.panel import Panel

    result = client.get(f"/router/report?window_days={window_days}")

    if is_json_mode():
        print_json(result)
        return

    console = Console()

    # ── Summary panel ──────────────────────────────────────────────────────
    summary = result.get("summary", {})
    adaptive_flag = "ENABLED" if result.get("adaptive_router_enabled") else "disabled"
    summary_lines = "\n".join([
        f"[bold]Window:[/bold] {result.get('window_days', window_days)} days  "
        f"[bold]Generated:[/bold] {result.get('generated_at', '')}",
        f"[bold]Total executions:[/bold] {result.get('total_executions', 0)}  "
        f"[bold]Adaptive router:[/bold] {adaptive_flag}",
        f"[bold]Overall success rate:[/bold] {round(summary.get('overall_success_rate', 0) * 100, 1)}%  "
        f"[bold]Avg score:[/bold] {summary.get('overall_avg_score', 0)}",
        f"[bold]Models active:[/bold] {summary.get('models_active', 0)}  "
        f"[bold]Task types:[/bold] {summary.get('task_types_seen', 0)}",
    ])
    console.print(Panel(summary_lines, title="Routing Performance Report", expand=False))

    # ── Per-model table ────────────────────────────────────────────────────
    per_model = result.get("per_model", [])
    if per_model:
        columns = ["Model", "Executions", "Success %", "Avg Score", "Avg ms", "Avg Retries"]
        rows = [
            [
                m["model_id"],
                str(m["executions"]),
                f"{round(m['success_rate'] * 100, 1)}%",
                str(m["avg_score"]),
                str(int(m["avg_duration_ms"])),
                str(m["avg_retries"]),
            ]
            for m in per_model
        ]
        print_table("Per-Model Performance", columns, rows)

    # ── Per-task-type table ────────────────────────────────────────────────
    per_task_type = result.get("per_task_type", [])
    if per_task_type:
        columns = ["Task Type", "Default Model", "Executions", "Models Compared", "Recommendation"]
        rows = [
            [
                t["task_type"],
                t["default_model"],
                str(t["executions"]),
                ", ".join(
                    f"{m['model_id']}:{round(m['success_rate']*100,1)}% (n={m['n']})"
                    for m in t["models_compared"]
                ),
                t.get("recommendation") or "—",
            ]
            for t in per_task_type
        ]
        print_table("Per-Task-Type Breakdown", columns, rows)

    # ── Recommendations ────────────────────────────────────────────────────
    recs = result.get("recommendations", [])
    if recs:
        rec_text = "\n".join(f"• {r}" for r in recs)
        console.print(Panel(rec_text, title="Recommendations", style="yellow", expand=False))
    else:
        console.print("[dim]No routing recommendations at this time.[/dim]")


@app.command("select")
def router_select(
    ctx: typer.Context,
    task_type: str = typer.Option(..., "--task-type", help="Task type to route"),
    context_tier: str = typer.Option("execution", "--context-tier"),
) -> None:
    """Ask the router which model to use for a given task type."""
    client = ctx.obj["client"]
    from cli.output import is_json_mode, print_dict, print_json

    body = {"task_type": task_type, "context_tier": context_tier}
    result = client.post("/router/select", json=body)
    if is_json_mode():
        print_json(result)
        return
    print_dict("Routing Decision", result)
