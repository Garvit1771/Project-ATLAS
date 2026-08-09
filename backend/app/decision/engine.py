"""
ATLAS — Decision Support Engine.

Implements deterministic option scoring, ranking, and what-if risk re-scoring
as defined in docs/methodology.md Sections 5 and 6.

Design principles:
  - IBM Granite does NOT participate in this module.  All outputs are numerical
    and deterministic.  Granite calls happen at the API layer AFTER this engine.
  - computed_risk_score_after is produced by re-running RiskEngine.compute() on a
    modified hypothetical AnalyticsResult + MissionContext.  It is NEVER read from
    the scenario config (risk_score_after_target is test-validation only).
  - HARD_THRESHOLD detections (z_score is None) are handled by applying the
    numeric delta to the actual current telemetry value and re-checking the
    envelope boundary.  They are NEVER treated as resolved merely because
    z_score is None.
  - Boolean state changes are applied to separate copies of AnalyticsResult and
    MissionContext; originals are never mutated.

Usage:
    engine = DecisionEngine(scenario)
    decision = engine.evaluate(analytics_result, risk_result, mission_context, record)
    what_if  = engine.what_if("REDUCE_LOAD", analytics_result, risk_result,
                               mission_context, record)
"""

from __future__ import annotations

import json
from dataclasses import replace as dc_replace
from pathlib import Path
from typing import Optional

from backend.app.models.analytics import (
    AnalyticsResult,
    AnomalyDetection,
    ConfidenceBand,
    DetectionMethod,
    Severity,
)
from backend.app.models.decision import (
    DecisionOption,
    DecisionResult,
    RecommendationStrength,
    WhatIfResult,
)
from backend.app.models.mission import MissionContext
from backend.app.models.risk import RiskResult
from backend.app.models.telemetry import TelemetryRecord
from backend.app.risk.engine import RiskEngine
from backend.app.simulation.scenarios import DecisionOptionConfig, ScenarioConfig


# ── Load variable config once at import time ──────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[3]
_NORMAL_RANGES_PATH = _REPO_ROOT / "data" / "normal_ranges.json"


def _load_var_cfg() -> dict[str, dict]:
    with _NORMAL_RANGES_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)["variables"]


_VAR_CFG: dict[str, dict] = _load_var_cfg()

# Variables owned by Thruster 2 — deactivated together when thruster_2_active=False
_THRUSTER_2_VARS = frozenset({
    "thruster_2_vibration_hz",
    "thruster_2_temp_c",
    "thruster_2_efficiency_pct",
})


# ── Recommendation strength (methodology.md Section 5) ────────────────────────

def _recommendation_strength(score: float) -> RecommendationStrength:
    """
    Derive recommendation strength from computed_risk_score_after.
      < 0.30        → STRONG
      0.30 – 0.60   → MODERATE
      > 0.60        → WEAK
    """
    if score < 0.30:
        return RecommendationStrength.STRONG
    elif score <= 0.60:
        return RecommendationStrength.MODERATE
    else:
        return RecommendationStrength.WEAK


# ── Hypothetical state construction ───────────────────────────────────────────

