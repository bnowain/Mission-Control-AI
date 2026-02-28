"""
Mission Control — Events API (Phase 4)
========================================
GET    /events                — recent event log (paginated)
POST   /events/webhooks       — register webhook
GET    /events/webhooks       — list webhooks
DELETE /events/webhooks/{id}  — remove webhook
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.database.async_helpers import run_in_thread
from app.models.schemas import (
    EventListResponse,
    EventResponse,
    WebhookCreateRequest,
    WebhookListResponse,
    WebhookResponse,
)
from app.processing.events import (
    add_webhook,
    get_recent_events,
    list_webhooks,
    remove_webhook,
)

router = APIRouter(prefix="/events", tags=["events"])


def _webhook_row_to_response(row: dict) -> WebhookResponse:
    import json
    try:
        event_types = json.loads(row.get("event_types") or "[]")
    except Exception:
        event_types = []
    return WebhookResponse(
        id=row["id"],
        url=row["url"],
        event_types=event_types,
        active=bool(row.get("active", 1)),
        created_at=str(row.get("created_at", "")),
    )


# ── GET /events ──────────────────────────────────────────────────────────────

@router.get("", response_model=EventListResponse)
async def get_events(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    event_type: Optional[str] = Query(default=None),
):
    """Return recent events from event_log, newest first."""
    rows, total = await run_in_thread(
        get_recent_events,
        limit=limit,
        offset=offset,
        event_type=event_type,
    )
    events = [
        EventResponse(
            id=r["id"],
            event_type=r["event_type"],
            artifact_id=r.get("artifact_id"),
            payload_json=r.get("payload_json"),
            delivered=bool(r.get("delivered", False)),
            created_at=str(r.get("created_at", "")),
        )
        for r in rows
    ]
    return EventListResponse(events=events, total=total, limit=limit, offset=offset)


# ── POST /events/webhooks ────────────────────────────────────────────────────

@router.post("/webhooks", status_code=201, response_model=WebhookResponse)
async def create_webhook(req: WebhookCreateRequest):
    """Register a webhook subscriber."""
    row = await run_in_thread(
        add_webhook,
        req.url,
        event_types=req.event_types,
        secret=req.secret,
    )
    return _webhook_row_to_response(row)


# ── GET /events/webhooks ─────────────────────────────────────────────────────

@router.get("/webhooks", response_model=WebhookListResponse)
async def get_webhooks():
    """List all active webhook subscribers."""
    rows = await run_in_thread(list_webhooks)
    return WebhookListResponse(webhooks=[_webhook_row_to_response(r) for r in rows])


# ── DELETE /events/webhooks/{id} ─────────────────────────────────────────────

@router.delete("/webhooks/{webhook_id}", status_code=204)
async def delete_webhook(webhook_id: str):
    """Remove a webhook (soft delete)."""
    found = await run_in_thread(remove_webhook, webhook_id)
    if not found:
        raise HTTPException(status_code=404, detail=f"Webhook '{webhook_id}' not found")
