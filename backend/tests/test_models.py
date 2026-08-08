"""
ATLAS — Phase 1 model tests.

Tests:
  - All models import successfully
  - Valid construction of every model
  - Invalid telemetry records are rejected by Pydantic
  - Required fields are enforced
  - DecisionOption does NOT expose risk_score_after_target
  - Enum values are correct
  - MissionContext dataclass construction
"""

import pytest
from datetime import datetime, timezone

# ── Import smoke test ─────────────────────────────────────────────────────────

def test_all_models_importable():
    """All model modules must be importable without errors."""
    from backend.app.models.telemetry import TelemetryRecord  # noqa: F401
    from backend.app.models.analytics import (  # noqa: F401
        AnomalyDetection, AnalyticsResult,
        Severity, DetectionMethod, ConfidenceBand, TrendDirection,
    )
    from backend.app.models.risk import RiskResult  # noqa: F401
    from backend.app.models.decision import (  # noqa: F401
        DecisionOption, DecisionResult, WhatIfResult,
        RecommendationStrength, SourceTag,
    )
    from backend.app.models.mission import MissionContext  # noqa: F401


# ── TelemetryRecord ───────────────────────────────────────────────────────────

def _valid_telemetry_data() -> dict:
    return {
        "tick": 0,
        "timestamp": datetime(2026, 8, 8, 2, 0, 0, tzinfo=timezone.utc),
        "battery_voltage_v": 27.8,
        "battery_temp_c": 24.0,
        "solar_power_w": 100.0,
        "cpu_temp_c": 55.0,
        "cpu_load_pct": 45.0,
        "thruster_1_temp_c": 200.0,
        "thruster_2_temp_c": 200.0,
        "thruster_2_vibration_hz": 1.2,
        "thruster_2_efficiency_pct": 95.0,
        "attitude_error_deg": 0.1,
        "signal_strength_dbm": -72.0,
        "packet_loss_pct": 0.5,
        "radiation_level_mgy": 0.3,
    }


def test_telemetry_record_valid():
    from backend.app.models.telemetry import TelemetryRecord
    data = _valid_telemetry_data()
    record = TelemetryRecord(**data)
    assert record.tick == 0
    assert record.battery_voltage_v == 27.8
    assert record.thruster_2_vibration_hz == 1.2
    assert record.signal_strength_dbm == -72.0


def test_telemetry_record_all_13_variables_present():
    """Confirm all 13 architecture-specified variables are fields on the model."""
    from backend.app.models.telemetry import TelemetryRecord
    fields = TelemetryRecord.model_fields
    expected = [
        "battery_voltage_v", "battery_temp_c", "solar_power_w",
        "cpu_temp_c", "cpu_load_pct",
        "thruster_1_temp_c", "thruster_2_temp_c",
        "thruster_2_vibration_hz", "thruster_2_efficiency_pct",
        "attitude_error_deg",
        "signal_strength_dbm", "packet_loss_pct",
        "radiation_level_mgy",
    ]
    for var in expected:
        assert var in fields, f"Missing telemetry field: {var}"


def test_telemetry_record_missing_required_field_rejected():
    from backend.app.models.telemetry import TelemetryRecord
    from pydantic import ValidationError
    data = _valid_telemetry_data()
    del data["thruster_2_temp_c"]
    with pytest.raises(ValidationError):
        TelemetryRecord(**data)


def test_telemetry_record_wrong_type_rejected():
    from backend.app.models.telemetry import TelemetryRecord
    from pydantic import ValidationError
    data = _valid_telemetry_data()
    data["battery_voltage_v"] = "not-a-number"
    with pytest.raises(ValidationError):
        TelemetryRecord(**data)


def test_telemetry_record_negative_tick_rejected():
    from backend.app.models.telemetry import TelemetryRecord
    from pydantic import ValidationError
    data = _valid_telemetry_data()
    data["tick"] = -1
    with pytest.raises(ValidationError):
        TelemetryRecord(**data)


def test_telemetry_record_is_immutable():
    """frozen=True means the record cannot be mutated after construction."""
    from backend.app.models.telemetry import TelemetryRecord
    record = TelemetryRecord(**_valid_telemetry_data())
    with pytest.raises(Exception):
        record.tick = 99  # type: ignore


# ── AnomalyDetection ──────────────────────────────────────────────────────────

def test_anomaly_detection_valid_no_anomaly():
    from backend.app.models.analytics import AnomalyDetection, Severity
    det = AnomalyDetection(
        variable="thruster_2_vibration_hz",
        subsystem="propulsion",
        anomaly_detected=False,
        severity=Severity.NONE,
    )
    assert det.anomaly_detected is False
    assert det.detection_method is None
    assert det.z_score is None
    assert det.evidence == []


