"""
CLI command group: mission-control task
========================================
task create  → POST /tasks
task view    → GET  /tasks/{id}
task run     → POST /tasks/{id}/execute
task cancel  → POST /tasks/{id}/cancel
task replay  → POST /runs/{id}/replay
"""

from __future__ import annotations

from typing import List, Optional

import typer

app = typer.Typer(help="Create, view, run, cancel, and replay tasks.")


@app.command("create")
def task_create(
    ctx: typer.Context,
    task_type: str = typer.Option(..., "--type", help="Task type (e.g. bug_fix, refactor_small)"),
    project: str = typer.Option(..., "--project", help="Project ID"),
    files: Optional[List[str]] = typer.Option(None, "--files", help="Relevant file paths"),
    constraints: Optional[str] = typer.Option(None, "--constraints", help="Free-text constraints"),
) -> None:
    """Create a new task. Returns ULID task ID and SHA256 signature."""
    client = ctx.obj["client"]
    from cli.output import is_json_mode, print_dict, print_json

    body: dict = {"project_id": project, "task_type": task_type}
    if files:
        body["relevant_files"] = files
    if constraints:
        body["constraints"] = constraints

    result = client.post("/tasks", json=body)
    if is_json_mode():
        print_json(result)
        return
    print_dict(
        "Task Created",
        {
            "id": result.get("id"),
            "project_id": result.get("project_id"),
            "task_type": result.get("task_type"),
            "task_status": result.get("task_status"),
            "signature": result.get("signature"),
            "created_at": result.get("created_at"),
        },
    )


@app.command("view")
def task_view(
    ctx: typer.Context,
    task_id: str = typer.Argument(..., help="Task ULID"),
) -> None:
    """Fetch a task by ID."""
    client = ctx.obj["client"]
    from cli.output import is_json_mode, print_dict, print_json

    result = client.get(f"/tasks/{task_id}")
    if is_json_mode():
        print_json(result)
        return
    print_dict(
        f"Task {task_id}",
        {
            "id": result.get("id"),
            "project_id": result.get("project_id"),
            "task_type": result.get("task_type"),
            "task_status": result.get("task_status"),
            "plan_id": result.get("plan_id") or "none",
            "phase_id": result.get("phase_id") or "none",
            "step_id": result.get("step_id") or "none",
            "created_at": result.get("created_at"),
            "updated_at": result.get("updated_at"),
        },
    )


@app.command("run")
def task_run(
    ctx: typer.Context,
    task_id: str = typer.Argument(..., help="Task ULID to execute"),
    prompt: str = typer.Option(..., "--prompt", help="Prompt text for the model"),
    model_class: Optional[str] = typer.Option(None, "--model", help="Model capability class override"),
    context_tier: Optional[str] = typer.Option(None, "--context", help="Context tier override (execution/hybrid/planning)"),
    project: Optional[str] = typer.Option(None, "--project", help="Override project ID for this run"),
) -> None:
    """Execute a task via the full execution loop. May take up to 120s."""
    client = ctx.obj["client"]
    from cli.output import is_json_mode, print_dict, print_json

    body: dict = {"prompt": prompt}
    if model_class:
        body["model_class"] = model_class
    if context_tier:
        body["context_tier"] = context_tier
    if project:
        body["project_id"] = project

    result = client.post_execute(f"/tasks/{task_id}/execute", json=body)
    if is_json_mode():
        print_json(result)
        return
    print_dict(
        f"Execution Result — {task_id}",
        {
            "task_status": result.get("task_status"),
            "score": result.get("score"),
            "passed": result.get("passed"),
            "duration_ms": result.get("duration_ms"),
            "retry_count": result.get("retry_count"),
            "response_text": (result.get("response_text") or "")[:200],
        },
    )


@app.command("cancel")
def task_cancel(
    ctx: typer.Context,
    task_id: str = typer.Argument(..., help="Task ULID to cancel"),
) -> None:
    """Cancel a pending or running task."""
    client = ctx.obj["client"]
    from cli.output import is_json_mode, print_dict, print_json, print_success

    result = client.post(f"/tasks/{task_id}/cancel")
    if is_json_mode():
        print_json(result)
        return
    print_success(f"Task {task_id} cancelled (status: {result.get('task_status')})")


@app.command("replay")
def task_replay(
    ctx: typer.Context,
    run_id: str = typer.Argument(..., help="Run ULID to replay exactly"),
) -> None:
    """Exact replay of a previous execution run."""
    client = ctx.obj["client"]
    from cli.output import is_json_mode, print_json
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    result = client.post_execute(f"/runs/{run_id}/replay")
    if is_json_mode():
        print_json(result)
        return

    console = Console()

    orig_score  = result.get("original_score")
    new_score   = result.get("new_score")
    orig_passed = result.get("original_passed")
    new_passed  = result.get("new_passed")
    task_type   = result.get("task_type", "unknown")
    duration_ms = result.get("duration_ms")
    model_id    = result.get("model_id", "unknown")

    # Score delta
    if orig_score is not None and new_score is not None:
        delta = new_score - orig_score
        delta_str = f"[green]+{delta:.1f}[/green]" if delta >= 0 else f"[red]{delta:.1f}[/red]"
    else:
        delta_str = "n/a"

    def _pass_label(v) -> str:
        if v is True:
            return "[green]PASS[/green]"
        if v is False:
            return "[red]FAIL[/red]"
        return "n/a"

    table = Table(show_header=True, header_style="bold cyan", box=None)
    table.add_column("", style="bold")
    table.add_column("Original", justify="right")
    table.add_column("Replay", justify="right")
    table.add_column("Delta", justify="right")

    table.add_row(
        "Score",
        f"{orig_score:.1f}" if orig_score is not None else "n/a",
        f"{new_score:.1f}" if new_score is not None else "n/a",
        delta_str,
    )
    table.add_row(
        "Passed",
        _pass_label(orig_passed),
        _pass_label(new_passed),
        "",
    )

    meta_lines = (
        f"[bold]Model:[/bold] {model_id}  "
        f"[bold]Task type:[/bold] {task_type}  "
        f"[bold]Duration:[/bold] {duration_ms}ms\n"
        f"[bold]Original run:[/bold] {result.get('original_run_id')}  "
        f"[bold]New run:[/bold] {result.get('new_run_id')}"
    )

    response_preview = (result.get("response_text") or "")[:300]
    if response_preview:
        response_preview = f"\n[bold]Response preview:[/bold]\n{response_preview}"

    console.print(Panel(
        f"{meta_lines}\n" + response_preview,
        title="[bold blue]Replay Complete[/bold blue]",
        expand=False,
    ))
    console.print(table)
