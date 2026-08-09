"""
ATLAS — Risk Engine.

Produces a RiskResult from an AnalyticsResult + MissionContext by applying
the deterministic weighted formula defined in docs/methodology.md Section 4.

Design:
  - All numerical inputs come from Phase 3 AnalyticsResult and MissionContext.
  - Weights are loaded from data/normal_ranges.json (not hard-coded).
  - No scenario-specific values are hard-coded.
  - IBM Granite never touches these calculations.
  - Given identical inputs, the output is always identical.

Usage:
    engine = RiskEngine()
    risk = engine.compute(analytics_result, mission_context, current_record)
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from backend.app.models.analytics import (
    AnalyticsResult,
    AnomalyDetection,
    Severity,
)
from backend.app.models.mission import MissionContext
from backend.app.models.risk import RiskResult
from backend.app.models.telemetry import TelemetryRecord
from backend.app.risk.scoring import (
    severity_normalized,
    trend_rate_normalized,
    correlation_count_normalized,
    time_pressure_factor,
    redundancy_factor,
    weighted_risk_score,
)
from backend.app.risk.threshold import best_breach_estimate


# ── Config loader ─────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[3]
_NORMAL_RANGES_PATH = _REPO_ROOT / "data" / "normal_ranges.json"


def _load_config() -> dict:
    with _NORMAL_RANGES_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


_CONFIG = _load_config()
_VAR_CFG: dict[str, dict] = _CONFIG["variables"]
_WEIGHTS: dict[str, float] = _CONFIG["risk_weights"]


# ── Severity ordering (for dominant-variable selection) ───────────────────────

_SEV_ORDER = [
    Severity.NONE,
    Severity.LOW,
    Severity.MODERATE,
    Severity.HIGH,
    Severity.CRITICAL,
]


def _sev_rank(s: Severity) -> int:
    return _SEV_ORDER.index(s)


# ── Risk Engine ───────────────────────────────────────────────────────────────

class RiskEngine:
    """
    Stateless risk engine.  All state is provided by the caller.

    Accepts:
        analytics_result — Phase 3 output for the current tick
        mission_context  — live mission state (phase, timing, redundancy)
        current_record   — the TelemetryRecord for this tick
                           (used to extract current_values for breach estimation)

    Returns a RiskResult containing the computed risk_score and supporting fields.
    """

    def compute(
        self,
        analytics_result: AnalyticsResult,
        mission_context: MissionContext,
        current_record: TelemetryRecord,
    ) -> RiskResult:
        """
        Compute the deterministic risk score for one tick.
        """
        tick = analytics_result.tick

        # ── 1. Determine dominant severity ────────────────────────────────────
        dominant_sev, dominant_var = self._dominant_severity(analytics_result)

        # ── 2. severity_normalized ─────────────────────────────────────────
        sev_norm = severity_normalized(dominant_sev)

        # ── 3. trend_rate_normalized ───────────────────────────────────────
        # Use the regression_slope of the dominant anomalous variable.
        # If no anomaly, slope is 0 → trend contribution is 0.
        trend_norm = self._best_trend_norm(analytics_result)

        # ── 4. correlation_count_normalized ───────────────────────────────
        n_correlated = len(analytics_result.correlated_signals)
        corr_norm = correlation_count_normalized(n_correlated)

        # ── 5. time_pressure_factor ────────────────────────────────────────
        current_time = current_record.timestamp
        time_factor = time_pressure_factor(
            next_maneuver_time=mission_context.next_maneuver_time,
            current_time=current_time,
        )

        # ── 6. redundancy_factor ───────────────────────────────────────────
        redund_factor = redundancy_factor(mission_context.redundancy_available)

        # ── 7. Composite weighted score ────────────────────────────────────
        score = weighted_risk_score(
            w_severity=_WEIGHTS["w_severity"],
            w_trend=_WEIGHTS["w_trend"],
            w_correlation=_WEIGHTS["w_correlation"],
            w_time=_WEIGHTS["w_time"],
            w_redundancy=_WEIGHTS["w_redundancy"],
            sev_norm=sev_norm,
            trend_norm=trend_norm,
            corr_norm=corr_norm,
            time_factor=time_factor,
            redund_factor=redund_factor,
        )

        # ── 8. Threshold breach estimate ───────────────────────────────────
        current_values = self._extract_current_values(current_record)
        breach_minutes, breach_var = best_breach_estimate(
            detections=analytics_result.detections,
            variable_configs=_VAR_CFG,
            current_values=current_values,
        )

        return RiskResult(
            tick=tick,
            risk_score=score,
            severity=dominant_sev,
            estimated_threshold_breach_minutes=breach_minutes,
            dominant_variable=dominant_var,
            redundancy_available=mission_context.redundancy_available,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _dominant_severity(
        self,
        analytics_result: AnalyticsResult,
    ) -> tuple[Severity, Optional[str]]:
        """
        Return the highest severity from all active detections.
        If Layer 3 composite fired, use composite_severity.
        Otherwise use the max individual severity.
        """
        # Composite anomaly takes precedence for severity
        if analytics_result.composite_anomaly and analytics_result.composite_severity:
            # Also identify the dominant variable (highest individual severity)
            dom_var = self._dominant_detection_var(analytics_result.detections)
            return analytics_result.composite_severity, dom_var

        if not analytics_result.detections:
            return Severity.NONE, None

        dom_det = max(analytics_result.detections, key=lambda d: _sev_rank(d.severity))
        return dom_det.severity, dom_det.variable

    def _dominant_detection_var(
        self,
        detections: list[AnomalyDetection],
    ) -> Optional[str]:
        """Return the variable name with the highest individual severity."""
        if not detections:
            return None
        return max(detections, key=lambda d: _sev_rank(d.severity)).variable

    def _best_trend_norm(self, analytics_result: AnalyticsResult) -> float:
        """
        Compute trend_rate_normalized for the most severely trending variable.

        For each anomalous detection, compute trend_rate_normalized using
        the detection's regression_slope and the variable's delta_max_per_tick.
        Return the maximum across all detections.

        If no detections, return 0.0.
        """
        if not analytics_result.detections:
            return 0.0

        best = 0.0
        for det in analytics_result.detections:
            var_cfg = _VAR_CFG.get(det.variable)
            if var_cfg is None:
                continue
            delta_max = var_cfg["delta_max_per_tick"]
            norm = trend_rate_normalized(det.regression_slope, delta_max)
            if norm > best:
                best = norm
        return best

    @staticmethod
    def _extract_current_values(record: TelemetryRecord) -> dict[str, float]:
        """Extract the 13 telemetry field values as a flat dict."""
        return {
            var: float(getattr(record, var))
            for var in [
                "battery_voltage_v", "battery_temp_c", "solar_power_w",
                "cpu_temp_c", "cpu_load_pct",
                "thruster_1_temp_c", "thruster_2_temp_c",
                "thruster_2_vibration_hz", "thruster_2_efficiency_pct",
                "attitude_error_deg",
                "signal_strength_dbm", "packet_loss_pct",
                "radiation_level_mgy",
            ]
        }