def test_anomaly_detection_valid_with_anomaly():
    from backend.app.models.analytics import (
        AnomalyDetection, Severity, DetectionMethod,
        ConfidenceBand, TrendDirection,
    )
    det = AnomalyDetection(
        variable="thruster_2_vibration_hz",
        subsystem="propulsion",
        anomaly_detected=True,
        severity=Severity.MODERATE,
        detection_method=DetectionMethod.ROLLING_ZSCORE,
        z_score=3.2,
        confidence_value=0.72,
        confidence_band=ConfidenceBand.MODERATE,
        trend_direction=TrendDirection.RISING,
        regression_slope=0.018,
        first_anomaly_tick=155,
        evidence=["thruster_2_vibration_hz z-score: 3.2 (threshold: 2.5)"],
    )
    assert det.anomaly_detected is True
    assert det.severity == Severity.MODERATE
    assert det.confidence_band == ConfidenceBand.MODERATE
    assert det.first_anomaly_tick == 155
    assert len(det.evidence) == 1


def test_anomaly_detection_confidence_value_range():
    from backend.app.models.analytics import AnomalyDetection, Severity
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        AnomalyDetection(
            variable="x", subsystem="y",
            anomaly_detected=True, severity=Severity.HIGH,
            confidence_value=1.5,  # out of range
        )


def test_anomaly_detection_missing_required_fields():
    from backend.app.models.analytics import AnomalyDetection
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        AnomalyDetection(variable="thruster_2_vibration_hz")  # missing required fields


# ── AnalyticsResult ───────────────────────────────────────────────────────────

def test_analytics_result_empty():
    from backend.app.models.analytics import AnalyticsResult
    result = AnalyticsResult(tick=10)
    assert result.tick == 10
    assert result.detections == []
    assert result.composite_anomaly is False
    assert result.correlated_signals == []


def test_analytics_result_with_composite():
    from backend.app.models.analytics import (
        AnalyticsResult, AnomalyDetection, Severity,
        DetectionMethod, ConfidenceBand, TrendDirection,
    )
    det1 = AnomalyDetection(
        variable="thruster_2_vibration_hz", subsystem="propulsion",
        anomaly_detected=True, severity=Severity.MODERATE,
        detection_method=DetectionMethod.ROLLING_ZSCORE,
        first_anomaly_tick=152, evidence=["vibration z-score 3.1"],
    )
    det2 = AnomalyDetection(
        variable="thruster_2_temp_c", subsystem="propulsion",
        anomaly_detected=True, severity=Severity.MODERATE,
        detection_method=DetectionMethod.ROLLING_ZSCORE,
        first_anomaly_tick=155, evidence=["temp z-score 3.0"],
    )
    result = AnalyticsResult(
        tick=180,
        detections=[det1, det2],
        composite_anomaly=True,
        composite_subsystem="propulsion",
        composite_severity=Severity.HIGH,
        composite_confidence_value=0.91,
        composite_confidence_band=ConfidenceBand.HIGH,
        correlated_signals=["thruster_2_vibration_hz", "thruster_2_temp_c"],
    )
    assert result.composite_anomaly is True
    assert result.composite_severity == Severity.HIGH
    assert result.composite_confidence_band == ConfidenceBand.HIGH
    assert len(result.correlated_signals) == 2


# ── RiskResult ────────────────────────────────────────────────────────────────

def test_risk_result_valid():
    from backend.app.models.risk import RiskResult
    from backend.app.models.analytics import Severity
    result = RiskResult(
        tick=180,
        risk_score=0.73,
        severity=Severity.HIGH,
        estimated_threshold_breach_minutes=22.0,
        dominant_variable="thruster_2_vibration_hz",
        redundancy_available=True,
    )
    assert result.risk_score == 0.73
    assert result.severity == Severity.HIGH
    assert result.estimated_threshold_breach_minutes == 22.0


def test_risk_result_no_breach_estimate():
    from backend.app.models.risk import RiskResult
    from backend.app.models.analytics import Severity
    result = RiskResult(tick=10, risk_score=0.1, severity=Severity.LOW)
    assert result.estimated_threshold_breach_minutes is None


def test_risk_result_score_bounds():
    from backend.app.models.risk import RiskResult
    from backend.app.models.analytics import Severity
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        RiskResult(tick=0, risk_score=1.5, severity=Severity.CRITICAL)
    with pytest.raises(ValidationError):
        RiskResult(tick=0, risk_score=-0.1, severity=Severity.NONE)


# ── DecisionOption ────────────────────────────────────────────────────────────

def test_decision_option_valid():
    from backend.app.models.decision import DecisionOption, RecommendationStrength
    opt = DecisionOption(
        option_id="SWITCH_REDUNDANT",
        label="Switch to Redundant Thruster 3",
        description="Deactivate Thruster 2 and transfer burn to Redundant Thruster 3.",
        computed_risk_score_after=0.18,
        recommendation_strength=RecommendationStrength.STRONG,
        fuel_cost_pct=7.0,
        time_delay_min=4.0,
        mission_constraint_satisfied=True,
        subsystem_stress=["propulsion"],
    )
    assert opt.computed_risk_score_after == 0.18
    assert opt.recommendation_strength == RecommendationStrength.STRONG


