"""
ATLAS — Phase 7 decision support router.

GET  /api/decision/options  — ranked decision options (deterministic)
POST /api/decision/whatif   — what-if re-scoring + Granite narrative

The router is an integration layer:
  - DecisionEngine.evaluate()  produces all deterministic scores.
  - DecisionEngine.what_if()   computes the projected risk delta.
  - GraniteClient.narrate_decision() produces the AI narrative.

No formula logic lives here.  The Granite call happens after the
deterministic result is computed; a Granite failure never prevents
the deterministic result from being returned.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.app.ai.prompts import build_decision_prompt
from backend.app.api.models import WhatIfRequest, WhatIfResponse
from backend.app.models.decision import DecisionResult
from backend.app.api import session

router = APIRouter(prefix="/api/decision", tags=["decision"])

_NO_DATA_MSG = (
    "No telemetry data available. Connect to /api/telemetry/stream first."
)


@router.get("/options", response_model=DecisionResult)
def get_decision_options() -> DecisionResult:
    """
    Return all ranked decision options for the current simulation state.

    Options are sorted ascending by computed_risk_score_after (lowest
    projected risk first).  This ranking is fully deterministic; Granite
    is not called here.

    Returns 503 if no ticks have been processed yet.
    """
    record, analytics, risk = session.get_state_snapshot()

    if analytics is None or risk is None:
        raise HTTPException(status_code=503, detail=_NO_DATA_MSG)

    return session.decision_engine.evaluate(
        analytics_result=analytics,
        risk_result=risk,
        mission_context=session.mission_context,
        current_record=record,
    )


@router.post("/whatif", response_model=WhatIfResponse)
def post_whatif(body: WhatIfRequest) -> WhatIfResponse:
    """
    Evaluate a single decision option via the what-if re-scoring engine
    and return a Granite narrative explaining the projected risk delta.

    The deterministic WhatIfResult is always computed first.  Granite is
    called after; if Granite is unavailable the existing Phase 6 fallback
    message is returned in ai_narrative — the deterministic result is
    unaffected.

    Returns:
        200 with WhatIfResponse on success.
        400 if option_id is not recognised by the current scenario.
        503 if no ticks have been processed yet.
    """
    record, analytics, risk = session.get_state_snapshot()

    if analytics is None or risk is None:
        raise HTTPException(status_code=503, detail=_NO_DATA_MSG)

    # Deterministic what-if re-scoring (raises KeyError for unknown option)
    try:
        what_if_result = session.decision_engine.what_if(
            option_id=body.option_id,
            analytics_result=analytics,
            risk_result=risk,
            mission_context=session.mission_context,
            current_record=record,
        )
    except KeyError as exc:
        # DecisionEngine.what_if raises KeyError with a clear message including
        # the available option ids — surface that directly.
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Build full decision result for the Granite prompt context
    decision_result = session.decision_engine.evaluate(
        analytics_result=analytics,
        risk_result=risk,
        mission_context=session.mission_context,
        current_record=record,
    )

    # Knowledge context for the subsystem currently anomalous (if any)
    subsystem = analytics.composite_subsystem or "propulsion"
    knowledge = session.knowledge_loader.load(subsystem, session.mission_context)

    # Granite narrative — falls back gracefully if unavailable
    prompt = build_decision_prompt(
        decision_result=decision_result,
        analytics_result=analytics,
        risk_result=risk,
        mission_context=session.mission_context,
        knowledge_context=knowledge,
    )
    ai_narrative = session.granite_client.narrate_decision(prompt)

    return WhatIfResponse(what_if=what_if_result, ai_narrative=ai_narrative)
