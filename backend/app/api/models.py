"""
ATLAS — Phase 7 API-layer request and response models.

These models are the HTTP interface contract for Phase 7 endpoints.
They are thin wrappers around existing domain models where possible,
and new Pydantic models only where the API surface requires something
the domain models do not already provide.

Domain models (Phase 1) are reused directly where the response shape
matches them exactly — e.g. DecisionResult is returned as-is from
GET /api/decision/options.

Source tags per methodology.md Section 8 are documented on each field.
"""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field

from backend.app.models.analytics import AnalyticsResult
from backend.app.models.decision import WhatIfResult
from backend.app.models.risk import RiskResult
from backend.app.models.telemetry import TelemetryRecord


# ── Request models ────────────────────────────────────────────────────────────

class WhatIfRequest(BaseModel):
    """
    Request body for POST /api/decision/whatif.

    option_id must match a key in the active scenario's options dict
    (e.g. "SWITCH_REDUNDANT", "REDUCE_LOAD", "CONTINUE").
    """

    option_id: str = Field(
        ...,
        min_length=1,
        description="Scenario option key to evaluate (e.g. 'SWITCH_REDUNDANT')",
    )


class CopilotRequest(BaseModel):
    """
    Request body for POST /api/copilot/ask.

    question must be a non-empty string.  Whitespace-only strings are
    rejected at the route handler level (not at the model level) so that
    the 400 response includes a meaningful detail message.
    """

    question: str = Field(
        ...,
        min_length=1,
        description="Operator question for the Copilot panel",
    )


# ── Response models ───────────────────────────────────────────────────────────

class TelemetrySnapshotResponse(BaseModel):
    """
    Response for GET /api/telemetry/snapshot.

    Returns the most recently processed TelemetryRecord so the frontend
    can populate without waiting for the SSE stream.
    Source tag for all telemetry values: COMPUTED.
    """

    tick: int = Field(..., description="Simulation tick counter (0-based)")
    timestamp: datetime = Field(..., description="UTC timestamp of the record")
    telemetry: TelemetryRecord = Field(
        ..., description="Full telemetry record for this tick"
    )


class AnalysisStatusResponse(BaseModel):
    """
    Response for GET /api/analysis/status.

    Returns the most recent analytics and risk outputs together so the
    Intelligence panel can be populated from a single request.
    Source tag: COMPUTED for all fields.
    """

    analytics: AnalyticsResult = Field(
        ..., description="Anomaly detection result for the latest tick"
    )
    risk: RiskResult = Field(
        ..., description="Risk assessment result for the latest tick"
    )


class WhatIfResponse(BaseModel):
    """
    Response for POST /api/decision/whatif.

    Combines the deterministic what-if re-scoring result (source: COMPUTED)
    with an optional IBM Granite narrative explaining the projected delta
    (source: AI EXPLANATION).  The deterministic result is always present;
    ai_narrative falls back to the Phase 6 unavailability message if
    Granite is not configured.
    """

    what_if: WhatIfResult = Field(
        ...,
        description=(
            "Deterministic what-if result: current_risk, projected_risk, delta. "
            "Source tag: COMPUTED."
        ),
    )
    ai_narrative: str = Field(
        ...,
        description=(
            "IBM Granite natural-language explanation of the projected risk delta. "
            "Source tag: AI EXPLANATION. "
            "Falls back to explicit unavailability message if Granite is not configured."
        ),
    )


class CopilotResponse(BaseModel):
    """
    Response for POST /api/copilot/ask.

    Contains the Granite Copilot answer (source: AI EXPLANATION) or the
    Phase 6 fallback message if Granite is unavailable.
    """

    answer: str = Field(
        ...,
        description=(
            "IBM Granite Copilot answer to the operator's question. "
            "Source tag: AI EXPLANATION. "
            "Falls back to explicit unavailability message if Granite is not configured."
        ),
    )


class ExplanationResponse(BaseModel):
    """
    Response for GET /api/analysis/explain.

    Contains the IBM Granite anomaly explanation grounded in the current
    analytics and risk state (source: AI EXPLANATION), plus the subsystem
    the explanation relates to.  Falls back to the Phase 6 unavailability
    message if Granite is not configured.

    The deterministic analytics/risk data is NOT duplicated here — the
    frontend already has it from the SSE stream.  This response carries
    only the AI layer output.
    """

    explanation: str = Field(
        ...,
        description=(
            "IBM Granite anomaly explanation grounded in the computed evidence. "
            "Source tag: AI EXPLANATION. "
            "Falls back to explicit unavailability message if Granite is not configured."
        ),
    )
    subsystem: str = Field(
        ...,
        description=(
            "Spacecraft subsystem this explanation relates to "
            "(e.g. 'propulsion'). Derived from composite_subsystem or dominant_variable."
        ),
    )