def _apply_action_to_analytics(
    analytics: AnalyticsResult,
    current_record: TelemetryRecord,
    numeric_state_deltas: dict[str, float],
    boolean_state_changes: dict[str, bool],
) -> AnalyticsResult:
    """
    Build a hypothetical AnalyticsResult that reflects the effect of one decision
    option.  The original is never mutated.

    Steps:
      1. For each detection, apply any numeric delta:
           - HARD_THRESHOLD detections: apply delta to the actual current telemetry
             value; keep or clear the breach based on whether the hypothetical value
             still falls outside [v_min, v_max].
           - Z-SCORE detections: reduce z-score magnitude proportionally to the
             delta size relative to the envelope range; re-derive severity and
             confidence; clear if new |z| drops to or below Z_THRESHOLD.
      2. Apply boolean state changes:
           - thruster_2_active=False: remove all _THRUSTER_2_VARS from detections
             and correlated_signals.
      3. Rebuild composite anomaly fields from the surviving detections/correlated.

    Returns a new AnalyticsResult (frozen Pydantic model).
    """
    # Fast-path: nothing to do
    if not numeric_state_deltas and not boolean_state_changes:
        return analytics

    from backend.app.analytics.detector import (
        Z_THRESHOLD,
        _severity_from_z,
        _z_confidence,
        _confidence_band,
    )

    # ── Step 1 — apply numeric deltas to existing detections ──────────────────
    new_detections: list[AnomalyDetection] = []

    for det in analytics.detections:
        delta = numeric_state_deltas.get(det.variable)

        if delta is None:
            # No delta for this variable — detection unchanged
            new_detections.append(det)
            continue

        cfg = _VAR_CFG.get(det.variable)
        if cfg is None:
            new_detections.append(det)
            continue

        v_min: float = cfg["min"]
        v_max: float = cfg["max"]

        if det.detection_method == DetectionMethod.HARD_THRESHOLD:
            # ── Hard-threshold branch ─────────────────────────────────────
            # z_score is None for hard-threshold detections.
            # We MUST NOT treat None as 0.0.  Instead, evaluate the
            # hypothetical value against the envelope directly.
            current_val = float(getattr(current_record, det.variable))
            hypo_val = current_val + delta

            if hypo_val < v_min or hypo_val > v_max:
                # Still breaching — detection remains CRITICAL
                new_detections.append(det)
            else:
                # Delta brings value back inside envelope — breach resolved
                # Detection is dropped (not added to new_detections)
                pass

        else:
            # ── Z-score branch ────────────────────────────────────────────
            # z_score is a real number here.
            if det.z_score is None:
                # Defensive: z_score should not be None for non-hard-threshold,
                # but treat as unchanged if so.
                new_detections.append(det)
                continue

            envelope_range = v_max - v_min
            if envelope_range <= 0.0:
                new_detections.append(det)
                continue

            # Delta reduces anomaly if it opposes the regression slope direction.
            # Reduction fraction = |delta| / (envelope_range / 2), capped at 1.0.
            slope = det.regression_slope or 0.0
            delta_opposes = (delta != 0.0) and ((delta * slope) < 0.0)

            if not delta_opposes:
                # Delta goes with the anomaly direction or is neutral — unchanged
                new_detections.append(det)
                continue

            reduction = min(1.0, abs(delta) / (envelope_range * 0.5))
            new_z = det.z_score * (1.0 - reduction)
            new_z_abs = abs(new_z)

            if new_z_abs <= Z_THRESHOLD:
                # Anomaly resolved — drop this detection entirely
                pass
            else:
                # Still anomalous at reduced magnitude — rebuild detection
                new_sev = _severity_from_z(new_z_abs)
                new_conf = _z_confidence(new_z_abs)
                new_band = _confidence_band(new_conf)
                new_det = AnomalyDetection(
                    variable=det.variable,
                    subsystem=det.subsystem,
                    anomaly_detected=True,
                    severity=new_sev,
                    detection_method=det.detection_method,
                    z_score=new_z,
                    confidence_value=new_conf,
                    confidence_band=new_band,
                    trend_direction=det.trend_direction,
                    regression_slope=det.regression_slope,
                    first_anomaly_tick=det.first_anomaly_tick,
                    evidence=det.evidence,
                )
                new_detections.append(new_det)

    # ── Step 2 — apply boolean state changes ──────────────────────────────────
    if boolean_state_changes.get("thruster_2_active") is False:
        # Remove all Thruster 2 variables entirely from the hypothetical state
        new_detections = [
            d for d in new_detections
            if d.variable not in _THRUSTER_2_VARS
        ]

    # ── Step 3 — rebuild composite fields ─────────────────────────────────────
    surviving_vars = {d.variable for d in new_detections}
    new_correlated = [v for v in analytics.correlated_signals if v in surviving_vars]

    if len(new_correlated) >= 2:
        # Composite anomaly survives with its original fields
        new_composite_anomaly = analytics.composite_anomaly
        new_composite_subsystem = analytics.composite_subsystem
        new_composite_severity = analytics.composite_severity
        new_composite_conf_value = analytics.composite_confidence_value
        new_composite_conf_band = analytics.composite_confidence_band
    else:
        # Too few correlated signals remain — composite dissolves
        new_composite_anomaly = False
        new_composite_subsystem = None
        new_composite_severity = None
        new_composite_conf_value = None
        new_composite_conf_band = None
        new_correlated = []

    return AnalyticsResult(
        tick=analytics.tick,
        detections=new_detections,
        composite_anomaly=new_composite_anomaly,
        composite_subsystem=new_composite_subsystem,
        composite_severity=new_composite_severity,
        composite_confidence_value=new_composite_conf_value,
        composite_confidence_band=new_composite_conf_band,
        correlated_signals=new_correlated,
    )


def _apply_action_to_mission(
    mission: MissionContext,
    boolean_state_changes: dict[str, bool],
) -> MissionContext:
    """
    Build a hypothetical MissionContext copy reflecting the boolean state changes.
    The original is never mutated.

    Handles:
      thruster_2_active: False  → sets thruster_2_active=False on the copy
      thruster_3_active: True   → sets thruster_3_active=True; redundancy stays True
    """
    if not boolean_state_changes:
        return mission  # no changes — return the original unchanged

    new_t2 = mission.thruster_2_active
    new_t3 = mission.thruster_3_active
    new_redundancy = mission.redundancy_available

    if boolean_state_changes.get("thruster_2_active") is False:
        new_t2 = False

    if boolean_state_changes.get("thruster_3_active") is True:
        new_t3 = True
        # Thruster 3 is now active.  Thruster 1 remains available, so redundancy
        # is still True (the spacecraft has operational propulsion).
        new_redundancy = True

    return MissionContext(
        mission_name=mission.mission_name,
        mission_type=mission.mission_type,
        phase=mission.phase,
        next_maneuver_time=mission.next_maneuver_time,
        abort_window_minutes=mission.abort_window_minutes,
        thruster_1_active=mission.thruster_1_active,
        thruster_2_active=new_t2,
        thruster_3_active=new_t3,
        redundancy_available=new_redundancy,
        constraints=list(mission.constraints),
        scenario_id=mission.scenario_id,
    )


