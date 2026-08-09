"""
ATLAS — Feature engineering.

Computes per-variable statistical features from a rolling buffer of
TelemetryRecord instances. All formulas are defined in methodology.md Section 1.

Features produced per variable:
  rolling_mean      — mean over last w ticks
  rolling_std       — std  over last w ticks (ddof=1; returns 0.0 if < 2 samples)
  z_score           — (current - mean) / std  (None until MIN_TICKS in buffer)
  delta             — current - previous      (None if only 1 record in buffer)
  regression_slope  — linear regression slope (units/tick) over last w ticks
  trend_direction   — sign of regression_slope: RISING / FALLING / FLAT

The cold-start guard: z_score is None when fewer than MIN_TICKS=10 records are
in the buffer, and regression_slope is None when fewer than 2 records exist.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Optional

import numpy as np

from backend.app.models.analytics import TrendDirection
from backend.app.models.telemetry import TelemetryRecord


# ── Constants ─────────────────────────────────────────────────────────────────

ROLLING_WINDOW: int = 60    # default w — configurable, matches normal_ranges.json
MIN_TICKS: int = 10         # cold-start guard for z-score
FLAT_SLOPE_THRESHOLD: float = 1e-6  # slopes smaller than this are treated as flat


# ── Feature result dataclass ──────────────────────────────────────────────────

@dataclass(frozen=True)
class VariableFeatures:
    """
    Computed features for a single telemetry variable at one tick.
    All values are derived from the rolling buffer; none are invented.
    """
    variable: str
    current_value: float
    rolling_mean: float
    rolling_std: float
    z_score: Optional[float]          # None during cold-start (< MIN_TICKS)
    delta: Optional[float]            # None if only 1 record in buffer
    regression_slope: Optional[float] # None if < 2 records in buffer
    trend_direction: Optional[TrendDirection]  # None if regression_slope is None


# ── Feature engineering functions ────────────────────────────────────────────

def _telemetry_var_names() -> list[str]:
    """Return the 13 telemetry variable names in a stable order."""
    return [
        "battery_voltage_v", "battery_temp_c", "solar_power_w",
        "cpu_temp_c", "cpu_load_pct",
        "thruster_1_temp_c", "thruster_2_temp_c",
        "thruster_2_vibration_hz", "thruster_2_efficiency_pct",
        "attitude_error_deg",
        "signal_strength_dbm", "packet_loss_pct",
        "radiation_level_mgy",
    ]


def compute_features(
    buffer: deque[TelemetryRecord],
    window: int = ROLLING_WINDOW,
) -> dict[str, VariableFeatures]:
    """
    Compute features for all 13 telemetry variables from the current buffer.

    Parameters
    ----------
    buffer : deque of TelemetryRecord, ordered oldest-first.
             Caller is responsible for maintaining the buffer at ≤ N=300 records.
    window : rolling window width w (default 60 ticks).

    Returns
    -------
    Dict mapping variable name → VariableFeatures.
    """
    if not buffer:
        raise ValueError("Buffer must contain at least one TelemetryRecord.")

    records = list(buffer)
    n = len(records)

    # Use the last `window` records for rolling computations
    window_records = records[-min(n, window):]
    w = len(window_records)

    # Build per-variable arrays from the window
    arrays: dict[str, np.ndarray] = {}
    for var in _telemetry_var_names():
        arrays[var] = np.array([getattr(r, var) for r in window_records], dtype=float)

    current = records[-1]
    previous = records[-2] if n >= 2 else None

    result: dict[str, VariableFeatures] = {}
    x = np.arange(w, dtype=float)  # tick indices for regression (relative)

    for var in _telemetry_var_names():
        vals = arrays[var]
        current_val = float(getattr(current, var))

        # Rolling mean and std
        rmean = float(np.mean(vals))
        rstd = float(np.std(vals, ddof=1)) if w >= 2 else 0.0

        # Z-score: requires MIN_TICKS records and non-zero std
        z: Optional[float] = None
        if n >= MIN_TICKS and rstd > 0.0:
            z = (current_val - rmean) / rstd

        # Delta: signed one-tick change
        delta: Optional[float] = None
        if previous is not None:
            delta = current_val - float(getattr(previous, var))

        # Regression slope over the window
        slope: Optional[float] = None
        direction: Optional[TrendDirection] = None
        if w >= 2:
            # numpy.polyfit returns [slope, intercept]
            coeffs = np.polyfit(x, vals, 1)
            slope = float(coeffs[0])
            if abs(slope) < FLAT_SLOPE_THRESHOLD:
                direction = TrendDirection.FLAT
            elif slope > 0:
                direction = TrendDirection.RISING
            else:
                direction = TrendDirection.FALLING

        result[var] = VariableFeatures(
            variable=var,
            current_value=current_val,
            rolling_mean=rmean,
            rolling_std=rstd,
            z_score=z,
            delta=delta,
            regression_slope=slope,
            trend_direction=direction,
        )

    return result
