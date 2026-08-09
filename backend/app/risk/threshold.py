"""
ATLAS — Threshold breach estimation.

Implements the time-to-breach formula from docs/methodology.md Section 4.
Given a Phase 3 detection, computes how many minutes until the trending
variable is projected to reach its operating envelope boundary.

Pure functions only — no I/O, no state.
"""

from __future__ import annotations

from typing import Optional

from backend.app.models.analytics import AnomalyDetection, TrendDirection


def estimated_breach_minutes(
    detection: AnomalyDetection,
    current_value: float,
    v_min: float,
    v_max: float,
) -> Optional[float]:
    """
    Estimate minutes until the variable reaches its relevant threshold.

    if regression_slope != 0:
        v_threshold = v_max  if slope > 0  (signal rising toward upper limit)
                    = v_min  if slope < 0  (signal falling toward lower limit)
        distance = v_threshold - current_value    (signed)
        estimated_ticks   = abs(distance / regression_slope)
        estimated_minutes = estimated_ticks / 60
    else:
        return None  (no detectable trend)

    Returns None if:
      - regression_slope is None or zero
      - trend_direction is FLAT or None
      - the signal is already past the threshold (distance <= 0 in the
        direction of travel) — in that case we return 0.0 to indicate
        breach is imminent/already occurred
    """
    slope = detection.regression_slope
    direction = detection.trend_direction

    if slope is None or direction is None or direction == TrendDirection.FLAT:
        return None
    if abs(slope) < 1e-12:
        return None

    # Choose the boundary the signal is trending toward
    if slope > 0:
        v_threshold = v_max
    else:
        v_threshold = v_min

    distance = v_threshold - current_value  # signed

    # If already at or beyond the threshold in direction of travel
    if slope > 0 and distance <= 0:
        return 0.0
    if slope < 0 and distance >= 0:
        return 0.0

    estimated_ticks = abs(distance / slope)
    return estimated_ticks / 60.0


def best_breach_estimate(
    detections: list[AnomalyDetection],
    variable_configs: dict[str, dict],
    current_values: dict[str, float],
) -> tuple[Optional[float], Optional[str]]:
    """
    Given a list of anomaly detections, return the shortest estimated
    breach time and the variable it belongs to.

    Returns (None, None) if no variable has a trending anomaly.
    Returns (0.0, variable) if any variable is already at or past threshold.
    """
    best_minutes: Optional[float] = None
    best_var: Optional[str] = None

    for det in detections:
        if not det.anomaly_detected:
            continue
        var = det.variable
        cfg = variable_configs.get(var)
        if cfg is None:
            continue
        current_val = current_values.get(var)
        if current_val is None:
            continue

        minutes = estimated_breach_minutes(
            detection=det,
            current_value=current_val,
            v_min=cfg["min"],
            v_max=cfg["max"],
        )
        if minutes is not None:
            if best_minutes is None or minutes < best_minutes:
                best_minutes = minutes
                best_var = var

    return best_minutes, best_var
