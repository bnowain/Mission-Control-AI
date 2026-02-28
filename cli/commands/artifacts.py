"""
CLI command group: mission-control artifacts
=============================================
artifacts list    → GET  /artifacts
artifacts view    → GET  /artifacts/{id}
artifacts export  → GET  /artifacts/{id}/export
artifacts ingest  → POST /artifacts
artifacts process → POST /artifacts/{id}/process
artifacts state   → POST /artifacts/{id}/state
"""

from __future__ import annotations

from typing import Optional

import typer

app = typer.Typer(help="Manage artifacts: ingest, list, export, process.")


@app.command("list")
def artifacts_list(
    ctx: typer.Context,
    limit: int = typer.Option(20, "--limit", help="Max results (1-100)"),
    offset: int = typer.Option(0, "--offset", help="Pagination offset"),
    state: Optional[str] = typer.Option(None, "--state", help="Filter by processing_state"),
    source_type: Optional[str] = typer.Option(None, "--type", help="Filter by source_type"),
) -> None:
    """List artifacts with optional filters."""
    client = ctx.obj["client"]
    from cli.output import is_json_mode, print_json, print_table

    params: dict = {"limit": limit, "offset": offset}
    if state:
        params["processing_state"] = state
    if source_type:
        params["source_type"] = source_type

    result = client.get("/artifacts", params=params)
    artifacts = result.get("artifacts", [])

    if is_json_mode():
        print_json(result)
        return

    rows = [
        [
            a.get("id", ""),
            a.get("source_type", ""),
            a.get("processing_state", ""),
            a.get("mime_type") or "",
            a.get("file_size_bytes") or "",
            a.get("ingest_at", ""),
        ]
        for a in artifacts
    ]
    print_table(
        f"Artifacts ({result.get('total', len(artifacts))} total)",
        ["ID", "Type", "State", "MIME", "Size (B)", "Ingested At"],
        rows,
    )


@app.command("view")
def artifacts_view(
    ctx: typer.Context,
    artifact_id: str = typer.Argument(..., help="Artifact UUID"),
) -> None:
    """View a single artifact by ID."""
    client = ctx.obj["client"]
    from cli.output import is_json_mode, print_dict, print_json

    result = client.get(f"/artifacts/{artifact_id}")
    if is_json_mode():
        print_json(result)
        return
    print_dict(
        f"Artifact {artifact_id}",
        {k: v for k, v in result.items() if v is not None},
    )


@app.command("export")
def artifacts_export(
    ctx: typer.Context,
    artifact_id: str = typer.Argument(..., help="Artifact UUID"),
) -> None:
    """Export artifact data (raw + extracted + analysis layers)."""
    client = ctx.obj["client"]
    from cli.output import is_json_mode, print_dict, print_json

    result = client.get(f"/artifacts/{artifact_id}/export")
    if is_json_mode():
        print_json(result)
        return
    # Show each layer as a dict panel
    for layer in ("raw", "extracted", "analysis"):
        data = result.get(layer) or {}
        if data:
            print_dict(f"Layer: {layer}", data if isinstance(data, dict) else {"data": str(data)})


@app.command("ingest")
def artifacts_ingest(
    ctx: typer.Context,
    source_type: Optional[str] = typer.Option(None, "--type", help="Source type (e.g. pdf, audio)"),
    source_hash: Optional[str] = typer.Option(None, "--hash", help="SHA256 hash of source file"),
    file_path: Optional[str] = typer.Option(None, "--file", help="Local file path"),
    page_url: Optional[str] = typer.Option(None, "--url", help="Page URL for external sources"),
    pipeline_version: Optional[str] = typer.Option(None, "--pipeline-version"),
) -> None:
    """Ingest a new artifact (deduplicates by source_hash)."""
    client = ctx.obj["client"]
    from cli.output import is_json_mode, print_dict, print_json, print_success

    body: dict = {}
    if source_type:
        body["source_type"] = source_type
    if source_hash:
        body["source_hash"] = source_hash
    if file_path:
        body["file_path"] = file_path
    if page_url:
        body["page_url"] = page_url
    if pipeline_version:
        body["pipeline_version"] = pipeline_version

    result = client.post("/artifacts", json=body)
    if is_json_mode():
        print_json(result)
        return
    print_dict("Artifact Ingested", {k: v for k, v in result.items() if v is not None})


@app.command("process")
def artifacts_process(
    ctx: typer.Context,
    artifact_id: str = typer.Argument(..., help="Artifact UUID"),
    pipeline: str = typer.Option(..., "--pipeline", help="Pipeline name"),
    priority: int = typer.Option(5, "--priority", help="Job priority (1=highest, 10=lowest)"),
) -> None:
    """Enqueue a processing job for an artifact."""
    client = ctx.obj["client"]
    from cli.output import is_json_mode, print_dict, print_json, print_success

    body = {"pipeline_name": pipeline, "priority": priority}
    result = client.post(f"/artifacts/{artifact_id}/process", json=body)
    if is_json_mode():
        print_json(result)
        return
    print_success(f"Job enqueued: {result.get('job_id')} (status: {result.get('job_status')})")


@app.command("state")
def artifacts_state(
    ctx: typer.Context,
    artifact_id: str = typer.Argument(..., help="Artifact UUID"),
    to: str = typer.Option(..., "--to", help="Target state (e.g. PROCESSING, PROCESSED)"),
) -> None:
    """Transition artifact to a new state."""
    client = ctx.obj["client"]
    from cli.output import is_json_mode, print_dict, print_json, print_success

    body = {"new_state": to}
    result = client.post(f"/artifacts/{artifact_id}/state", json=body)
    if is_json_mode():
        print_json(result)
        return
    print_success(
        f"Artifact {artifact_id} → {result.get('processing_state')}"
    )
