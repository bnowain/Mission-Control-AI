"""
Mission Control — Event System (Phase 4)
=========================================
In-memory subscriber dispatch + event_log DB persistence + webhook delivery.

Design:
  - emit() is synchronous (for sync business logic callers)
  - Webhook delivery is best-effort; no retry queue in Phase 4
  - In-memory subscribers are per-process; lost on restart (expected for Phase 4)
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Callable, Optional

from ulid import ULID

from app.core.logging import get_logger
from app.database.init import get_connection

log = get_logger("processing.events")


class EventDispatcher:
    """
    Emits events, persists them to event_log, dispatches webhooks.
    """

    def __init__(self) -> None:
        self._subscribers: list[Callable[[str, Optional[str], dict], None]] = []

    # ── Emit ────────────────────────────────────────────────────────────────

    def emit(
        self,
        event_type: str,
        artifact_id: Optional[str] = None,
        payload: Optional[dict] = None,
    ) -> str:
        """
        Persist event to event_log, notify in-memory subscribers, dispatch webhooks.
        Returns the event_id (ULID).
        """
        event_id = str(ULID())
        now = datetime.now(timezone.utc).isoformat()
        payload_str = json.dumps(payload or {})

        # Persist
        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO event_log (id, event_type, artifact_id, payload_json, delivered, created_at)
                VALUES (?, ?, ?, ?, 0, ?)
                """,
                (event_id, event_type, artifact_id, payload_str, now),
            )
            conn.commit()
        finally:
            conn.close()

        # Notify in-memory subscribers
        for fn in self._subscribers:
            try:
                fn(event_type, artifact_id, payload or {})
            except Exception as exc:
                log.warning("Event subscriber error", event_type=event_type, exc=str(exc))

        # Dispatch webhooks (best-effort)
        self._dispatch_webhooks(event_id, event_type, artifact_id, payload or {})

        log.info("Event emitted", event_id=event_id, event_type=event_type, artifact_id=artifact_id)
        return event_id

    # ── Subscribe (in-memory) ────────────────────────────────────────────────

    def subscribe(self, fn: Callable[[str, Optional[str], dict], None]) -> None:
        """Register an in-memory subscriber. Called for every emitted event."""
        self._subscribers.append(fn)

    # ── Webhooks ─────────────────────────────────────────────────────────────

    def add_webhook(
        self,
        url: str,
        event_types: Optional[list[str]] = None,
        secret: Optional[str] = None,
    ) -> dict:
        """Register a webhook subscriber."""
        webhook_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        event_types_str = json.dumps(event_types or [])

        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO webhook_subscribers (id, url, event_types, active, secret, created_at)
                VALUES (?, ?, ?, 1, ?, ?)
                """,
                (webhook_id, url, event_types_str, secret, now),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM webhook_subscribers WHERE id = ?", (webhook_id,)
            ).fetchone()
            log.info("Webhook registered", webhook_id=webhook_id, url=url)
            return dict(row)
        finally:
            conn.close()

    def list_webhooks(self) -> list[dict]:
        """Return all active webhook subscribers."""
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM webhook_subscribers WHERE active = 1 ORDER BY created_at"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def remove_webhook(self, webhook_id: str) -> bool:
        """Soft-delete a webhook. Returns True if found, False if not."""
        conn = get_connection()
        try:
            cursor = conn.execute(
                "UPDATE webhook_subscribers SET active = 0 WHERE id = ?",
                (webhook_id,),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    # ── Event log queries ────────────────────────────────────────────────────

    def get_recent(
        self,
        limit: int = 50,
        offset: int = 0,
        event_type: Optional[str] = None,
    ) -> tuple[list[dict], int]:
        """Return (events, total) with optional event_type filter."""
        conn = get_connection()
        try:
            where = "WHERE event_type = ?" if event_type else ""
            params_filter = [event_type] if event_type else []

            total = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM event_log {where}", params_filter
            ).fetchone()["cnt"]

            rows = conn.execute(
                f"SELECT * FROM event_log {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params_filter + [limit, offset],
            ).fetchall()
            return [dict(r) for r in rows], total
        finally:
            conn.close()

    # ── Internal ─────────────────────────────────────────────────────────────

    def _dispatch_webhooks(
        self,
        event_id: str,
        event_type: str,
        artifact_id: Optional[str],
        payload: dict,
    ) -> None:
        """Best-effort webhook delivery. Failures are logged, not re-queued."""
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM webhook_subscribers WHERE active = 1"
            ).fetchall()
            webhooks = [dict(r) for r in rows]
        finally:
            conn.close()

        if not webhooks:
            return

        import urllib.request

        for wh in webhooks:
            # Check event_type filter
            try:
                subscribed_types = json.loads(wh.get("event_types") or "[]")
            except Exception:
                subscribed_types = []

            if subscribed_types and event_type not in subscribed_types:
                continue

            try:
                body = json.dumps({
                    "event_id": event_id,
                    "event_type": event_type,
                    "artifact_id": artifact_id,
                    "payload": payload,
                }).encode("utf-8")

                req = urllib.request.Request(
                    wh["url"],
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    # Mark delivered
                    conn2 = get_connection()
                    try:
                        conn2.execute(
                            "UPDATE event_log SET delivered = 1 WHERE id = ?", (event_id,)
                        )
                        conn2.commit()
                    finally:
                        conn2.close()
                log.info("Webhook delivered", webhook_id=wh["id"], event_id=event_id)
            except Exception as exc:
                log.warning(
                    "Webhook delivery failed",
                    webhook_id=wh["id"],
                    url=wh["url"],
                    exc=str(exc),
                )


# ---------------------------------------------------------------------------
# Module-level singleton + convenience wrappers
# ---------------------------------------------------------------------------

_dispatcher = EventDispatcher()


def emit_event(event_type: str, artifact_id: Optional[str] = None, payload: Optional[dict] = None) -> str:
    return _dispatcher.emit(event_type, artifact_id=artifact_id, payload=payload)


def subscribe_events(fn: Callable) -> None:
    _dispatcher.subscribe(fn)


def add_webhook(url: str, event_types: Optional[list[str]] = None, secret: Optional[str] = None) -> dict:
    return _dispatcher.add_webhook(url, event_types=event_types, secret=secret)


def list_webhooks() -> list[dict]:
    return _dispatcher.list_webhooks()


def remove_webhook(webhook_id: str) -> bool:
    return _dispatcher.remove_webhook(webhook_id)


def get_recent_events(limit: int = 50, offset: int = 0, event_type: Optional[str] = None) -> tuple[list[dict], int]:
    return _dispatcher.get_recent(limit=limit, offset=offset, event_type=event_type)
