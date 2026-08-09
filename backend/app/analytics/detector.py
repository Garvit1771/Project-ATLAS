"""
ATLAS — Three-layer anomaly detection cascade.

Implements exactly the detection logic from docs/methodology.md Section 2:
  Layer 1 — Hard threshold breach        → severity CRITICAL
  Layer 2 — Rolling z-score threshold    → severity LOW / MODERATE / HIGH
  Layer 3 — Cross-signal correlation     → severity escalated one level

And the confidence formulas from Section 3:
  z_confidence        = min(1.0, (|z| - Z_THRESHOLD) / Z_THRESHOLD)
  composite_confidence = min(1.0, z_confidence + 0.35)
  Display bands:  >= 0.85 → HIGH  |  0.65-0.84 → MODERATE  |  < 0.65 → LOW

All values are computed deterministically from buffer data.
No probabilities are invented.
"""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Optional

from backend.app.analytics.features import VariableFeatures, compute_features
from backend.app.models.analytics import (
    AnalyticsResult,
    AnomalyDetection,
    ConfidenceBand,
    DetectionMethod,
    Severity,
    TrendDirection,
)
from backend.app.models.telemetry import TelemetryRecord


# ── Config loader ─────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[3]
_NORMAL_RANGES_PATH = _REPO_ROOT / "data" / "normal_ranges.json"


def _load_config() -> dict:
    with _NORMAL_RANGES_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


_CONFIG = _load_config()
_VAR_CFG: dict[str, dict]  = _CONFIG["variables"]
_CORR_RULES: dict[str, list[str]] = _CONFIG["correlation_rules"]
Z_THRESHOLD: float          = float(_CONFIG["z_score_threshold"])
CORR_WINDOW: int            = int(_CONFIG["correlation_window_ticks"])


# ── Severity helpers ──────────────────────────────────────────────────────────

_SEVERITY_ORDER = [
    Severity.NONE,
    Severity.LOW,
    Severity.MODERATE,
    Severity.HIGH,
    Severity.CRITICAL,
]


def _severity_from_z(abs_z: float) -> Severity:
    """Map |z| to severity per methodology.md Section 2 Layer 2 table."""
    if abs_z <= 3.0:
        return Severity.LOW
    elif abs_z <= 4.0:
        return Severity.MODERATE
    else:
        return Severity.HIGH


def _escalate_severity(sev: Severity) -> Severity:
    """Escalate severity by one level; CRITICAL stays CRITICAL."""
    idx = _SEVERITY_ORDER.index(sev)
    return _SEVERITY_ORDER[min(idx + 1, len(_SEVERITY_ORDER) - 1)]


def _max_severity(severities: list[Severity]) -> Severity:
    return max(severities, key=lambda s: _SEVERITY_ORDER.index(s))


# ── Confidence helpers ────────────────────────────────────────────────────────

def _z_confidence(abs_z: float) -> float:
    """
    z_confidence = min(1.0, (|z| - Z_THRESHOLD) / Z_THRESHOLD)
    Maps: Z_THRESHOLD → 0.0,  2×Z_THRESHOLD → 1.0.
    """
    return min(1.0, (abs_z - Z_THRESHOLD) / Z_THRESHOLD)


def _confidence_band(value: float) -> ConfidenceBand:
    """Map numeric confidence to display band per methodology.md Section 3."""
    if value >= 0.85:
        return ConfidenceBand.HIGH
    elif value >= 0.65:
        return ConfidenceBand.MODERATE
    else:
        return ConfidenceBand.LOW


# ── Evidence builder ──────────────────────────────────────────────────────────

def _build_evidence(
    var: str,
    feat: VariableFeatures,
    method: DetectionMethod,
) -> list[str]:
    """
    Produce human-readable evidence strings for Granite prompt injection.
    Each entry is directly traceable to a specific computation.
    """
    evidence: list[str] = []
    cfg = _VAR_CFG[var]
    v_min, v_max = cfg["min"], cfg["max"]

    if method == DetectionMethod.HARD_THRESHOLD:
        if feat.current_value < v_min:
            evidence.append(
                f"{var} value {feat.current_value:.4f} is below minimum threshold {v_min}"
            )
        elif feat.current_value > v_max:
            evidence.append(
                f"{var} value {feat.current_value:.4f} exceeds maximum threshold {v_max}"
            )
    else:
        if feat.z_score is not None:
            evidence.append(
                f"{var} z-score: {feat.z_score:.2f} (threshold: {Z_THRESHOLD})"
            )
        if feat.trend_direction is not None:
            evidence.append(
                f"{var} trend: {feat.trend_direction.value} "
                f"(slope: {feat.regression_slope:.4f} units/tick)"
            )

    return evidence