# ── What-if scoring ────────────────────────────────────────────────────────────

def _score_option(
    option_cfg: DecisionOptionConfig,
    analytics: AnalyticsResult,
    mission: MissionContext,
    current_record: TelemetryRecord,
    risk_engine: RiskEngine,
) -> float:
    """
    Re-run the risk formula on the hypothetical state produced by one option.

    Procedure (methodology.md Section 6):
      1. Apply numeric_state_deltas to produce a hypothetical AnalyticsResult.
      2. Apply boolean_state_changes to produce a hypothetical MissionContext.
      3. Run RiskEngine.compute() on the hypothetical state.
      4. Return the resulting risk_score.

    Neither the original AnalyticsResult nor the MissionContext is mutated.
    """
    hypo_analytics = _apply_action_to_analytics(
        analytics=analytics,
        current_record=current_record,
        numeric_state_deltas=option_cfg.numeric_state_deltas,
        boolean_state_changes=option_cfg.boolean_state_changes,
    )
    hypo_mission = _apply_action_to_mission(
        mission=mission,
        boolean_state_changes=option_cfg.boolean_state_changes,
    )
    risk_result = risk_engine.compute(
        analytics_result=hypo_analytics,
        mission_context=hypo_mission,
        current_record=current_record,
    )
    return risk_result.risk_score


# ── Decision Engine ────────────────────────────────────────────────────────────

class DecisionEngine:
    """
    Deterministic decision support engine.

    Evaluates all candidate options for a scenario and returns a ranked
    DecisionResult.  IBM Granite is not involved in any step here.

    Args:
        scenario: the loaded ScenarioConfig for the active scenario.
    """

    def __init__(self, scenario: ScenarioConfig) -> None:
        self._scenario = scenario
        self._risk_engine = RiskEngine()

    # ── Public interface ───────────────────────────────────────────────────────

    def evaluate(
        self,
        analytics_result: AnalyticsResult,
        risk_result: RiskResult,
        mission_context: MissionContext,
        current_record: TelemetryRecord,
    ) -> DecisionResult:
        """
        Evaluate all scenario options and return a ranked DecisionResult.

        Args:
            analytics_result — Phase 3 output for the current tick
            risk_result      — Phase 4 output (current risk score)
            mission_context  — live mission state
            current_record   — the TelemetryRecord for this tick

        Returns:
            DecisionResult with options sorted ascending by computed_risk_score_after.
        """
        options: list[DecisionOption] = []

        for option_id, opt_cfg in self._scenario.options.items():
            projected = _score_option(
                option_cfg=opt_cfg,
                analytics=analytics_result,
                mission=mission_context,
                current_record=current_record,
                risk_engine=self._risk_engine,
            )
            strength = _recommendation_strength(projected)

            options.append(DecisionOption(
                option_id=option_id,
                label=opt_cfg.label,
                description=opt_cfg.description,
                computed_risk_score_after=projected,
                recommendation_strength=strength,
                fuel_cost_pct=opt_cfg.fuel_cost_pct,
                time_delay_min=opt_cfg.time_delay_min,
                mission_constraint_satisfied=opt_cfg.mission_constraint_satisfied,
                subsystem_stress=opt_cfg.subsystem_stress,
            ))

        # Rank ascending by projected risk (lowest first)
        options.sort(key=lambda o: o.computed_risk_score_after)

        return DecisionResult(
            tick=analytics_result.tick,
            options=options,
            current_risk_score=risk_result.risk_score,
            fault_type=self._scenario.scenario_id,
            mission_phase=mission_context.phase,
        )

    def what_if(
        self,
        option_id: str,
        analytics_result: AnalyticsResult,
        risk_result: RiskResult,
        mission_context: MissionContext,
        current_record: TelemetryRecord,
    ) -> WhatIfResult:
        """
        Evaluate a single option and return a WhatIfResult.

        Args:
            option_id — must match a key in the scenario's options dict

        Returns:
            WhatIfResult(option_id, current_risk, projected_risk, delta)
            where delta = projected_risk - current_risk  (negative = risk reduction).

        Raises:
            KeyError if option_id is not found in the scenario.
        """
        opt_cfg = self._scenario.options.get(option_id)
        if opt_cfg is None:
            available = list(self._scenario.options.keys())
            raise KeyError(
                f"Option '{option_id}' not found in scenario "
                f"'{self._scenario.scenario_id}'. Available: {available}"
            )

        projected = _score_option(
            option_cfg=opt_cfg,
            analytics=analytics_result,
            mission=mission_context,
            current_record=current_record,
            risk_engine=self._risk_engine,
        )
        current = risk_result.risk_score
        delta = projected - current

        return WhatIfResult(
            option_id=option_id,
            current_risk=current,
            projected_risk=projected,
            delta=delta,
        )
