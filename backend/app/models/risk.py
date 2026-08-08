"""
ATLAS — Risk engine output model.

Represents the output of the weighted composite risk formula defined in
docs/methodology.md Section 4. No formula logic is implemented here.
Source tag: COMPUTED.
"""

from typing import Optional
from pydantic import BaseModel, Field

from backend.app.models.analytics import Severity


class RiskResult(BaseModel):
    """
    Output of the risk engine for one telemetry tick.
    All values are produced by the deterministic weighted formula.
    IBM Granite never produces or modifies these values.
    Source tag: COMPUTED.
    """

    tick: int = Field(..., ge=0, description="Tick this result corresponds to")
    risk_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "Composite risk score [0.0–1.0] computed by the weighted formula "
            "in methodology.md Section 4"
        ),
    )
    severity: Severity = Field(
        ...,
        description=(
            "Overall severity level derived from the dominant anomaly "
            "contributing to the risk score"
        ),
    )
    estimated_threshold_breach_minutes: Optional[float] = Field(
        None,
        ge=0.0,
        description=(
            "Estimated minutes until the trending variable reaches its "
            "operating envelope limit. None if no variable is trending "
            "toward a threshold (regression_slope == 0)."
        ),
    )
    dominant_variable: Optional[str] = Field(
        None,
        description=(
            "The telemetry variable with the highest contribution to the "
            "current risk score; used for evidence injection"
        ),
    )
    redundancy_available: bool = Field(
        True,
        description=(
            "Whether a redundant system is available. "
            "Affects redundancy_factor in the risk formula."
        ),
    )

    model_config = {"frozen": True}
