"""
ATLAS — Decision engine output models.

Represents the runtime outputs of the Decision Support Engine as defined in
docs/methodology.md Section 5 and docs/architecture.md Section 3.2.

Key naming conventions (enforced here):
  computed_risk_score_after  — runtime formula output (COMPUTED source tag)
  risk_score_after_target    — scenario config validation value; NOT in this model

Source tags: COMPUTED for scores; MISSION PARAMS for fuel/time from scenario config.
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# ── Enumerations ──────────────────────────────────────────────────────────────

class RecommendationStrength(str, Enum):
    """
    Deterministic recommendation strength derived from computed_risk_score_after.
    Mapping (methodology.md Section 5):
      STRONG   — computed_risk_score_after < 0.30
      MODERATE — 0.30 <= computed_risk_score_after <= 0.60
      WEAK     — computed_risk_score_after > 0.60
    """
    STRONG   = "STRONG"
    MODERATE = "MODERATE"
    WEAK     = "WEAK"


class SourceTag(str, Enum):
    """
    Source tags for all values displayed in the frontend (methodology.md Section 8).
    Every displayed value must carry exactly one of these tags.
    """
    COMPUTED       = "COMPUTED"
    MISSION_PARAMS = "MISSION PARAMS"
    AI_EXPLANATION = "AI EXPLANATION"
    OPERATOR       = "OPERATOR"


# ── Per-option result ─────────────────────────────────────────────────────────

class DecisionOption(BaseModel):
    """
    Runtime output for one candidate decision option.
    Produced by the Decision Engine after what-if re-scoring.

    IMPORTANT: risk_score_after_target from the scenario config file is
    intentionally absent from this model — it is a Phase 5 test fixture only,
    not a runtime field (methodology.md Section 5).
    """

    option_id: str = Field(
        ..., description="Scenario config key (e.g. 'SWITCH_REDUNDANT')"
    )
    label: str = Field(
        ..., description="Short human-readable option label for UI display"
    )
    description: str = Field(
        ..., description="Full description of the action this option takes"
    )

    # ── Computed by the what-if formula ───────────────────────────────────────
    computed_risk_score_after: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "Risk score projected after applying this option, computed by "
            "re-running the risk formula on the hypothetical state. "
            "Source tag: COMPUTED."
        ),
    )
    recommendation_strength: RecommendationStrength = Field(
        ...,
        description=(
            "Deterministic strength derived from computed_risk_score_after. "
            "Source tag: COMPUTED."
        ),
    )

    # ── From scenario config (mission parameters) ─────────────────────────────
    fuel_cost_pct: float = Field(
        ...,
        ge=0.0,
        description="Estimated additional fuel consumption (%). Source tag: MISSION PARAMS.",
    )
    time_delay_min: float = Field(
        ...,
        ge=0.0,
        description="Estimated mission timeline delay (minutes). Source tag: MISSION PARAMS.",
    )
    mission_constraint_satisfied: bool = Field(
        ...,
        description=(
            "Whether this option keeps the spacecraft within mission constraints "
            "(e.g. orbital insertion window). Source tag: MISSION PARAMS."
        ),
    )
    subsystem_stress: list[str] = Field(
        default_factory=list,
        description="Subsystems that will be under increased stress if this option is taken.",
    )

    model_config = {"frozen": True}


# ── Ranked decision result ────────────────────────────────────────────────────

class DecisionResult(BaseModel):
    """
    Full output of the Decision Engine for one decision event.
    Options are pre-ranked by computed_risk_score_after ascending before
    being passed to the AI reasoning layer.
    Source tag: COMPUTED (scores); MISSION PARAMS (fuel/time).
    """

    tick: int = Field(..., ge=0, description="Tick this decision result corresponds to")
    options: list[DecisionOption] = Field(
        ...,
        description=(
            "Candidate options ranked by computed_risk_score_after ascending. "
            "Granite receives this pre-ranked list and explains the tradeoffs only."
        ),
    )
    current_risk_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Risk score before any action is taken. Source tag: COMPUTED.",
    )
    fault_type: Optional[str] = Field(
        None,
        description="Scenario fault type key used to look up option configs",
    )
    mission_phase: Optional[str] = Field(
        None,
        description="Mission phase at the time of the decision event",
    )

    model_config = {"frozen": True}


# ── What-if result ────────────────────────────────────────────────────────────

class WhatIfResult(BaseModel):
    """
    Output of a what-if re-scoring for a specific option.
    Returned by the what-if endpoint; explained by Granite in natural language.
    Source tag: COMPUTED.
    """

    option_id: str = Field(..., description="The option that was evaluated")
    current_risk: float = Field(..., ge=0.0, le=1.0, description="Risk before the action")
    projected_risk: float = Field(..., ge=0.0, le=1.0, description="Risk after the action")
    delta: float = Field(
        ...,
        description=(
            "Risk change: projected_risk - current_risk. "
            "Negative value means risk reduction."
        ),
    )

    model_config = {"frozen": True}
