"""
ATLAS — Phase 7 Copilot Q&A router.

POST /api/copilot/ask

Accepts an operator question, builds a grounded Granite prompt using the
current simulation state and knowledge context, and returns the Granite
answer.  Each question is stateless — no conversation history is maintained,
per the Phase 6 prompt design and methodology.md Section 7.

The Granite call uses the existing Phase 6 GraniteClient and
build_copilot_prompt — no AI logic is duplicated here.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.app.ai.prompts import build_copilot_prompt
from backend.app.api.models import CopilotRequest, CopilotResponse
from backend.app.api import session

router = APIRouter(prefix="/api/copilot", tags=["copilot"])

_NO_DATA_MSG = (
    "No telemetry data available. Connect to /api/telemetry/stream first."
)


@router.post("/ask", response_model=CopilotResponse)
def post_copilot_ask(body: CopilotRequest) -> CopilotResponse:
    """
    Answer an operator question using IBM Granite Copilot.

    The question is grounded in the current simulation state via the
    Phase 6 prompt builder.  Whitespace-only questions are rejected with
    a 400 before any Granite call is made.  Granite failure returns the
    Phase 6 fallback message — the endpoint always returns 200 when state
    is available and the question is valid.

    Returns:
        200 with CopilotResponse.
        400 if question is empty or whitespace-only.
        503 if no ticks have been processed yet.
    """
    # Whitespace-only check: Pydantic accepts "  " (min_length=1 passes for
    # a single space), so we validate semantic emptiness in the handler.
    if not body.question.strip():
        raise HTTPException(
            status_code=400,
            detail="Question must not be empty or whitespace-only.",
        )

    record, analytics, risk = session.get_state_snapshot()

    if analytics is None or risk is None:
        raise HTTPException(status_code=503, detail=_NO_DATA_MSG)

    # Knowledge context for the most relevant subsystem
    subsystem = analytics.composite_subsystem or "propulsion"
    knowledge = session.knowledge_loader.load(subsystem, session.mission_context)

    prompt = build_copilot_prompt(
        question=body.question,
        analytics_result=analytics,
        risk_result=risk,
        mission_context=session.mission_context,
        knowledge_context=knowledge,
    )
    answer = session.granite_client.answer_copilot(prompt)

    return CopilotResponse(answer=answer)
