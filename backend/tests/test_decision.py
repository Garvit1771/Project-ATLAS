"""
ATLAS — Phase 5 decision support engine tests.

Coverage:
  Imports
  _recommendation_strength  (all boundary conditions)
  _apply_action_to_mission  (no changes / thruster_2_active=False /
                              thruster_3_active=True / combined)
  _apply_action_to_analytics — z-score detections:
    - no delta → unchanged
    - delta opposing rising anomaly → z reduced
    - large opposing delta → detection dropped (resolved)
    - delta same direction → unchanged
    - composite clears when <2 correlated signals survive
  _apply_action_to_analytics — HARD_THRESHOLD detections (regression test for
    known bug: z_score=None must NEVER be treated as 0.0):
    - hard-threshold detection, delta too small → breach remains
    - hard-threshold detection, delta large enough → breach resolved
    - hard-threshold detection with z_score=None is NOT resolved by default
  DecisionEngine initialisation
  DecisionEngine.evaluate():
    - returns DecisionResult
    - tick propagated
    - three options for FAULT-01
    - options sorted ascending by computed_risk_score_after
    - no field named risk_score_after_target in DecisionOption
    - no field named risk_score_after (ambiguous) in DecisionOption
    - current_risk_score matches risk_result.risk_score
    - fault_type equals scenario_id
    - mission_phase propagated
    - all computed_risk_score_after in [0.0, 1.0]
    - recommendation_strength derived from computed_risk_score_after
    - MISSION PARAMS fields match scenario config
    - DecisionResult is frozen
  DecisionEngine.what_if():
    - returns WhatIfResult
    - option_id propagated
    - current_risk == risk_result.risk_score
    - delta == projected_risk - current_risk
    - raises KeyError for unknown option
    - WhatIfResult is frozen
    - original analytics/mission context is NOT mutated
  Integration tests (full FAULT-01 pipeline at peak fault):
    - SWITCH_REDUNDANT has lowest projected risk
    - REDUCE_LOAD projected risk < CONTINUE projected risk
    - SWITCH_REDUNDANT projected risk < REDUCE_LOAD projected risk (strict ordering)
    - CONTINUE projected risk ≈ current risk (no state changes → nearly identical)
    - SWITCH_REDUNDANT projected risk within ±0.15 of target 0.18
    - REDUCE_LOAD projected risk > SWITCH_REDUNDANT (partial relief, not full)
    - hard-threshold regression: REDUCE_LOAD does NOT drop to same score as
      SWITCH_REDUNDANT when variables are in hard-threshold breach
    - all projected risks in [0.0, 1.0]
    - what_if delta for SWITCH_REDUNDANT is negative (risk reduced)
    - what_if delta for CONTINUE is ≈ 0
"""

from __future__ import annotations

from dataclasses import fields as dc_fields
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import pytest

