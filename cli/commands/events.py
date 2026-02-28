"""
CLI command group: mission-control events
==========================================
events list           → GET    /events
events webhooks       → GET    /events/webhooks
events webhook-add    → POST   /events/webhooks
events webhook-remove → DELETE /events/webhooks/{id}
"""

from __future__ import annotations

from typing import List, Optional

import typer

app = typer.Typer(help="List events and manage webhooks.")


@app.command("list")
def events_list(
    ctx: typer.Context,
    limit: int = typer.Option(20, "--limit", help="Max results"),
    event_type: Optional[str] = typer.Option(None, "--type", help="Filter by event type"),
) -> None:
    """List recent events."""
    client = ctx.obj["client"]
    from cli.output import is_json_mode, print_json, print_table

    params: dict = {"limit": limit}
    if event_type:
        params["event_type"] = event_type

    result = client.get("/events", params=params)
    events = result if isinstance(result, list) else result.get("events", [])

    if is_json_mode():
        print_json(result)
        return
    rows = [
        [
            e.get("id", ""),
            e.get("event_type", ""),
            e.get("source_id") or "",
            e.get("created_at", ""),
        ]
        for e in events
    ]
    print_table("Events", ["ID", "Type", "Source ID", "Created At"], rows)


@app.command("webhooks")
def events_webhooks(ctx: typer.Context) -> None:
    """List registered webhooks."""
    client = ctx.obj["client"]
    from cli.output import is_json_mode, print_json, print_table

    result = client.get("/events/webhooks")
    webhooks = result if isinstance(result, list) else result.get("webhooks", [])

    if is_json_mode():
        print_json(result)
        return
    rows = [
        [
            w.get("id", ""),
            w.get("url", ""),
            ", ".join(w.get("event_types") or []),
            w.get("created_at", ""),
        ]
        for w in webhooks
    ]
    print_table("Webhooks", ["ID", "URL", "Event Types", "Created At"], rows)


@app.command("webhook-add")
def events_webhook_add(
    ctx: typer.Context,
    url: str = typer.Argument(..., help="Webhook URL"),
    types: Optional[List[str]] = typer.Option(None, "--types", help="Event types to subscribe to"),
) -> None:
    """Register a new webhook."""
    client = ctx.obj["client"]
    from cli.output import is_json_mode, print_dict, print_json, print_success

    body: dict = {"url": url}
    if types:
        body["event_types"] = types

    result = client.post("/events/webhooks", json=body)
    if is_json_mode():
        print_json(result)
        return
    print_success(f"Webhook registered: {result.get('id')}")


@app.command("webhook-remove")
def events_webhook_remove(
    ctx: typer.Context,
    webhook_id: str = typer.Argument(..., help="Webhook ID to delete"),
) -> None:
    """Remove a webhook by ID."""
    client = ctx.obj["client"]
    from cli.output import is_json_mode, print_json, print_success

    client.delete(f"/events/webhooks/{webhook_id}")
    if is_json_mode():
        print_json({"deleted": webhook_id})
        return
    print_success(f"Webhook {webhook_id} removed.")
