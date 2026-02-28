"""
CLI command: mission-control coder
====================================
Interactive REPL that wraps the REST API.
WebSocket streaming deferred (still an echo stub) — uses REST loop instead.

Slash commands:
  /status              → GET /system/status
  /project <id>        → set active project
  /model <class>       → set capability class (fast_model, coder_model, etc.)
  /context <tier>      → set context tier (execution, hybrid, planning)
  /quit                → exit

Any other input → POST /tasks (create) + POST /tasks/{id}/execute (run)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import typer
from rich.console import Console
from rich.prompt import Prompt

app = typer.Typer(help="Interactive coder REPL — wraps task create + execute.")


@dataclass
class CoderSession:
    project: Optional[str] = None
    model_class: Optional[str] = None
    context_tier: str = "execution"


def _prompt_str(session: CoderSession) -> str:
    parts = [
        session.project or "no-project",
        session.model_class or "auto-model",
        session.context_tier,
    ]
    return f"[MC] {' | '.join(parts)} > "


@app.callback(invoke_without_command=True)
def coder_cmd(ctx: typer.Context) -> None:
    """Launch the interactive coder REPL."""
    client = ctx.obj["client"]
    console = Console()

    session = CoderSession()

    # Try to grab default project/model from config
    cfg = ctx.obj.get("config")
    if cfg:
        session.project = cfg.default_project
        session.model_class = cfg.default_model

    console.print("[bold cyan]Mission Control — Interactive Coder[/bold cyan]")
    console.print(f"Backend: [dim]{ctx.obj['client'].base_url}[/dim]")
    console.print("Slash commands: /status  /project <id>  /model <class>  /context <tier>  /quit")
    console.print()

    while True:
        try:
            raw = Prompt.ask(_prompt_str(session)).strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Exiting coder. Goodbye.[/dim]")
            break

        if not raw:
            continue

        # --- Slash commands ---
        if raw.startswith("/"):
            parts = raw[1:].split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""

            if cmd == "quit":
                console.print("[dim]Goodbye.[/dim]")
                break

            elif cmd == "status":
                try:
                    health = client.get("/api/health")
                    sys_st = client.get("/system/status")
                    console.print(
                        f"[green]health:[/green] {health.get('status')}  "
                        f"[green]schema:[/green] {sys_st.get('schema_version')}  "
                        f"[green]active_tasks:[/green] {sys_st.get('active_task_count')}"
                    )
                except SystemExit:
                    pass

            elif cmd == "project":
                if not arg:
                    console.print(f"Current project: [cyan]{session.project or 'none'}[/cyan]")
                else:
                    session.project = arg
                    console.print(f"[green]Project set to:[/green] {arg}")

            elif cmd == "model":
                if not arg:
                    console.print(f"Current model class: [cyan]{session.model_class or 'auto'}[/cyan]")
                else:
                    session.model_class = arg
                    console.print(f"[green]Model class set to:[/green] {arg}")

            elif cmd == "context":
                valid = ("execution", "hybrid", "planning")
                if not arg:
                    console.print(f"Current context tier: [cyan]{session.context_tier}[/cyan]")
                elif arg not in valid:
                    console.print(f"[red]Invalid tier.[/red] Valid: {', '.join(valid)}")
                else:
                    session.context_tier = arg
                    console.print(f"[green]Context tier set to:[/green] {arg}")

            else:
                console.print(f"[yellow]Unknown command: /{cmd}[/yellow]")

        else:
            # Treat as prompt — create task then execute
            if not session.project:
                console.print("[yellow]No project set. Use /project <id> first.[/yellow]")
                continue

            try:
                # Step 1: create task
                task_body: dict = {
                    "project_id": session.project,
                    "task_type": "generic",
                }
                task = client.post("/tasks", json=task_body)
                task_id = task.get("id")
                console.print(f"[dim]Task created: {task_id}[/dim]")

                # Step 2: execute task
                exec_body: dict = {
                    "prompt": raw,
                    "context_tier": session.context_tier,
                }
                if session.model_class:
                    exec_body["model_class"] = session.model_class

                console.print(f"[dim]Executing... (context: {session.context_tier})[/dim]")
                result = client.post_execute(f"/tasks/{task_id}/execute", json=exec_body)

                score = result.get("score", "?")
                passed = result.get("passed", "?")
                duration = result.get("duration_ms", "?")
                console.print(
                    f"[bold]Score:[/bold] {score}  [bold]Passed:[/bold] {passed}  "
                    f"[bold]Duration:[/bold] {duration}ms"
                )
                response = (result.get("response_text") or "").strip()
                if response:
                    console.print()
                    console.print(response)
                    console.print()

            except SystemExit:
                # HTTP error already printed by api_client
                pass