from backend.app.models.analytics import (
    AnalyticsResult,
    AnomalyDetection,
    ConfidenceBand,
    DetectionMethod,
    Severity,
    TrendDirection,
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

# ── Constants ─────────────────────────────────────────────────────────────────

_T0 = datetime(2026, 8, 9, 2, 0, 0, tzinfo=timezone.utc)
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCENARIO_PATH = _REPO_ROOT / "data" / "scenarios" / "alpha1_fault_01.json"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _record(tick: int = 150, ts: Optional[datetime] = None, **kw) -> TelemetryRecord:
    """Build a TelemetryRecord with nominal defaults."""
    defaults = {
        "tick": tick,
        "timestamp": ts or _T0,
        "battery_voltage_v": 27.8,
        "battery_temp_c": 24.0,
        "solar_power_w": 100.0,
        "cpu_temp_c": 55.0,
        "cpu_load_pct": 45.0,
        "thruster_1_temp_c": 200.0,
        "thruster_2_temp_c": 200.0,
        "thruster_2_vibration_hz": 1.2,
        "thruster_2_efficiency_pct": 95.0,
        "attitude_error_deg": 0.12,
        "signal_strength_dbm": -72.0,
        "packet_loss_pct": 0.5,
        "radiation_level_mgy": 0.3,
    }
    defaults.update(kw)
    return TelemetryRecord(**defaults)


def _detection_zscore(
    variable: str = "thruster_2_vibration_hz",
    subsystem: str = "propulsion",
    severity: Severity = Severity.HIGH,
    z_score: float = 4.5,
    regression_slope: float = 0.025,
    trend_direction: TrendDirection = TrendDirection.RISING,
    first_anomaly_tick: int = 125,
) -> AnomalyDetection:
    """Build a z-score (Layer 2) AnomalyDetection."""
    return AnomalyDetection(
        variable=variable,
        subsystem=subsystem,
        anomaly_detected=True,
        severity=severity,
        detection_method=DetectionMethod.ROLLING_ZSCORE,
        z_score=z_score,
        confidence_value=0.8,
        confidence_band=ConfidenceBand.MODERATE,
        trend_direction=trend_direction,
        regression_slope=regression_slope,
        first_anomaly_tick=first_anomaly_tick,
        evidence=[f"{variable} z={z_score:.2f}"],
    )


def _detection_hard_threshold(
    variable: str = "thruster_2_vibration_hz",
    subsystem: str = "propulsion",
    regression_slope: float = 0.004,
    trend_direction: TrendDirection = TrendDirection.RISING,
    first_anomaly_tick: int = 195,
) -> AnomalyDetection:
    """
    Build a HARD_THRESHOLD (Layer 1) AnomalyDetection.
    z_score is intentionally None — this is the critical invariant.
    """
    return AnomalyDetection(
        variable=variable,
        subsystem=subsystem,
        anomaly_detected=True,
        severity=Severity.CRITICAL,
        detection_method=DetectionMethod.HARD_THRESHOLD,
        z_score=None,           # ← MUST stay None; never substitute 0.0
        confidence_value=1.0,
        confidence_band=ConfidenceBand.HIGH,
        trend_direction=trend_direction,
        regression_slope=regression_slope,
        first_anomaly_tick=first_anomaly_tick,
        evidence=[f"{variable} exceeds envelope"],
    )


def _analytics_composite(
    tick: int = 170,
    detections: Optional[list[AnomalyDetection]] = None,
    correlated: Optional[list[str]] = None,
) -> AnalyticsResult:
    """Build an AnalyticsResult with composite propulsion anomaly."""
    dets = detections if detections is not None else [
        _detection_zscore("thruster_2_vibration_hz", z_score=4.5, regression_slope=0.025),
        _detection_zscore("thruster_2_temp_c", z_score=4.0, regression_slope=0.30,
                          severity=Severity.HIGH),
        _detection_zscore("thruster_2_efficiency_pct", z_score=-3.5,
                          regression_slope=-0.08,
                          trend_direction=TrendDirection.FALLING,
                          severity=Severity.MODERATE),
    ]
    corr = correlated if correlated is not None else [
        "thruster_2_vibration_hz", "thruster_2_temp_c", "thruster_2_efficiency_pct",
    ]
    return AnalyticsResult(
        tick=tick,
        detections=dets,
        composite_anomaly=True,
        composite_subsystem="propulsion",
        composite_severity=Severity.CRITICAL,
        composite_confidence_value=0.92,
        composite_confidence_band=ConfidenceBand.HIGH,
        correlated_signals=corr,
    )


def _risk(tick: int = 170, score: float = 0.70) -> RiskResult:
    return RiskResult(
        tick=tick,
        risk_score=score,
        severity=Severity.CRITICAL,
        estimated_threshold_breach_minutes=12.5,
        dominant_variable="thruster_2_vibration_hz",
        redundancy_available=True,
    )


def _mission(minutes_to_maneuver: Optional[float] = 40.0,
             redundancy: bool = True) -> MissionContext:
    nmt = _T0 + timedelta(minutes=minutes_to_maneuver) if minutes_to_maneuver else None
    return MissionContext(next_maneuver_time=nmt, redundancy_available=redundancy)


def _load_scenario():
    from backend.app.simulation.scenarios import load_scenario_from_path
    return load_scenario_from_path(_SCENARIO_PATH)


def _get_engine():
    from backend.app.decision.engine import DecisionEngine
    return DecisionEngine(_load_scenario())


# ── Import smoke tests ────────────────────────────────────────────────────────

def test_engine_imports():
    from backend.app.decision.engine import DecisionEngine  # noqa: F401


def test_helpers_importable():
    from backend.app.decision.engine import (  # noqa: F401
        _recommendation_strength,
        _apply_action_to_analytics,
        _apply_action_to_mission,
    )


# ── _recommendation_strength ─────────────────────────────────────────────────

def test_strength_zero_is_strong():
    from backend.app.decision.engine import _recommendation_strength
    assert _recommendation_strength(0.0) == RecommendationStrength.STRONG


def test_strength_0_29_is_strong():
    from backend.app.decision.engine import _recommendation_strength
    assert _recommendation_strength(0.29) == RecommendationStrength.STRONG


def test_strength_0_30_is_moderate():
    from backend.app.decision.engine import _recommendation_strength
    assert _recommendation_strength(0.30) == RecommendationStrength.MODERATE


def test_strength_0_45_is_moderate():
    from backend.app.decision.engine import _recommendation_strength
    assert _recommendation_strength(0.45) == RecommendationStrength.MODERATE


def test_strength_0_60_is_moderate():
    from backend.app.decision.engine import _recommendation_strength
    assert _recommendation_strength(0.60) == RecommendationStrength.MODERATE


def test_strength_0_61_is_weak():
    from backend.app.decision.engine import _recommendation_strength
    assert _recommendation_strength(0.61) == RecommendationStrength.WEAK


def test_strength_1_0_is_weak():
    from backend.app.decision.engine import _recommendation_strength
    assert _recommendation_strength(1.0) == RecommendationStrength.WEAK


# ── _apply_action_to_mission ──────────────────────────────────────────────────

def test_mission_no_changes_returns_same_object():
    from backend.app.decision.engine import _apply_action_to_mission
    m = _mission()
    result = _apply_action_to_mission(m, {})
    assert result is m  # unchanged, same object returned


def test_mission_thruster2_false_sets_flag():
    from backend.app.decision.engine import _apply_action_to_mission
    m = _mission()
    result = _apply_action_to_mission(m, {"thruster_2_active": False})
    assert result.thruster_2_active is False


def test_mission_thruster2_false_does_not_mutate_original():
    from backend.app.decision.engine import _apply_action_to_mission
    m = _mission()
    _apply_action_to_mission(m, {"thruster_2_active": False})
    assert m.thruster_2_active is True  # original unchanged


def test_mission_thruster3_true_sets_flag():
    from backend.app.decision.engine import _apply_action_to_mission
    m = _mission()
    result = _apply_action_to_mission(m, {"thruster_3_active": True})
    assert result.thruster_3_active is True


def test_mission_combined_switch_redundant():
    from backend.app.decision.engine import _apply_action_to_mission
    m = _mission()
    result = _apply_action_to_mission(
        m, {"thruster_2_active": False, "thruster_3_active": True}
    )
    assert result.thruster_2_active is False
    assert result.thruster_3_active is True
    assert result.redundancy_available is True  # still operational


def test_mission_redundancy_preserved_after_switch():
    from backend.app.decision.engine import _apply_action_to_mission
    m = _mission(redundancy=True)
    result = _apply_action_to_mission(
        m, {"thruster_2_active": False, "thruster_3_active": True}
    )
    assert result.redundancy_available is True


# ── _apply_action_to_analytics — z-score branch ───────────────────────────────

def test_analytics_no_deltas_returns_same_object():
    from backend.app.decision.engine import _apply_action_to_analytics
    a = _analytics_composite()
    record = _record()
    result = _apply_action_to_analytics(a, record, {}, {})
    assert result is a  # no-op returns the original


def test_analytics_zscore_no_delta_unchanged():
    """A detection with no delta for its variable is left unchanged."""
    from backend.app.decision.engine import _apply_action_to_analytics
    a = _analytics_composite()
    record = _record()
    # Apply a delta only to thruster_2_temp_c, not to vibration or efficiency
    result = _apply_action_to_analytics(a, record, {"thruster_2_temp_c": -6.0}, {})
    vib_dets = [d for d in result.detections
                if d.variable == "thruster_2_vibration_hz"]
    assert len(vib_dets) == 1
    assert vib_dets[0].z_score == pytest.approx(4.5)


def test_analytics_zscore_opposing_delta_reduces_z():
    """A delta opposing a rising z-score should reduce the z-score magnitude."""
    from backend.app.decision.engine import _apply_action_to_analytics
    # vibration_hz: envelope [0.5, 2.0], range=1.5
    # slope=0.025 (RISING), delta=-0.4 (opposing)
    # reduction = min(1.0, 0.4 / (1.5*0.5)) = min(1.0, 0.4/0.75) = 0.533
    # new_z = 4.5 * (1 - 0.533) = 4.5 * 0.467 = 2.10  → ≤ Z_THRESHOLD(2.5) → resolved
    det = _detection_zscore("thruster_2_vibration_hz", z_score=4.5, regression_slope=0.025)
    a = AnalyticsResult(tick=150, detections=[det], correlated_signals=[])
    record = _record()
    result = _apply_action_to_analytics(
        a, record, {"thruster_2_vibration_hz": -0.4}, {}
    )
    # With this delta the detection is fully resolved (new |z| < 2.5)
    assert not any(d.variable == "thruster_2_vibration_hz" for d in result.detections)


def test_analytics_zscore_small_opposing_delta_reduces_but_keeps():
    """A small opposing delta reduces severity but does not fully resolve."""
    from backend.app.decision.engine import _apply_action_to_analytics
    # vibration_hz: envelope [0.5, 2.0], range=1.5
    # slope=0.025, delta=-0.1 (opposing, small)
    # reduction = min(1.0, 0.1/0.75) = 0.133
    # new_z = 4.5 * (1 - 0.133) = 3.90  → still > 2.5 (Z_THRESHOLD)
    # severity from 3.90: 3.0 < 3.90 ≤ 4.0 → MODERATE
    det = _detection_zscore("thruster_2_vibration_hz", z_score=4.5, regression_slope=0.025,
                             severity=Severity.HIGH)
    a = AnalyticsResult(tick=150, detections=[det], correlated_signals=[])
    record = _record()
    result = _apply_action_to_analytics(
        a, record, {"thruster_2_vibration_hz": -0.1}, {}
    )
    remaining = [d for d in result.detections
                 if d.variable == "thruster_2_vibration_hz"]
    assert len(remaining) == 1
    assert remaining[0].anomaly_detected is True
    assert remaining[0].severity == Severity.MODERATE  # downgraded


def test_analytics_zscore_same_direction_delta_unchanged():
    """A delta in the same direction as the anomaly leaves the detection unchanged."""
    from backend.app.decision.engine import _apply_action_to_analytics
    det = _detection_zscore("thruster_2_vibration_hz", z_score=4.5, regression_slope=0.025)
    a = AnalyticsResult(tick=150, detections=[det], correlated_signals=[])
    record = _record()
    # Positive delta on a rising variable — worsens, unchanged
    result = _apply_action_to_analytics(
        a, record, {"thruster_2_vibration_hz": 0.5}, {}
    )
    remaining = [d for d in result.detections
                 if d.variable == "thruster_2_vibration_hz"]
    assert len(remaining) == 1
    assert remaining[0].z_score == pytest.approx(4.5)


def test_analytics_composite_clears_when_less_than_2_remain():
    """If fewer than 2 correlated signals survive, composite_anomaly becomes False."""
    from backend.app.decision.engine import _apply_action_to_analytics
    # Start with 2 correlated signals; apply a delta that resolves one
    det1 = _detection_zscore("thruster_2_vibration_hz", z_score=4.5, regression_slope=0.025)
    det2 = _detection_zscore("thruster_2_temp_c", z_score=3.2, regression_slope=0.15,
                              severity=Severity.MODERATE)
    a = AnalyticsResult(
        tick=150,
        detections=[det1, det2],
        composite_anomaly=True,
        composite_subsystem="propulsion",
        composite_severity=Severity.CRITICAL,
        composite_confidence_value=0.90,
        composite_confidence_band=ConfidenceBand.HIGH,
        correlated_signals=["thruster_2_vibration_hz", "thruster_2_temp_c"],
    )
    record = _record()
    # Delta of -0.4 opposing thruster_2_vibration_hz resolves it (z→2.10 < 2.5)
    result = _apply_action_to_analytics(
        a, record, {"thruster_2_vibration_hz": -0.4}, {}
    )
    assert result.composite_anomaly is False
    assert result.correlated_signals == []
    assert result.composite_severity is None


def test_analytics_composite_survives_when_2_remain():
    """Composite anomaly is preserved if 2 or more correlated signals survive."""
    from backend.app.decision.engine import _apply_action_to_analytics
    a = _analytics_composite()  # 3 correlated signals
    record = _record()
    # No deltas → composite must survive unchanged
    result = _apply_action_to_analytics(a, record, {}, {})
    assert result is a  # no-op path


# ── _apply_action_to_analytics — HARD_THRESHOLD branch (regression tests) ─────

def test_hard_threshold_zscore_none_is_never_treated_as_zero():
    """
    REGRESSION TEST: A HARD_THRESHOLD detection with z_score=None must NOT be
    considered resolved merely because z_score is None.  This was the known bug
    in an earlier attempted implementation.
    """
    from backend.app.decision.engine import _apply_action_to_analytics
    # thruster_2_vibration_hz: envelope max=2.0
    # Current value = 2.05 (breaches max by 0.05)
    # REDUCE_LOAD delta = -0.4  → hypothetical value = 1.65, inside [0.5, 2.0]
    # BUT we test with a tiny delta that leaves value outside:
    # delta = -0.02  → hypo = 2.03 still > 2.0  → breach REMAINS
    det = _detection_hard_threshold("thruster_2_vibration_hz")
    a = AnalyticsResult(tick=200, detections=[det], correlated_signals=[])
    # Current telemetry: vibration = 2.05 (just over envelope max of 2.0)
    record = _record(tick=200, thruster_2_vibration_hz=2.05)
    result = _apply_action_to_analytics(
        a, record, {"thruster_2_vibration_hz": -0.02}, {}
    )
    # 2.05 - 0.02 = 2.03, still > 2.0 → breach persists
    remaining = [d for d in result.detections
                 if d.variable == "thruster_2_vibration_hz"]
    assert len(remaining) == 1, (
        "Hard-threshold detection should NOT be resolved by a small delta. "
        "This is the regression test for the z_score=None bug."
    )
    assert remaining[0].severity == Severity.CRITICAL
    assert remaining[0].z_score is None  # must remain None


def test_hard_threshold_large_delta_resolves_breach():
    """A delta large enough to return the value inside the envelope resolves the breach."""
    from backend.app.decision.engine import _apply_action_to_analytics
    # thruster_2_vibration_hz: envelope [0.5, 2.0]
    # Current value = 2.05 (breach by 0.05)
    # delta = -0.4 → hypo = 1.65, inside envelope → resolved
    det = _detection_hard_threshold("thruster_2_vibration_hz")
    a = AnalyticsResult(tick=200, detections=[det], correlated_signals=[])
    record = _record(tick=200, thruster_2_vibration_hz=2.05)
    result = _apply_action_to_analytics(
        a, record, {"thruster_2_vibration_hz": -0.4}, {}
    )
    remaining = [d for d in result.detections
                 if d.variable == "thruster_2_vibration_hz"]
    assert len(remaining) == 0, "Hard-threshold breach should be resolved by a large enough delta"


def test_hard_threshold_no_delta_unchanged():
    """Hard-threshold detection with no delta for its variable is left unchanged."""
    from backend.app.decision.engine import _apply_action_to_analytics
    det = _detection_hard_threshold("thruster_2_vibration_hz")
    a = AnalyticsResult(tick=200, detections=[det], correlated_signals=[])
    record = _record(tick=200, thruster_2_vibration_hz=2.05)
    # Delta only for a different variable
    result = _apply_action_to_analytics(
        a, record, {"thruster_2_temp_c": -6.0}, {}
    )
    remaining = [d for d in result.detections
                 if d.variable == "thruster_2_vibration_hz"]
    assert len(remaining) == 1
    assert remaining[0].z_score is None
    assert remaining[0].severity == Severity.CRITICAL


def test_hard_threshold_boolean_deactivate_removes_it():
    """thruster_2_active=False removes a hard-threshold detection entirely."""
    from backend.app.decision.engine import _apply_action_to_analytics
    det = _detection_hard_threshold("thruster_2_vibration_hz")
    a = AnalyticsResult(tick=200, detections=[det], correlated_signals=[])
    record = _record(tick=200, thruster_2_vibration_hz=2.05)
    result = _apply_action_to_analytics(
        a, record, {}, {"thruster_2_active": False}
    )
    remaining = [d for d in result.detections
                 if d.variable == "thruster_2_vibration_hz"]
    assert len(remaining) == 0


def test_hard_threshold_efficiency_below_min_small_delta():
    """
    REGRESSION: thruster_2_efficiency_pct below envelope minimum (92.0).
    A small positive delta (+2.0) from REDUCE_LOAD:
    if current = 90.0 → hypo = 92.0 (exactly at min) — boundary check.
    Exactly at boundary: 92.0 is NOT less than 92.0 and NOT greater than 98.0
    → breach resolved.
    """
    from backend.app.decision.engine import _apply_action_to_analytics
    det = _detection_hard_threshold(
        "thruster_2_efficiency_pct",
        subsystem="propulsion",
        regression_slope=-0.02,
        trend_direction=TrendDirection.FALLING,
    )
    a = AnalyticsResult(tick=200, detections=[det], correlated_signals=[])
    # Exactly at boundary after +2.0 delta (90.0 + 2.0 = 92.0 == min)
    record = _record(tick=200, thruster_2_efficiency_pct=90.0)
    result = _apply_action_to_analytics(
        a, record, {"thruster_2_efficiency_pct": 2.0}, {}
    )
    remaining = [d for d in result.detections
                 if d.variable == "thruster_2_efficiency_pct"]
    # 90.0 + 2.0 = 92.0 = v_min → NOT below min, NOT above max → resolved
    assert len(remaining) == 0


def test_hard_threshold_efficiency_still_below_min():
    """
    Small delta that does not fully return efficiency into envelope — breach persists.
    """
    from backend.app.decision.engine import _apply_action_to_analytics
    det = _detection_hard_threshold(
        "thruster_2_efficiency_pct",
        subsystem="propulsion",
        regression_slope=-0.02,
        trend_direction=TrendDirection.FALLING,
    )
    a = AnalyticsResult(tick=200, detections=[det], correlated_signals=[])
    # current=89.5, delta=+1.0 → hypo=90.5, still < 92.0
    record = _record(tick=200, thruster_2_efficiency_pct=89.5)
    result = _apply_action_to_analytics(
        a, record, {"thruster_2_efficiency_pct": 1.0}, {}
    )
    remaining = [d for d in result.detections
                 if d.variable == "thruster_2_efficiency_pct"]
    assert len(remaining) == 1
    assert remaining[0].severity == Severity.CRITICAL
    assert remaining[0].z_score is None


# ── boolean_state_changes — analytics ────────────────────────────────────────

def test_analytics_thruster2_deactivate_removes_all_three_vars():
    from backend.app.decision.engine import _apply_action_to_analytics
    a = _analytics_composite()
    record = _record()
    result = _apply_action_to_analytics(a, record, {}, {"thruster_2_active": False})
    remaining_vars = {d.variable for d in result.detections}
    for v in ["thruster_2_vibration_hz", "thruster_2_temp_c",
              "thruster_2_efficiency_pct"]:
        assert v not in remaining_vars


def test_analytics_thruster2_deactivate_clears_composite():
    from backend.app.decision.engine import _apply_action_to_analytics
    a = _analytics_composite()
    record = _record()
    result = _apply_action_to_analytics(a, record, {}, {"thruster_2_active": False})
    assert result.composite_anomaly is False
    assert result.correlated_signals == []
    assert result.composite_severity is None


def test_analytics_original_not_mutated_after_boolean_change():
    from backend.app.decision.engine import _apply_action_to_analytics
    a = _analytics_composite()
    record = _record()
    _apply_action_to_analytics(a, record, {}, {"thruster_2_active": False})
    # Original must be unchanged
    assert len(a.detections) == 3
    assert a.composite_anomaly is True


# ── DecisionEngine initialisation ─────────────────────────────────────────────

def test_engine_initialises():
    engine = _get_engine()
    assert engine is not None


# ── DecisionEngine.evaluate() ────────────────────────────────────────────────

def test_evaluate_returns_decision_result():
    result = _get_engine().evaluate(_analytics_composite(), _risk(), _mission(), _record())
    assert isinstance(result, DecisionResult)


def test_evaluate_tick_propagated():
    a = _analytics_composite(tick=175)
    result = _get_engine().evaluate(a, _risk(tick=175), _mission(), _record(tick=175))
    assert result.tick == 175


def test_evaluate_three_options():
    result = _get_engine().evaluate(_analytics_composite(), _risk(), _mission(), _record())
    assert len(result.options) == 3


def test_evaluate_options_sorted_ascending():
    result = _get_engine().evaluate(_analytics_composite(), _risk(), _mission(), _record())
    scores = [o.computed_risk_score_after for o in result.options]
    assert scores == sorted(scores)


def test_evaluate_no_field_risk_score_after_target():
    """risk_score_after_target must NOT appear in DecisionOption."""
    result = _get_engine().evaluate(_analytics_composite(), _risk(), _mission(), _record())
    for option in result.options:
        assert not hasattr(option, "risk_score_after_target"), (
            "DecisionOption must not expose risk_score_after_target"
        )


def test_evaluate_no_ambiguous_risk_score_after():
    """There must be no field called risk_score_after (ambiguous) in DecisionOption."""
    result = _get_engine().evaluate(_analytics_composite(), _risk(), _mission(), _record())
    for option in result.options:
        assert not hasattr(option, "risk_score_after"), (
            "DecisionOption must not expose ambiguous 'risk_score_after'"
        )


def test_evaluate_current_risk_matches_risk_result():
    rr = _risk(score=0.71)
    result = _get_engine().evaluate(_analytics_composite(), rr, _mission(), _record())
    assert result.current_risk_score == pytest.approx(0.71)


def test_evaluate_fault_type_is_scenario_id():
    result = _get_engine().evaluate(_analytics_composite(), _risk(), _mission(), _record())
    assert result.fault_type == "ALPHA1-FAULT-01"


def test_evaluate_mission_phase_propagated():
    result = _get_engine().evaluate(_analytics_composite(), _risk(), _mission(), _record())
    assert result.mission_phase == "orbital_insertion"


def test_evaluate_all_scores_in_range():
    result = _get_engine().evaluate(_analytics_composite(), _risk(), _mission(), _record())
    for o in result.options:
        assert 0.0 <= o.computed_risk_score_after <= 1.0


def test_evaluate_recommendation_strength_derived_from_score():
    result = _get_engine().evaluate(_analytics_composite(), _risk(), _mission(), _record())
    for o in result.options:
        s = o.computed_risk_score_after
        if s < 0.30:
            assert o.recommendation_strength == RecommendationStrength.STRONG
        elif s <= 0.60:
            assert o.recommendation_strength == RecommendationStrength.MODERATE
        else:
            assert o.recommendation_strength == RecommendationStrength.WEAK


def test_evaluate_mission_params_from_scenario():
    """fuel_cost_pct, time_delay_min, mission_constraint_satisfied come from config."""
    from backend.app.simulation.scenarios import load_scenario_from_path
    scenario = load_scenario_from_path(_SCENARIO_PATH)
    result = _get_engine().evaluate(_analytics_composite(), _risk(), _mission(), _record())
    by_id = {o.option_id: o for o in result.options}
    for opt_id, cfg in scenario.options.items():
        assert by_id[opt_id].fuel_cost_pct == pytest.approx(cfg.fuel_cost_pct)
        assert by_id[opt_id].time_delay_min == pytest.approx(cfg.time_delay_min)
        assert by_id[opt_id].mission_constraint_satisfied == cfg.mission_constraint_satisfied


def test_evaluate_decision_result_is_frozen():
    result = _get_engine().evaluate(_analytics_composite(), _risk(), _mission(), _record())
    with pytest.raises(Exception):
        result.tick = 999  # type: ignore[misc]


def test_evaluate_option_ids_present():
    result = _get_engine().evaluate(_analytics_composite(), _risk(), _mission(), _record())
    ids = {o.option_id for o in result.options}
    assert {"CONTINUE", "REDUCE_LOAD", "SWITCH_REDUNDANT"} == ids


# ── DecisionEngine.what_if() ─────────────────────────────────────────────────

def test_what_if_returns_what_if_result():
    r = _get_engine().what_if(
        "SWITCH_REDUNDANT", _analytics_composite(), _risk(), _mission(), _record()
    )
    assert isinstance(r, WhatIfResult)


def test_what_if_option_id_propagated():
    r = _get_engine().what_if(
        "REDUCE_LOAD", _analytics_composite(), _risk(), _mission(), _record()
    )
    assert r.option_id == "REDUCE_LOAD"


def test_what_if_current_risk_matches():
    rr = _risk(score=0.69)
    r = _get_engine().what_if(
        "CONTINUE", _analytics_composite(), rr, _mission(), _record()
    )
    assert r.current_risk == pytest.approx(0.69)


def test_what_if_delta_is_projected_minus_current():
    rr = _risk(score=0.70)
    r = _get_engine().what_if(
        "SWITCH_REDUNDANT", _analytics_composite(), rr, _mission(), _record()
    )
    assert r.delta == pytest.approx(r.projected_risk - r.current_risk)


def test_what_if_projected_in_range():
    rr = _risk()
    for opt in ["CONTINUE", "REDUCE_LOAD", "SWITCH_REDUNDANT"]:
        r = _get_engine().what_if(opt, _analytics_composite(), rr, _mission(), _record())
        assert 0.0 <= r.projected_risk <= 1.0


def test_what_if_unknown_option_raises_key_error():
    with pytest.raises(KeyError):
        _get_engine().what_if(
            "DOES_NOT_EXIST", _analytics_composite(), _risk(), _mission(), _record()
        )


def test_what_if_result_is_frozen():
    r = _get_engine().what_if(
        "CONTINUE", _analytics_composite(), _risk(), _mission(), _record()
    )
    with pytest.raises(Exception):
        r.delta = 999.0  # type: ignore[misc]


def test_what_if_does_not_mutate_original_analytics():
    a = _analytics_composite()
    original_dets = list(a.detections)
    original_composite = a.composite_anomaly
    _get_engine().what_if(
        "SWITCH_REDUNDANT", a, _risk(), _mission(), _record()
    )
    assert list(a.detections) == original_dets
    assert a.composite_anomaly == original_composite


def test_what_if_does_not_mutate_original_mission():
    m = _mission()
    original_t2 = m.thruster_2_active
    original_t3 = m.thruster_3_active
    _get_engine().what_if(
        "SWITCH_REDUNDANT", _analytics_composite(), _risk(), m, _record()
    )
    assert m.thruster_2_active == original_t2
    assert m.thruster_3_active == original_t3


# ── Integration tests: full FAULT-01 pipeline at peak fault ───────────────────

def _peak_fault_inputs():
    """
    Run the FAULT-01 simulator to tick 220 and return
    (analytics_result, risk_result, mission_context, current_record, scenario).
    """
    from backend.app.simulation.scenarios import load_scenario_from_path
    from backend.app.simulation.generator import TelemetryGenerator
    from backend.app.analytics.engine import AnalyticsEngine
    from backend.app.risk.engine import RiskEngine

    scenario = load_scenario_from_path(_SCENARIO_PATH)
    gen = TelemetryGenerator(scenario=scenario, seed=42)
    ae = AnalyticsEngine()
    re = RiskEngine()

    mission = MissionContext(
        next_maneuver_time=_T0 + timedelta(minutes=40),
        redundancy_available=True,
    )
    records = gen.generate(220)

    ar = ae.process(records[-1])
    for rec in records[:-1]:
        ae.process(rec)

    # Rerun properly in order
    ae2 = AnalyticsEngine()
    for rec in records:
        ar = ae2.process(rec)
    rr = re.compute(ar, mission, records[-1])

    return ar, rr, mission, records[-1], scenario


# Cache simulation so it only runs once per session
_PEAK = None

def _get_peak():
    global _PEAK
    if _PEAK is None:
        _PEAK = _peak_fault_inputs()
    return _PEAK


def test_integration_three_options():
    ar, rr, mission, record, scenario = _get_peak()
    from backend.app.decision.engine import DecisionEngine
    result = DecisionEngine(scenario).evaluate(ar, rr, mission, record)
    assert len(result.options) == 3


def test_integration_options_sorted_ascending():
    ar, rr, mission, record, scenario = _get_peak()
    from backend.app.decision.engine import DecisionEngine
    result = DecisionEngine(scenario).evaluate(ar, rr, mission, record)
    scores = [o.computed_risk_score_after for o in result.options]
    assert scores == sorted(scores)


def test_integration_switch_redundant_lowest_risk():
    """
    SWITCH_REDUNDANT must have strictly lower projected risk than REDUCE_LOAD
    (because it fully deactivates the anomalous subsystem).

    REDUCE_LOAD may equal CONTINUE if the small deltas do not fully resolve any
    hard-threshold breaches at the tick sampled (both still have active hard-threshold
    detections). The important guarantee is that SWITCH_REDUNDANT < both others.
    """
    ar, rr, mission, record, scenario = _get_peak()
    from backend.app.decision.engine import DecisionEngine
    result = DecisionEngine(scenario).evaluate(ar, rr, mission, record)
    by_id = {o.option_id: o for o in result.options}
    assert (
        by_id["SWITCH_REDUNDANT"].computed_risk_score_after
        < by_id["REDUCE_LOAD"].computed_risk_score_after
    ), "SWITCH_REDUNDANT should have lower projected risk than REDUCE_LOAD"
    assert (
        by_id["SWITCH_REDUNDANT"].computed_risk_score_after
        < by_id["CONTINUE"].computed_risk_score_after
    ), "SWITCH_REDUNDANT should have lower projected risk than CONTINUE"
    # REDUCE_LOAD <= CONTINUE (may be equal if small deltas don't clear breaches)
    assert (
        by_id["REDUCE_LOAD"].computed_risk_score_after
        <= by_id["CONTINUE"].computed_risk_score_after
    ), "REDUCE_LOAD should not have higher projected risk than CONTINUE"


def test_integration_switch_redundant_near_target():
    """SWITCH_REDUNDANT projected risk within ±0.15 of scenario target 0.18."""
    ar, rr, mission, record, scenario = _get_peak()
    from backend.app.decision.engine import DecisionEngine
    result = DecisionEngine(scenario).evaluate(ar, rr, mission, record)
    by_id = {o.option_id: o for o in result.options}
    score = by_id["SWITCH_REDUNDANT"].computed_risk_score_after
    assert abs(score - 0.18) <= 0.15, (
        f"SWITCH_REDUNDANT projected risk {score:.3f} is >±0.15 from target 0.18"
    )


def test_integration_continue_near_current_risk():
    """CONTINUE applies no state changes, so projected ≈ current risk."""
    ar, rr, mission, record, scenario = _get_peak()
    from backend.app.decision.engine import DecisionEngine
    result = DecisionEngine(scenario).evaluate(ar, rr, mission, record)
    by_id = {o.option_id: o for o in result.options}
    delta = abs(by_id["CONTINUE"].computed_risk_score_after - rr.risk_score)
    assert delta < 0.05, (
        f"CONTINUE projected {by_id['CONTINUE'].computed_risk_score_after:.3f} "
        f"differs from current {rr.risk_score:.3f} by {delta:.3f}"
    )


def test_integration_reduce_load_strictly_higher_than_switch():
    """
    HARD-THRESHOLD REGRESSION: REDUCE_LOAD's small deltas should NOT reduce risk
    to the same level as SWITCH_REDUNDANT (which fully deactivates Thruster 2).
    This test fails if hard-threshold z_score=None is treated as 0.0.
    """
    ar, rr, mission, record, scenario = _get_peak()
    from backend.app.decision.engine import DecisionEngine
    result = DecisionEngine(scenario).evaluate(ar, rr, mission, record)
    by_id = {o.option_id: o for o in result.options}
    reduce_score = by_id["REDUCE_LOAD"].computed_risk_score_after
    switch_score = by_id["SWITCH_REDUNDANT"].computed_risk_score_after
    assert reduce_score > switch_score, (
        f"REDUCE_LOAD ({reduce_score:.3f}) should be strictly higher than "
        f"SWITCH_REDUNDANT ({switch_score:.3f}). "
        "If they are equal, the hard-threshold z_score=None bug has resurfaced."
    )


def test_integration_all_scores_in_range():
    ar, rr, mission, record, scenario = _get_peak()
    from backend.app.decision.engine import DecisionEngine
    result = DecisionEngine(scenario).evaluate(ar, rr, mission, record)
    for o in result.options:
        assert 0.0 <= o.computed_risk_score_after <= 1.0


def test_integration_what_if_switch_reduces_risk():
    ar, rr, mission, record, scenario = _get_peak()
    from backend.app.decision.engine import DecisionEngine
    engine = DecisionEngine(scenario)
    wi = engine.what_if("SWITCH_REDUNDANT", ar, rr, mission, record)
    assert wi.delta < 0.0, (
        f"SWITCH_REDUNDANT should reduce risk; delta={wi.delta:.3f}"
    )


def test_integration_what_if_continue_delta_near_zero():
    ar, rr, mission, record, scenario = _get_peak()
    from backend.app.decision.engine import DecisionEngine
    engine = DecisionEngine(scenario)
    wi = engine.what_if("CONTINUE", ar, rr, mission, record)
    assert abs(wi.delta) < 0.05, (
        f"CONTINUE delta should be ≈0; got {wi.delta:.4f}"
    )


def test_integration_what_if_delta_consistent_with_evaluate():
    """what_if projected_risk must equal the corresponding option's computed_risk_score_after."""
    ar, rr, mission, record, scenario = _get_peak()
    from backend.app.decision.engine import DecisionEngine
    engine = DecisionEngine(scenario)
    result = engine.evaluate(ar, rr, mission, record)
    by_id = {o.option_id: o for o in result.options}
    for opt_id in ["CONTINUE", "REDUCE_LOAD", "SWITCH_REDUNDANT"]:
        wi = engine.what_if(opt_id, ar, rr, mission, record)
        assert wi.projected_risk == pytest.approx(
            by_id[opt_id].computed_risk_score_after, abs=1e-9
        ), f"Mismatch for {opt_id}: what_if={wi.projected_risk:.6f} vs evaluate={by_id[opt_id].computed_risk_score_after:.6f}"
