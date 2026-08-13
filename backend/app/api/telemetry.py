"""
ATLAS — Phase 7 telemetry router.

GET /api/telemetry/stream   — SSE stream (1 Hz, drives the simulation loop)
GET /api/telemetry/snapshot — latest telemetry record

Implemented in Stage 3 of the Phase 7 build.  The SSE endpoint is the highest-
risk component; it is isolated in its own stage so that the REST routers can be
verified independently first.
"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator

import anyio
import anyio.to_thread

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse

from backend.app.api.models import TelemetrySnapshotResponse
from backend.app.api import session

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])

# Production tick interval in seconds.  Module-level constant so tests can
# patch it via monkeypatch without adding any request-level parameter.
TICK_INTERVAL: float = 1.0

_NO_DATA_MSG = (
    "No telemetry data available. Connect to /api/telemetry/stream first."
)


# ── Tick processing (runs in an anyio worker thread) ─────────────────────────

def _process_tick(gen_iter: "any") -> str:
    """
    Advance the simulation by exactly one tick and update shared state.

    Runs in an anyio worker thread (dispatched by run_sync below) so that
    the synchronous simulation, analytics and risk calls do not block the
    event loop.

    Steps:
      1. Advance the generator.
      2. Run analytics engine (stateful — only called from here).
      3. Compute risk (stateless).
      4. Acquire _state_lock and write the consistent triple atomically.
      5. Return the serialised SSE event string.

    The lock is acquired only for the short write at step 4.  All expensive
    computation happens before the lock is taken.
    """
    record = next(gen_iter)
    analytics = session.analytics_engine.process(record)
    risk = session.risk_engine.compute(
        analytics_result=analytics,
        mission_context=session.mission_context,
        current_record=record,
    )

    with session._state_lock:
        session.latest_record = record
        session.latest_analytics = analytics
        session.latest_risk = risk

    payload = json.dumps(
        {
            "tick": record.tick,
            "timestamp": record.timestamp.isoformat(),
            "telemetry": record.model_dump(mode="json"),
            "analytics": analytics.model_dump(mode="json"),
            "risk": risk.model_dump(mode="json"),
        }
    )
    return f"event: tick\ndata: {payload}\n\n"


# ── SSE stream endpoint ───────────────────────────────────────────────────────

@router.get("/stream")
async def telemetry_stream() -> StreamingResponse:
    """
    Server-Sent Events stream of simulation ticks at 1 Hz.

    Each event carries the full telemetry, analytics, and risk result for
    one tick.  This is the only code path that advances the simulation — REST
    endpoints read the latest_* state written here.

    Single-operator enforcement: if an SSE stream is already active, returns
    HTTP 409 Conflict.  This prevents two generators from advancing the same
    TelemetryGenerator or AnalyticsEngine concurrently.

    Client disconnect and server shutdown are handled via the finally block
    in event_generator(), which always clears _stream_active.
    """
    with session._state_lock:
        if session._stream_active:
            return Response(
                content='{"detail": "An SSE stream is already active."}',
                status_code=409,
                media_type="application/json",
            )
        session._stream_active = True

    async def event_generator() -> AsyncGenerator[str, None]:
        # Create a local iterator reference so process_tick closure is clean.
        gen_iter = session.generator.stream()
        try:
            while True:
                event_str = await anyio.to_thread.run_sync(
                    _process_tick, gen_iter, abandon_on_cancel=False
                )
                yield event_str
                await asyncio.sleep(TICK_INTERVAL)
        finally:
            # Always clear the stream-active flag, regardless of how the
            # generator exits (client disconnect, exception, server shutdown).
            with session._state_lock:
                session._stream_active = False

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Snapshot endpoint ─────────────────────────────────────────────────────────

@router.get("/snapshot", response_model=TelemetrySnapshotResponse)
def get_telemetry_snapshot() -> TelemetrySnapshotResponse:
    """
    Return the most recently processed telemetry record.

    Returns 503 if the SSE stream has not yet produced a tick.
    """
    record, _, _ = session.get_state_snapshot()

    if record is None:
        raise HTTPException(status_code=503, detail=_NO_DATA_MSG)

    return TelemetrySnapshotResponse(
        tick=record.tick,
        timestamp=record.timestamp,
        telemetry=record,
    )
