"""
CLI command group: mission-control workers
===========================================
workers pipelines → GET /workers/pipelines
workers jobs      → GET /workers/jobs
workers job       → GET /workers/jobs/{id}
workers stats     → GET /workers/stats
"""

from __future__ import annotations

from typing import Optional

import typer

app = typer.Typer(help="Inspect worker pipelines, jobs, and stats.")


@app.command("pipelines")
def workers_pipelines(ctx: typer.Context) -> None:
    """List all registered processing pipelines."""
    client = ctx.obj["client"]
    from cli.output import is_json_mode, print_json, print_table

    result = client.get("/workers/pipelines")
    pipelines = result if isinstance(result, list) else result.get("pipelines", [])

    if is_json_mode():
        print_json(pipelines)
        return
    rows = [
        [
            p.get("name", ""),
            p.get("version", ""),
            p.get("description", ""),
        ]
        for p in pipelines
    ]
    print_table("Registered Pipelines", ["Name", "Version", "Description"], rows)


@app.command("jobs")
def workers_jobs(
    ctx: typer.Context,
    limit: int = typer.Option(20, "--limit", help="Max results"),
    status: Optional[str] = typer.Option(None, "--status", help="Filter by job_status"),
) -> None:
    """List processing jobs."""
    client = ctx.obj["client"]
    from cli.output import is_json_mode, print_json, print_table

    params: dict = {"limit": limit}
    if status:
        params["job_status"] = status

    result = client.get("/workers/jobs", params=params)
    jobs = result if isinstance(result, list) else result.get("jobs", [])

    if is_json_mode():
        print_json(result)
        return
    rows = [
        [
            j.get("id", ""),
            j.get("pipeline_name", ""),
            j.get("job_status", ""),
            j.get("priority", ""),
            j.get("artifact_id") or "",
            j.get("created_at", ""),
        ]
        for j in jobs
    ]
    print_table("Jobs", ["ID", "Pipeline", "Status", "Priority", "Artifact ID", "Created At"], rows)


@app.command("job")
def workers_job(
    ctx: typer.Context,
    job_id: str = typer.Argument(..., help="Job ULID"),
) -> None:
    """View a single job by ID."""
    client = ctx.obj["client"]
    from cli.output import is_json_mode, print_dict, print_json

    result = client.get(f"/workers/jobs/{job_id}")
    if is_json_mode():
        print_json(result)
        return
    print_dict(f"Job {job_id}", {k: v for k, v in result.items() if v is not None})


@app.command("stats")
def workers_stats(ctx: typer.Context) -> None:
    """Show worker job counts by status."""
    client = ctx.obj["client"]
    from cli.output import is_json_mode, print_dict, print_json

    result = client.get("/workers/stats")
    if is_json_mode():
        print_json(result)
        return
    print_dict("Worker Stats", result)
