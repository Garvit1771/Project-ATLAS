"""
ATLAS — Phase 7 analytics + risk status router.
Phase 8 addition: GET /api/analysis/explain

GET /api/analysis/status   — latest analytics + risk (deterministic)
GET /api/analysis/explain  — IBM Granite anomaly explanation (AI layer)

The explain endpoint is separated from the status endpoint intentionally:
  - /status is fast (reads shared state, no I/O)
  - /explain calls Granite synchronously and may be slow (network I/O)
  - Keeping them separate ensures Granite latency NEVER blocks telemetry
    tick delivery.  The frontend may call /explain on demand (e.g. when
    composite_anomaly first becomes True) rather than on every tick.

The explain endpoint follows the same Granite grounding rules as the
existing Phase 6 prompts: all numbers come from computed state; Granite
receives an evidence block and may only explain, not calculate.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.app.ai.prompts import build_anomaly_prompt
from backend.app.api.models import AnalysisStatusResponse, ExplanationResponse
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


@router.get("/explain", response_model=ExplanationResponse)
def get_anomaly_explanation() -> ExplanationResponse:
    """
    Return an IBM Granite anomaly explanation grounded in the current
    analytics and risk state.

    This endpoint follows the Phase 6 Granite Prompt Contract:
      - All evidence is derived from computed state (AnalyticsResult +
        RiskResult), never invented.
      - The prompt instructs Granite not to state numerical values.
      - procedures.md content is never injected (enforced by
        KnowledgeContextLoader).
      - If Granite is unavailable, the Phase 6 fallback message is
        returned — the endpoint always returns HTTP 200 when state is
        present.

    Returns:
        200 with ExplanationResponse.
        503 if no ticks have been processed yet.

    Note: this endpoint calls Granite synchronously.  Granite network
    latency may make this call slow (typically 1–4 seconds).  Callers
    should not invoke this on every tick; poll only when the Intelligence
    panel needs a fresh explanation (e.g. when composite_anomaly changes).
    """
    record, analytics, risk = session.get_state_snapshot()

    if analytics is None or risk is None:
        raise HTTPException(status_code=503, detail=_NO_DATA_MSG)

    # Determine the most relevant subsystem for knowledge context injection.
    # composite_subsystem is set when Layer 3 correlation fires; fall back to
    # the dominant individual detection's subsystem, then to "propulsion" as
    # the FAULT-01 primary subsystem.
    subsystem = analytics.composite_subsystem or "propulsion"
    if not analytics.composite_subsystem and analytics.detections:
        subsystem = analytics.detections[0].subsystem

    knowledge = session.knowledge_loader.load(subsystem, session.mission_context)

    prompt = build_anomaly_prompt(
        analytics_result=analytics,
        risk_result=risk,
        mission_context=session.mission_context,
        knowledge_context=knowledge,
    )
    explanation = session.granite_client.explain_anomaly(prompt)

    return ExplanationResponse(explanation=explanation, subsystem=subsystem)
