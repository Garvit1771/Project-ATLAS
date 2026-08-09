"""
ATLAS — Telemetry generator.

Produces TelemetryRecord instances at 1 Hz for all 13 telemetry variables.
Telemetry is physically plausible, correlated where the architecture specifies,
and reproducible given the same random seed.

Architecture-specified physical correlations (docs/architecture.md Section 4):
  1. Higher cpu_load_pct → higher cpu_temp_c
  2. Lower thruster_2_efficiency_pct → higher cpu_load_pct
     (attitude correction loop compensating for propulsion imbalance)
  3. Higher thruster_2_temp_c → minor rise in battery_temp_c
     (shared thermal bus)
  4. Higher radiation_level_mgy → minor rise in cpu_load_pct

Noise model:
  Each variable has a small Gaussian noise component whose standard deviation
  is 0.5% of its normal range width. This keeps values realistic without
  masking the fault signal.

Fault injection:
  When a ScenarioConfig is provided, a FaultInjector computes per-tick signed
  offsets that are added to the baseline before noise. Fault progression is
  gradual (linear ramp as defined in fault_injection.py).
"""

from __future__ import annotations

import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Optional

from backend.app.models.telemetry import TelemetryRecord
from backend.app.simulation.fault_injection import FaultInjector
from backend.app.simulation.scenarios import ScenarioConfig


# ── Normal-range loader ───────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[3]
_NORMAL_RANGES_PATH = _REPO_ROOT / "data" / "normal_ranges.json"


def _load_normal_ranges() -> dict[str, dict]:
    with _NORMAL_RANGES_PATH.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return data["variables"]


# ── Baseline operating points ─────────────────────────────────────────────────
# Mid-point of the normal range for each variable.
# The simulator oscillates around these points during normal operation.

_NORMAL_RANGES: dict[str, dict] = _load_normal_ranges()

def _midpoint(var: str) -> float:
    v = _NORMAL_RANGES[var]
    return (v["min"] + v["max"]) / 2.0

def _range_width(var: str) -> float:
    v = _NORMAL_RANGES[var]
    return v["max"] - v["min"]


# Baseline operating points during orbital-insertion burn (slightly above midpoint
# for temperature/load variables to reflect an active burn phase).
_BASELINE: dict[str, float] = {
    "battery_voltage_v":         27.8,   # slightly above mid — healthy charge
    "battery_temp_c":            24.0,   # nominal operating temp
    "solar_power_w":             100.0,  # mid-range
    "cpu_temp_c":                55.0,   # moderate under burn load
    "cpu_load_pct":              45.0,   # moderate — attitude correction running
    "thruster_1_temp_c":         200.0,  # lower end of active burn range
    "thruster_2_temp_c":         200.0,
    "thruster_2_vibration_hz":   1.2,    # mid-range nominal vibration
    "thruster_2_efficiency_pct": 95.0,   # healthy efficiency
    "attitude_error_deg":        0.12,   # small but non-zero pointing error
    "signal_strength_dbm":       -72.0,  # good link margin
    "packet_loss_pct":           0.5,    # low nominal loss
    "radiation_level_mgy":       0.3,    # moderate — polar orbit
}

# Noise: std dev = 0.5% of normal range width per variable
_NOISE_STD: dict[str, float] = {
    var: _range_width(var) * 0.005
    for var in _BASELINE
}

# Slow drift amplitude (sinusoidal variation over ~300-tick window)
# Adds orbital-period-like variation without exceeding the normal envelope.
_DRIFT_AMP: dict[str, float] = {
    var: _range_width(var) * 0.04   # ±4% of range
    for var in _BASELINE
}

# Per-variable drift frequencies (different periods to avoid lock-step behaviour)
_DRIFT_FREQ: dict[str, float] = {
    "battery_voltage_v":         0.008,
    "battery_temp_c":            0.006,
    "solar_power_w":             0.012,
    "cpu_temp_c":                0.009,
    "cpu_load_pct":              0.011,
    "thruster_1_temp_c":         0.007,
    "thruster_2_temp_c":         0.007,
    "thruster_2_vibration_hz":   0.013,
    "thruster_2_efficiency_pct": 0.005,
    "attitude_error_deg":        0.015,
    "signal_strength_dbm":       0.004,
    "packet_loss_pct":           0.010,
    "radiation_level_mgy":       0.003,
}


