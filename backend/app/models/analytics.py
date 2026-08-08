"""
ATLAS — Analytics output models.

These models represent the outputs of the three-layer anomaly detection cascade
defined in docs/methodology.md Sections 2 and 3. No detection logic is implemented
here — these are data containers only.
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# ── Enumerations ──────────────────────────────────────────────────────────────

class Severity(str, Enum):
    """Anomaly severity levels. Maps to severity_normalized in the risk formula."""
    NONE     = "NONE"
    LOW      = "LOW"
    MODERATE = "MODERATE"
    HIGH     = "HIGH"
    CRITICAL = "CRITICAL"


class DetectionMethod(str, Enum):
    """Which detection layer produced this result (methodology.md Section 2)."""
    HARD_THRESHOLD       = "hard_threshold"
    ROLLING_ZSCORE       = "rolling_zscore"
    ZSCORE_CORRELATION   = "rolling_zscore+correlation"


class ConfidenceBand(str, Enum):
    """Qualitative confidence band displayed in the UI (methodology.md Section 3).
    Raw numeric confidence is available in AnomalyDetection.confidence_value.
    The UI must show the band only, never the raw decimal.
    """
    HIGH     = "HIGH"      # confidence_value >= 0.85
    MODERATE = "MODERATE"  # 0.65 <= confidence_value < 0.85
    LOW      = "LOW"       # confidence_value < 0.65


class TrendDirection(str, Enum):
    """Trend direction derived from linear regression slope sign."""
    RISING  = "rising"
    FALLING = "falling"
    FLAT    = "flat"


# ── Detection result for a single signal ─────────────────────────────────────

class AnomalyDetection(BaseModel):
    """
    Result of the anomaly detection cascade for one telemetry variable.
    Produced by the analytics engine; consumed by the risk engine and AI layer.
    Source tag: COMPUTED.
    """

    variable: str = Field(
        ..., description="Telemetry variable name (e.g. 'thruster_2_vibration_hz')"
    )
    subsystem: str = Field(
        ..., description="Subsystem this variable belongs to (e.g. 'propulsion')"
    )
    anomaly_detected: bool = Field(
        ..., description="True if any detection layer flagged this variable"
    )
    severity: Severity = Field(
        ..., description="Severity level from the detection cascade"
    )
    detection_method: Optional[DetectionMethod] = Field(
        None, description="Which layer produced the flag; None if no anomaly"
    )
    z_score: Optional[float] = Field(
        None, description="Computed z-score at detection time; None for hard_threshold"
    )
    confidence_value: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description=(
            "Raw numeric confidence [0.0–1.0] derived from the detection method. "
            "Derived via methodology.md Section 3 formula. "
            "UI must display confidence_band only, not this value."
        ),
    )
    confidence_band: Optional[ConfidenceBand] = Field(
        None, description="Qualitative confidence band for UI display"
    )
    trend_direction: Optional[TrendDirection] = Field(
        None, description="Trend derived from regression slope sign"
    )
    regression_slope: Optional[float] = Field(
        None,
        description=(
            "Linear regression slope over the rolling window (units/tick). "
            "Used for trend_rate_normalized in the risk formula."
        ),
    )
    first_anomaly_tick: Optional[int] = Field(
        None,
        description=(
            "Tick at which this variable first crossed the anomaly threshold "
            "in the current event. Used by Layer 3 correlation window check."
        ),
    )
    evidence: list[str] = Field(
        default_factory=list,
        description=(
            "Human-readable evidence statements injected into the Granite prompt. "
            "Each entry is traceable to a specific computation."
        ),
    )

    model_config = {"frozen": True}


# ── Aggregate analytics result ────────────────────────────────────────────────

class AnalyticsResult(BaseModel):
    """
    Aggregated output of the analytics engine for one telemetry tick.
    Contains per-signal detections plus the composite correlation result.
    Source tag: COMPUTED.
    """

    tick: int = Field(..., ge=0, description="Tick this result corresponds to")
    detections: list[AnomalyDetection] = Field(
        default_factory=list,
        description="Per-signal anomaly detection results (anomaly_detected=True only)",
    )
    composite_anomaly: bool = Field(
        False,
        description="True when Layer 3 correlation rule fires across ≥2 signals",
    )
    composite_subsystem: Optional[str] = Field(
        None,
        description="Subsystem in which the composite anomaly was detected",
    )
    composite_severity: Optional[Severity] = Field(
        None,
        description=(
            "Severity of the composite anomaly: escalated one level above "
            "the highest individual severity among correlated signals"
        ),
    )
    composite_confidence_value: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Numeric confidence of the composite anomaly",
    )
    composite_confidence_band: Optional[ConfidenceBand] = Field(
        None,
        description="Qualitative confidence band of the composite anomaly for UI display",
    )
    correlated_signals: list[str] = Field(
        default_factory=list,
        description="Variable names that contributed to the composite anomaly",
    )

    model_config = {"frozen": True}
