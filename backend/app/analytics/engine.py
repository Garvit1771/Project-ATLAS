"""
ATLAS — Analytics engine.

Orchestrates the feature engineering and three-layer detection cascade,
maintains the rolling buffer and anomaly-onset tracking state, and
produces AnalyticsResult for each incoming TelemetryRecord.

Usage
-----
    engine = AnalyticsEngine()
    for record in simulator.stream():
        result = engine.process(record)
        # result is an AnalyticsResult or None if no anomaly was detected
        # (use process_all=True overload to always get a result)

The engine tracks first_anomaly_tick per variable to support the Layer 3
correlation window check across calls. State is reset by calling engine.reset().
"""

from __future__ import annotations

from collections import deque
from typing import Optional

from backend.app.analytics.detector import (
    _check_correlation,
    _check_hard_threshold,
    _check_zscore,
)
from backend.app.analytics.features import compute_features, ROLLING_WINDOW
from backend.app.models.analytics import (
    AnalyticsResult,
    AnomalyDetection,
    ConfidenceBand,
    DetectionMethod,
    Severity,
)
from backend.app.models.telemetry import TelemetryRecord
from backend.app.analytics.detector import (
    _confidence_band,
    Z_THRESHOLD,
    CORR_WINDOW,
    _VAR_CFG,
    _CORR_RULES,
)


BUFFER_SIZE: int = 300  # N = 300 ticks as per methodology.md Section 1


class AnalyticsEngine:
    """
    Stateful analytics engine.

    Maintains:
      - A rolling buffer of the last BUFFER_SIZE TelemetryRecords.
      - A dict of first_anomaly_tick per variable for Layer 3 correlation.

    Produces one AnalyticsResult per tick, regardless of whether an anomaly
    was detected (anomaly fields will be empty/False if nothing triggered).
    """

    def __init__(self, window: int = ROLLING_WINDOW) -> None:
        self._buffer: deque[TelemetryRecord] = deque(maxlen=BUFFER_SIZE)
        self._window = window
        # first_anomaly_tick[var] = tick at which var first became anomalous
        # Cleared when the variable returns to normal.
        self._first_anomaly_ticks: dict[str, int] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    def process(self, record: TelemetryRecord) -> AnalyticsResult:
        """
        Ingest one TelemetryRecord and return the AnalyticsResult for this tick.
        Always returns an AnalyticsResult (composite_anomaly=False if quiet).
        """
        self._buffer.append(record)
        return self._run(record.tick)

    def process_batch(self, records: list[TelemetryRecord]) -> list[AnalyticsResult]:
        """Process a list of records in order and return all results."""
        return [self.process(r) for r in records]

    def reset(self) -> None:
        """Clear the buffer and anomaly state. Use between independent simulations."""
        self._buffer.clear()
        self._first_anomaly_ticks.clear()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _run(self, current_tick: int) -> AnalyticsResult:
        # 1. Compute features for all variables
        features = compute_features(self._buffer, window=self._window)

        # 2. Run Layer 1 and Layer 2 for each variable
        per_signal: dict[str, AnomalyDetection] = {}

        for var, feat in features.items():
            detection: Optional[AnomalyDetection] = None

            # Layer 1 takes precedence
            detection = _check_hard_threshold(var, feat)

            # Layer 2 only if Layer 1 did not fire
            if detection is None:
                detection = _check_zscore(var, feat)

            if detection is not None:
                # Track first anomaly tick for Layer 3 correlation window
                if var not in self._first_anomaly_ticks:
                    self._first_anomaly_ticks[var] = current_tick

                # Attach the tracked first_anomaly_tick to the detection
                fat = self._first_anomaly_ticks[var]
                detection = AnomalyDetection(
                    **{
                        **detection.model_dump(),
                        "first_anomaly_tick": fat,
                    }
                )
                per_signal[var] = detection
            else:
                # Variable is not anomalous — clear tracking state
                self._first_anomaly_ticks.pop(var, None)

        # 3. Layer 3: cross-signal correlation
        corr_fired, corr_sub, corr_sev, corr_conf, corr_signals = _check_correlation(
            per_signal_detections=per_signal,
            first_anomaly_ticks=self._first_anomaly_ticks,
            current_tick=current_tick,
        )

        composite_conf_band: Optional[ConfidenceBand] = None
        if corr_fired and corr_conf is not None:
            composite_conf_band = _confidence_band(corr_conf)

            # Update detection_method for correlated signals to reflect Layer 3,
            # BUT only when the original method was ROLLING_ZSCORE.
            # HARD_THRESHOLD detections keep their original method because:
            #   - z_score is None for HARD_THRESHOLD detections (by definition).
            #   - Overwriting the method with ZSCORE_CORRELATION would produce an
            #     internally inconsistent detection (method says z-score correlation,
            #     but z_score is None) that breaks evidence construction for Granite
            #     and the hard-threshold branch in _apply_action_to_analytics.
            # The Layer 3 composite information is fully captured at the AnalyticsResult
            # level (composite_anomaly, composite_severity, composite_confidence_*,
            # correlated_signals) and does not need to be duplicated on individual
            # HARD_THRESHOLD detection records.
            updated: dict[str, AnomalyDetection] = {}
            for var, det in per_signal.items():
                if var in corr_signals and det.detection_method == DetectionMethod.ROLLING_ZSCORE:
                    updated[var] = AnomalyDetection(
                        **{
                            **det.model_dump(),
                            "detection_method": DetectionMethod.ZSCORE_CORRELATION,
                        }
                    )
                else:
                    updated[var] = det
            per_signal = updated

        return AnalyticsResult(
            tick=current_tick,
            detections=list(per_signal.values()),
            composite_anomaly=corr_fired,
            composite_subsystem=corr_sub,
            composite_severity=corr_sev,
            composite_confidence_value=corr_conf,
            composite_confidence_band=composite_conf_band,
            correlated_signals=corr_signals,
        )
