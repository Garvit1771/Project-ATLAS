"""
ATLAS — Risk input normalizations.

All five normalizations defined in docs/methodology.md Section 4.
Each function is pure (no side effects, no I/O) and deterministic.
These are the building blocks consumed by engine.py.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from backend.app.models.analytics import Severity


# ── Severity mapping (methodology.md Section 4) ───────────────────────────────

_SEVERITY_NORMALIZED: dict[Severity, float] = {
    Severity.NONE:     0.0,
    Severity.LOW:      0.25,
    Severity.MODERATE: 0.5,
    Severity.HIGH:     0.75,
    Severity.CRITICAL: 1.0,
}


def severity_normalized(severity: Severity) -> float:
    """
    Map a Severity enum to its normalized [0.0–1.0] value.
    Defined in methodology.md Section 4 — severity_normalized table.
    """
    return _SEVERITY_NORMALIZED[severity]


# ── Trend rate normalization ──────────────────────────────────────────────────

def trend_rate_normalized(
    regression_slope: Optional[float],
    delta_max: float,
) -> float:
    """
    trend_rate_normalized = min(1.0, |regression_slope| / delta_max)

    Uses the regression slope (units/tick) from Phase 3 feature engineering.
    Returns 0.0 when slope is None (cold-start or flat signal).

    delta_max is the variable's delta_max_per_tick from data/normal_ranges.json.
    Defined in methodology.md Section 4.
    """
    if regression_slope is None or delta_max <= 0.0:
        return 0.0
    return min(1.0, abs(regression_slope) / delta_max)


# ── Correlation count normalization ──────────────────────────────────────────

def correlation_count_normalized(correlated_signal_count: int) -> float:
    """
    correlation_count_normalized = min(1.0, correlated_signal_count / 3)

    Uses the correlated_signals count from the Phase 3 AnalyticsResult.
    Defined in methodology.md Section 4.
    """
    return min(1.0, correlated_signal_count / 3.0)


# ── Time pressure factor ──────────────────────────────────────────────────────

def time_pressure_factor(
    next_maneuver_time: Optional[datetime],
    current_time: datetime,
) -> float:
    """
    minutes_to_next_event = (next_maneuver_time - current_time).total_seconds() / 60
    time_pressure_factor  = max(0.0, 1.0 - (minutes_to_next_event / 60))

    Reaches 1.0 when the next maneuver is ≤ 0 minutes away.
    Reaches 0.0 when ≥ 60 minutes away.
    Returns 0.0 when no maneuver time is set (mission context unknown).

    Defined in methodology.md Section 4.
    """
    if next_maneuver_time is None:
        return 0.0
    delta_seconds = (next_maneuver_time - current_time).total_seconds()
    minutes_remaining = delta_seconds / 60.0
    return max(0.0, 1.0 - (minutes_remaining / 60.0))


# ── Redundancy factor ─────────────────────────────────────────────────────────

def redundancy_factor(redundancy_available: bool) -> float:
    """
    redundancy_factor = 1.0 if no_redundant_system_available else 0.3

    Reads the redundancy_available flag from MissionContext.
    Defined in methodology.md Section 4.
    """
    return 0.3 if redundancy_available else 1.0


# ── Composite weighted score ──────────────────────────────────────────────────

def weighted_risk_score(
    *,
    w_severity:    float,
    w_trend:       float,
    w_correlation: float,
    w_time:        float,
    w_redundancy:  float,
    sev_norm:      float,
    trend_norm:    float,
    corr_norm:     float,
    time_factor:   float,
    redund_factor: float,
) -> float:
    """
    risk_score = (
        w_severity    * severity_normalized
      + w_trend       * trend_rate_normalized
      + w_correlation * correlation_count_normalized
      + w_time        * time_pressure_factor
      + w_redundancy  * redundancy_factor
    )

    Result is clamped to [0.0, 1.0] as a defensive measure.
    Defined in methodology.md Section 4.
    """
    score = (
        w_severity    * sev_norm
      + w_trend       * trend_norm
      + w_correlation * corr_norm
      + w_time        * time_factor
      + w_redundancy  * redund_factor
    )
    return max(0.0, min(1.0, score))
