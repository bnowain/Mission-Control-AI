"""
Mission Control CLI — Entry Point
===================================
Usage:
    mission-control [OPTIONS] COMMAND [ARGS]...

Install:
    pip install -e .
    mission-control --help
"""

from __future__ import annotations

from typing import Optional

import typer

from cli import __version__
from cli.commands import (
    artifacts,
    backfill,
    codex,
    coder,
    events,
    rag,
    router,
    sql,
    status,
    task,
    telemetry,
    workers,
)

app = typer.Typer(
    name="mission-control",
    help="Mission Control — Adaptive AI Execution Framework CLI",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)

# ── Register sub-command groups ──────────────────────────────────────────────

app.add_typer(task.app,      name="task",      help="Create, view, run, cancel, replay tasks.")
app.add_typer(status.app,    name="status",    help="System status, hardware, and health check.")
app.add_typer(artifacts.app, name="artifacts", help="Artifact ingest, list, export, state.")
app.add_typer(workers.app,   name="workers",   help="Worker pipelines, jobs, stats.")
app.add_typer(events.app,    name="events",    help="Events and webhooks.")
app.add_typer(router.app,    name="router",    help="Router stats and model selection.")
app.add_typer(telemetry.app, name="telemetry", help="Execution telemetry and performance.")
app.add_typer(codex.app,     name="codex",     help="Codex knowledge base.")
app.add_typer(sql.app,       name="sql",       help="SQL query interface.")
app.add_typer(coder.app,     name="coder",     help="Interactive coder REPL.")
app.add_typer(rag.app,       name="rag",       help="RAG: index codebases/web and search.")

# backfill is a single-argument command — registered directly to avoid
# Click Group + Argument parsing issues with invoke_without_command.
app.command("backfill", help="Trigger a backfill pipeline run.")(backfill.backfill_cmd)


# ── Version callback (Typer pattern for eager flags) ─────────────────────────

def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"mission-control {__version__}")
        raise typer.Exit()


# ── Global options callback ───────────────────────────────────────────────────

@app.callback()
def main_callback(
    ctx: typer.Context,
    api_endpoint: Optional[str] = typer.Option(
        None, "--api-endpoint", "-e",
        envvar="MISSION_CONTROL_ENDPOINT",
        help="Backend API URL (default: http://localhost:8860)",
    ),
    api_key: Optional[str] = typer.Option(
        None, "--api-key",
        envvar="MISSION_CONTROL_API_KEY",
        help="API key for authentication",
    ),
    project: Optional[str] = typer.Option(
        None, "--project", "-p",
        help="Default project ID for this session",
    ),
    model: Optional[str] = typer.Option(
        None, "--model", "-m",
        help="Default model capability class (fast_model, coder_model, etc.)",
    ),
    json_output: bool = typer.Option(
        False, "--json",
        help="Output raw JSON instead of rich tables",
    ),
    debug: bool = typer.Option(
        False, "--debug",
        help="Print request details to stderr",
    ),
    version: Optional[bool] = typer.Option(
        None, "--version", "-v",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit",
    ),
) -> None:
    """Mission Control CLI — global options applied to every command."""
    from cli.config import load_config
    from cli.api_client import MCClient
    from cli.output import set_json_mode

    cfg = load_config(
        endpoint=api_endpoint,
        api_key=api_key,
        project=project,
        model=model,
    )

    set_json_mode(json_output)

    ctx.ensure_object(dict)
    ctx.obj["client"] = MCClient(cfg, debug=debug)
    ctx.obj["config"] = cfg
    ctx.obj["debug"] = debug


# ── Console entry point ───────────────────────────────────────────────────────

def run() -> None:
    app()


if __name__ == "__main__":
    run()