class TelemetryGenerator:
    """
    Generates TelemetryRecord instances tick by tick.

    Parameters:
        scenario:   Optional ScenarioConfig for fault injection.
                    If None, produces normal-operation telemetry indefinitely.
        seed:       Random seed for reproducibility. None → non-deterministic.
        start_time: UTC datetime for tick 0. Defaults to a fixed reference time
                    so tests are deterministic even without an explicit seed.
    """

    # Fixed reference start time for deterministic timestamp generation
    _REFERENCE_START = datetime(2026, 8, 9, 2, 0, 0, tzinfo=timezone.utc)

    def __init__(
        self,
        scenario: Optional[ScenarioConfig] = None,
        seed: Optional[int] = 42,
        start_time: Optional[datetime] = None,
    ) -> None:
        self._scenario = scenario
        self._rng = random.Random(seed)
        self._start_time = start_time or self._REFERENCE_START
        self._injector = FaultInjector(scenario.fault) if scenario else None

    # ── Public API ────────────────────────────────────────────────────────────

    def generate(self, num_ticks: int) -> list[TelemetryRecord]:
        """Generate exactly num_ticks records and return as a list."""
        return list(self._stream(num_ticks))

    def stream(self) -> Iterator[TelemetryRecord]:
        """Infinite generator — yields one TelemetryRecord per tick."""
        return self._stream(max_ticks=None)

    # ── Internal generation ───────────────────────────────────────────────────

    def _stream(self, max_ticks: Optional[int]) -> Iterator[TelemetryRecord]:
        tick = 0
        while max_ticks is None or tick < max_ticks:
            yield self._record_at(tick)
            tick += 1

    def _record_at(self, tick: int) -> TelemetryRecord:
        """Compute the TelemetryRecord for a specific tick."""
        timestamp = self._start_time + timedelta(seconds=tick)

        # 1. Compute fault offsets (zero dict if no scenario active)
        offsets = self._injector.offsets_at_tick(tick) if self._injector else {}

        # 2. Compute independent baseline + drift + noise for all variables
        raw: dict[str, float] = {}
        for var in _BASELINE:
            baseline = _BASELINE[var]
            drift = _DRIFT_AMP[var] * math.sin(2 * math.pi * _DRIFT_FREQ[var] * tick)
            noise = self._rng.gauss(0.0, _NOISE_STD[var])
            fault_offset = offsets.get(var, 0.0)
            raw[var] = baseline + drift + noise + fault_offset

        # 3. Apply architecture-specified physical correlations.
        #    Correlations are applied AFTER fault offsets so that fault-induced
        #    changes in one variable correctly propagate to correlated variables.

        # Correlation 1: lower thruster_2_efficiency → higher cpu_load
        # A 1% drop in efficiency → +0.6% CPU load (attitude correction compensating)
        efficiency_deviation = 95.0 - raw["thruster_2_efficiency_pct"]  # positive when degraded
        cpu_load_correction = efficiency_deviation * 0.6
        raw["cpu_load_pct"] += cpu_load_correction

        # Correlation 2: higher cpu_load → higher cpu_temp
        # Each 1% of CPU load above baseline adds ~0.1 °C
        cpu_load_deviation = raw["cpu_load_pct"] - _BASELINE["cpu_load_pct"]
        raw["cpu_temp_c"] += cpu_load_deviation * 0.10

        # Correlation 3: higher thruster_2_temp → minor rise in battery_temp (shared thermal bus)
        # Each 1 °C rise in thruster_2_temp above baseline adds ~0.03 °C to battery_temp
        t2_temp_deviation = raw["thruster_2_temp_c"] - _BASELINE["thruster_2_temp_c"]
        raw["battery_temp_c"] += t2_temp_deviation * 0.03

        # Correlation 4: higher radiation → minor rise in cpu_load
        # Each 0.1 mGy/h above baseline adds ~0.5% CPU load
        rad_deviation = raw["radiation_level_mgy"] - _BASELINE["radiation_level_mgy"]
        raw["cpu_load_pct"] += rad_deviation * 0.5

        # 4. Clamp all values to physically sensible bounds
        #    Use 1.5× the normal range to permit fault-state exceedance
        #    without allowing runaway values.
        raw = self._clamp_values(raw)

        return TelemetryRecord(
            tick=tick,
            timestamp=timestamp,
            battery_voltage_v=round(raw["battery_voltage_v"], 4),
            battery_temp_c=round(raw["battery_temp_c"], 4),
            solar_power_w=round(raw["solar_power_w"], 4),
            cpu_temp_c=round(raw["cpu_temp_c"], 4),
            cpu_load_pct=round(raw["cpu_load_pct"], 4),
            thruster_1_temp_c=round(raw["thruster_1_temp_c"], 4),
            thruster_2_temp_c=round(raw["thruster_2_temp_c"], 4),
            thruster_2_vibration_hz=round(raw["thruster_2_vibration_hz"], 4),
            thruster_2_efficiency_pct=round(raw["thruster_2_efficiency_pct"], 4),
            attitude_error_deg=round(raw["attitude_error_deg"], 6),
            signal_strength_dbm=round(raw["signal_strength_dbm"], 4),
            packet_loss_pct=round(raw["packet_loss_pct"], 4),
            radiation_level_mgy=round(raw["radiation_level_mgy"], 6),
        )

    @staticmethod
    def _clamp_values(raw: dict[str, float]) -> dict[str, float]:
        """
        Clamp each variable to a generous outer bound.
        Normal-range values are used as the expected envelope; the clamp
        boundary is set at normal_min - 50% range and normal_max + 50% range
        to permit fault exceedance while preventing arithmetic runaway.
        """
        clamped = {}
        for var, value in raw.items():
            v_cfg = _NORMAL_RANGES[var]
            v_min = v_cfg["min"]
            v_max = v_cfg["max"]
            width = v_max - v_min
            hard_min = v_min - 0.5 * width
            hard_max = v_max + 0.5 * width
            clamped[var] = max(hard_min, min(hard_max, value))
        return clamped
