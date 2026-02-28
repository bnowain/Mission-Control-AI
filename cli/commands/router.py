"""
CLI command group: mission-control router
==========================================
router stats  → GET  /router/stats
router select → POST /router/select
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
