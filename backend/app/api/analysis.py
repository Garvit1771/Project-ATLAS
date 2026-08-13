"""
ATLAS — Phase 7 analytics + risk status router.

GET /api/analysis/status

Returns the most recently computed AnalyticsResult and RiskResult as a
consistent pair from the same simulation tick.  The router is thin:
it reads shared session state and returns it; no computation is performed
here.  All analysis was already done by the SSE stream loop.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.app.api.models import AnalysisStatusResponse
from backend.app.api import session

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

_NO_DATA_MSG = (
    "No telemetry data available. Connect to /api/telemetry/stream first."
)


@router.get("/status", response_model=AnalysisStatusResponse)
def get_analysis_status() -> AnalysisStatusResponse:
    """
    Return the latest analytics and risk results.

    Returns 503 if the simulation has not yet produced a tick (i.e. the
    SSE stream has not been started, or session was just reset).
    """
    record, analytics, risk = session.get_state_snapshot()

    if analytics is None or risk is None:
        raise HTTPException(status_code=503, detail=_NO_DATA_MSG)

    return AnalysisStatusResponse(analytics=analytics, risk=risk)
