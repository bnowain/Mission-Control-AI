"""
Mission Control — WebSocket API (Phase 2 Stub)
================================================
/ws/execution  → real-time execution event stream

Phase 2: accept connection, send connected message, echo acknowledgements.
Phase 3: stream execution loop events, grading results, escalation signals.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.logging import get_logger

router = APIRouter(tags=["websocket"])

log = get_logger("websocket")


@router.websocket("/ws/execution")
async def ws_execution(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for real-time execution streaming.

    Phase 2 behaviour:
      - Accept the connection
      - Send a 'connected' event
      - Echo any received messages back as acknowledgements

    Phase 3 will push live execution loop events.
    """
    await websocket.accept()
    log.info("WebSocket client connected", client=str(websocket.client))

    await websocket.send_json({
        "event": "connected",
        "service": "mission-control",
        "message": "WebSocket connected. Streaming available in Phase 3.",
    })

    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_json({
                "event": "ack",
                "received": data,
            })
    except WebSocketDisconnect:
        log.info("WebSocket client disconnected")