# ── Layer 1: Hard threshold ───────────────────────────────────────────────────

def _check_hard_threshold(
    var: str,
    feat: VariableFeatures,
) -> Optional[AnomalyDetection]:
    """Return AnomalyDetection if value is outside the operating envelope, else None."""
    cfg = _VAR_CFG[var]
    v_min, v_max = cfg["min"], cfg["max"]
    subsystem = cfg["subsystem"]

    if feat.current_value < v_min or feat.current_value > v_max:
        return AnomalyDetection(
            variable=var,
            subsystem=subsystem,
            anomaly_detected=True,
            severity=Severity.CRITICAL,
            detection_method=DetectionMethod.HARD_THRESHOLD,
            z_score=None,
            confidence_value=1.0,
            confidence_band=ConfidenceBand.HIGH,
            trend_direction=feat.trend_direction,
            regression_slope=feat.regression_slope,
            first_anomaly_tick=None,  # set by engine when tracking state
            evidence=_build_evidence(var, feat, DetectionMethod.HARD_THRESHOLD),
        )
    return None


# ── Layer 2: Rolling z-score ──────────────────────────────────────────────────

def _check_zscore(
    var: str,
    feat: VariableFeatures,
) -> Optional[AnomalyDetection]:
    """Return AnomalyDetection if |z_score| > Z_THRESHOLD, else None."""
    if feat.z_score is None:
        return None  # cold-start; not enough data yet

    abs_z = abs(feat.z_score)
    if abs_z <= Z_THRESHOLD:
        return None

    cfg = _VAR_CFG[var]
    subsystem = cfg["subsystem"]
    severity = _severity_from_z(abs_z)
    conf_val = _z_confidence(abs_z)
    conf_band = _confidence_band(conf_val)

    return AnomalyDetection(
        variable=var,
        subsystem=subsystem,
        anomaly_detected=True,
        severity=severity,
        detection_method=DetectionMethod.ROLLING_ZSCORE,
        z_score=feat.z_score,
        confidence_value=conf_val,
        confidence_band=conf_band,
        trend_direction=feat.trend_direction,
        regression_slope=feat.regression_slope,
        first_anomaly_tick=None,  # set by engine
        evidence=_build_evidence(var, feat, DetectionMethod.ROLLING_ZSCORE),
    )


# ── Layer 3: Cross-signal correlation ────────────────────────────────────────

def _check_correlation(
    per_signal_detections: dict[str, AnomalyDetection],
    first_anomaly_ticks: dict[str, int],
    current_tick: int,
) -> tuple[bool, Optional[str], Optional[Severity], Optional[float], list[str]]:
    """
    Check whether ≥ 2 anomalous signals in the same subsystem had their
    first_anomaly_tick within CORR_WINDOW ticks of each other.

    Direction-agnostic: only simultaneity matters, not direction.

    Returns
    -------
    (fired, subsystem, escalated_severity, composite_confidence, correlated_signal_names)
    """
    for subsystem, rule_vars in _CORR_RULES.items():
        # Collect variables in this subsystem that are currently anomalous
        anomalous_in_sub = [
            v for v in rule_vars if v in per_signal_detections
        ]
        if len(anomalous_in_sub) < 2:
            continue

        # Check that all anomalous signals have a first_anomaly_tick within window
        ticks = [
            first_anomaly_ticks.get(v, current_tick)
            for v in anomalous_in_sub
        ]
        tick_spread = max(ticks) - min(ticks)

        if tick_spread <= CORR_WINDOW:
            # Correlation fires
            severities = [per_signal_detections[v].severity for v in anomalous_in_sub]
            highest = _max_severity(severities)
            escalated = _escalate_severity(highest)

            # Composite confidence: highest individual z-confidence + 0.35 bonus
            z_confidences = [
                per_signal_detections[v].confidence_value or 0.0
                for v in anomalous_in_sub
            ]
            best_z_conf = max(z_confidences)
            composite_conf = min(1.0, best_z_conf + 0.35)

            return True, subsystem, escalated, composite_conf, anomalous_in_sub

    return False, None, None, None, []
