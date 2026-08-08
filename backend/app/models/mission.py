"""
ATLAS — MissionContext dataclass.

Represents the live mission state injected into the risk engine, decision engine,
and AI reasoning layer. Defined as a dataclass (not Pydantic) per
docs/architecture.md Section 3.2: "Not a microservice — a structured object."

At runtime, the live MissionContext values override the static text in
backend/knowledge/mission_context.md for current-state fields (phase,
next_maneuver_time, thruster availability). The knowledge Markdown is reference
context only; the dataclass is the authoritative runtime source.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class MissionContext:
    """
    Live mission state. Populated from the scenario config and updated as the
    simulation runs. Injected into the risk engine (for time_pressure_factor)
    and the decision engine (for mission_phase and constraint checks).
    """

    # ── Mission identity ──────────────────────────────────────────────────────
    mission_name: str = "ALPHA-1"
    mission_type: str = "Lunar Orbiter"

    # ── Current phase ─────────────────────────────────────────────────────────
    phase: str = "orbital_insertion"

    # ── Timing ────────────────────────────────────────────────────────────────
    next_maneuver_time: Optional[datetime] = None
    """UTC datetime of the next critical maneuver. Used in time_pressure_factor."""

    abort_window_minutes: float = 8.0
    """Minutes of delay budget before the mission window is lost."""

    # ── Propulsion state ──────────────────────────────────────────────────────
    thruster_1_active: bool = True
    thruster_2_active: bool = True
    thruster_3_active: bool = False  # Redundant — standby at scenario start
    redundancy_available: bool = True
    """
    True when at least one redundant system is available.
    Controls redundancy_factor in the risk formula:
      True  → redundancy_factor = 0.3
      False → redundancy_factor = 1.0
    """

    # ── Active constraints ────────────────────────────────────────────────────
    constraints: list[str] = field(
        default_factory=lambda: [
            "Maintain orbital insertion window",
            "Attitude within 0.5° of burn attitude",
            "Science instruments in safe mode",
        ]
    )

    # ── Scenario reference ────────────────────────────────────────────────────
    scenario_id: Optional[str] = None
    """Active scenario identifier (e.g. 'ALPHA1-FAULT-01')."""
