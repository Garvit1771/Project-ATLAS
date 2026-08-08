"""
ATLAS — TelemetryRecord Pydantic model.

Represents one telemetry snapshot from the spacecraft simulator.
All 13 variables are defined exactly as in docs/architecture.md Section 4.
Pydantic v2 validates every incoming record; out-of-schema records are rejected.
"""

from datetime import datetime
from pydantic import BaseModel, Field


class TelemetryRecord(BaseModel):
    """One telemetry snapshot emitted by the simulator at 1 Hz."""

    # ── Metadata ──────────────────────────────────────────────────────────────
    tick: int = Field(..., ge=0, description="Simulation tick counter (0-based)")
    timestamp: datetime = Field(..., description="UTC timestamp of the record")

    # ── Power subsystem ───────────────────────────────────────────────────────
    battery_voltage_v: float = Field(
        ..., description="Battery voltage (V). Nominal: 26.0–29.5 V"
    )
    battery_temp_c: float = Field(
        ..., description="Battery temperature (°C). Nominal: 15–35 °C"
    )
    solar_power_w: float = Field(
        ..., description="Solar array power output (W). Nominal: 80–120 W"
    )

    # ── Computing subsystem ───────────────────────────────────────────────────
    cpu_temp_c: float = Field(
        ..., description="CPU temperature (°C). Nominal: 40–70 °C"
    )
    cpu_load_pct: float = Field(
        ..., description="CPU load (%). Nominal: 20–70 %"
    )

    # ── Propulsion subsystem ──────────────────────────────────────────────────
    thruster_1_temp_c: float = Field(
        ..., description="Thruster 1 temperature (°C). Nominal: 180–220 °C"
    )
    thruster_2_temp_c: float = Field(
        ..., description="Thruster 2 temperature (°C). Nominal: 180–220 °C"
    )
    thruster_2_vibration_hz: float = Field(
        ..., description="Thruster 2 vibration (Hz). Nominal: 0.5–2.0 Hz"
    )
    thruster_2_efficiency_pct: float = Field(
        ..., description="Thruster 2 efficiency (%). Nominal: 92–98 %"
    )

    # ── Attitude subsystem ────────────────────────────────────────────────────
    attitude_error_deg: float = Field(
        ..., description="Attitude pointing error (°). Nominal: 0.0–0.5 °"
    )

    # ── Communications subsystem ──────────────────────────────────────────────
    signal_strength_dbm: float = Field(
        ..., description="Signal strength (dBm). Nominal: -85 to -60 dBm"
    )
    packet_loss_pct: float = Field(
        ..., description="Packet loss (%). Nominal: 0–2 %"
    )

    # ── Environment ───────────────────────────────────────────────────────────
    radiation_level_mgy: float = Field(
        ..., description="Radiation level (mGy/h). Nominal: 0.1–0.8 mGy/h"
    )

    model_config = {"frozen": True}