def test_decision_option_does_not_expose_risk_score_after_target():
    """
    CRITICAL: risk_score_after_target is a scenario config validation field only.
    It must NOT appear as a field on the runtime DecisionOption model.
    """
    from backend.app.models.decision import DecisionOption
    assert "risk_score_after_target" not in DecisionOption.model_fields, (
        "risk_score_after_target must not be a field on DecisionOption — "
        "it is a Phase 5 test fixture, not a runtime response field."
    )


def test_decision_option_does_not_expose_ambiguous_risk_score_after():
    """
    The ambiguous field name risk_score_after must not exist on DecisionOption.
    Only computed_risk_score_after is valid.
    """
    from backend.app.models.decision import DecisionOption
    assert "risk_score_after" not in DecisionOption.model_fields, (
        "Use computed_risk_score_after, not the ambiguous risk_score_after."
    )


def test_decision_option_computed_risk_score_bounds():
    from backend.app.models.decision import DecisionOption, RecommendationStrength
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        DecisionOption(
            option_id="X", label="X", description="X",
            computed_risk_score_after=1.5,  # out of range
            recommendation_strength=RecommendationStrength.WEAK,
            fuel_cost_pct=0.0, time_delay_min=0.0,
            mission_constraint_satisfied=True,
        )


def test_decision_result_valid():
    from backend.app.models.decision import (
        DecisionOption, DecisionResult, RecommendationStrength,
    )
    opts = [
        DecisionOption(
            option_id="CONTINUE", label="Continue", description="Monitor.",
            computed_risk_score_after=0.73,
            recommendation_strength=RecommendationStrength.WEAK,
            fuel_cost_pct=0.0, time_delay_min=0.0,
            mission_constraint_satisfied=True,
        ),
        DecisionOption(
            option_id="SWITCH_REDUNDANT", label="Switch T3", description="Switch.",
            computed_risk_score_after=0.18,
            recommendation_strength=RecommendationStrength.STRONG,
            fuel_cost_pct=7.0, time_delay_min=4.0,
            mission_constraint_satisfied=True,
        ),
    ]
    result = DecisionResult(
        tick=180,
        options=opts,
        current_risk_score=0.73,
        fault_type="thruster_degradation",
        mission_phase="orbital_insertion",
    )
    assert len(result.options) == 2
    assert result.current_risk_score == 0.73


def test_what_if_result_valid():
    from backend.app.models.decision import WhatIfResult
    result = WhatIfResult(
        option_id="SWITCH_REDUNDANT",
        current_risk=0.73,
        projected_risk=0.18,
        delta=-0.55,
    )
    assert result.delta == pytest.approx(-0.55)


# ── SourceTag enum ────────────────────────────────────────────────────────────

def test_source_tag_values():
    from backend.app.models.decision import SourceTag
    assert SourceTag.COMPUTED       == "COMPUTED"
    assert SourceTag.MISSION_PARAMS == "MISSION PARAMS"
    assert SourceTag.AI_EXPLANATION == "AI EXPLANATION"
    assert SourceTag.OPERATOR       == "OPERATOR"


# ── MissionContext ────────────────────────────────────────────────────────────

def test_mission_context_defaults():
    from backend.app.models.mission import MissionContext
    ctx = MissionContext()
    assert ctx.mission_name == "ALPHA-1"
    assert ctx.phase == "orbital_insertion"
    assert ctx.thruster_2_active is True
    assert ctx.thruster_3_active is False
    assert ctx.redundancy_available is True
    assert len(ctx.constraints) == 3


def test_mission_context_custom_values():
    from backend.app.models.mission import MissionContext
    from datetime import datetime, timezone
    t = datetime(2026, 8, 9, 2, 30, 0, tzinfo=timezone.utc)
    ctx = MissionContext(
        mission_name="ALPHA-1",
        phase="orbital_insertion",
        next_maneuver_time=t,
        thruster_2_active=False,
        thruster_3_active=True,
        redundancy_available=True,
        scenario_id="ALPHA1-FAULT-01",
    )
    assert ctx.next_maneuver_time == t
    assert ctx.thruster_2_active is False
    assert ctx.thruster_3_active is True
    assert ctx.scenario_id == "ALPHA1-FAULT-01"


def test_mission_context_constraints_are_independent():
    """Each MissionContext instance must have its own constraints list."""
    from backend.app.models.mission import MissionContext
    ctx1 = MissionContext()
    ctx2 = MissionContext()
    ctx1.constraints.append("extra")
    assert "extra" not in ctx2.constraints


# ── Severity enum normalisation ───────────────────────────────────────────────

def test_severity_enum_values():
    from backend.app.models.analytics import Severity
    assert Severity.NONE     == "NONE"
    assert Severity.LOW      == "LOW"
    assert Severity.MODERATE == "MODERATE"
    assert Severity.HIGH     == "HIGH"
    assert Severity.CRITICAL == "CRITICAL"


def test_detection_method_enum_values():
    from backend.app.models.analytics import DetectionMethod
    assert DetectionMethod.HARD_THRESHOLD     == "hard_threshold"
    assert DetectionMethod.ROLLING_ZSCORE     == "rolling_zscore"
    assert DetectionMethod.ZSCORE_CORRELATION == "rolling_zscore+correlation"
