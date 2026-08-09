"""
ATLAS — Scenario loader.

Loads scenario configuration from data/scenarios/*.json.
Provides typed dataclasses for fault parameters, secondary signal overrides,
and decision options. No simulation logic lives here.

Convention: all numeric deltas use the signed-delta convention from the spec —
positive means increase, negative means decrease. No direction field.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ── Repository root resolution ────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[3]  # project-atlas/
_SCENARIOS_DIR = _REPO_ROOT / "data" / "scenarios"


# ── Typed scenario data structures ────────────────────────────────────────────

@dataclass(frozen=True)
class FaultSignal:
    """A primary fault signal with a total signed delta applied over ramp_ticks."""
    variable: str
    signed_delta: float  # positive = increase, negative = decrease


@dataclass(frozen=True)
class SecondarySignal:
    """A secondary (correlated) signal that starts drifting after its own onset_tick."""
    variable: str
    onset_tick: int
    signed_delta: float


@dataclass(frozen=True)
class FaultConfig:
    """Full fault injection parameters loaded from the scenario JSON."""
    onset_tick: int
    ramp_ticks: int
    target_tick: int
    signals: list[FaultSignal]
    secondary_signals: list[SecondarySignal]


@dataclass(frozen=True)
class DecisionOptionConfig:
    """
    One decision option from the scenario file.
    Note: risk_score_after_target is included here for Phase 5 test validation
    but is intentionally absent from the runtime DecisionOption Pydantic model.
    """
    option_id: str
    label: str
    description: str
    numeric_state_deltas: dict[str, float]
    boolean_state_changes: dict[str, bool]
    risk_score_after_target: float  # validation-only; not a runtime output
    fuel_cost_pct: float
    time_delay_min: float
    mission_constraint_satisfied: bool
    subsystem_stress: list[str]
    recommendation_strength: str


@dataclass
class ScenarioConfig:
    """Complete loaded scenario configuration."""
    scenario_id: str
    description: str
    mission: str
    phase: str
    next_maneuver_utc: str
    abort_window_minutes: float
    fault: FaultConfig
    options: dict[str, DecisionOptionConfig]


# ── Loader ────────────────────────────────────────────────────────────────────

def load_scenario(scenario_id: str) -> ScenarioConfig:
    """
    Load a scenario by ID from data/scenarios/.
    The filename is derived from the scenario_id:
      'ALPHA1-FAULT-01' → 'alpha1_fault_01.json'

    Raises FileNotFoundError if the scenario file does not exist.
    Raises ValueError if the JSON is structurally invalid.
    """
    filename = scenario_id.lower().replace("-", "_") + ".json"
    path = _SCENARIOS_DIR / filename

    if not path.exists():
        raise FileNotFoundError(
            f"Scenario file not found: {path}. "
            f"Expected file derived from scenario_id '{scenario_id}'."
        )

    with path.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)

    return _parse_scenario(raw)


def load_scenario_from_path(path: Path) -> ScenarioConfig:
    """Load a scenario from an explicit file path. Used in tests."""
    with path.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return _parse_scenario(raw)


def _parse_scenario(raw: dict) -> ScenarioConfig:
    """Parse the raw JSON dict into a typed ScenarioConfig."""
    fault_raw = raw["fault"]

    signals = [
        FaultSignal(variable=var, signed_delta=cfg["signed_delta"])
        for var, cfg in fault_raw["signals"].items()
    ]

    secondary_signals = [
        SecondarySignal(
            variable=var,
            onset_tick=cfg["onset_tick"],
            signed_delta=cfg["signed_delta"],
        )
        for var, cfg in fault_raw.get("secondary_signals", {}).items()
    ]

    fault = FaultConfig(
        onset_tick=fault_raw["onset_tick"],
        ramp_ticks=fault_raw["ramp_ticks"],
        target_tick=fault_raw["target_tick"],
        signals=signals,
        secondary_signals=secondary_signals,
    )

    options = {
        opt_id: DecisionOptionConfig(
            option_id=opt_id,
            label=opt_cfg["label"],
            description=opt_cfg["description"],
            numeric_state_deltas=opt_cfg.get("numeric_state_deltas", {}),
            boolean_state_changes=opt_cfg.get("boolean_state_changes", {}),
            risk_score_after_target=opt_cfg["risk_score_after_target"],
            fuel_cost_pct=opt_cfg["fuel_cost_pct"],
            time_delay_min=opt_cfg["time_delay_min"],
            mission_constraint_satisfied=opt_cfg["mission_constraint_satisfied"],
            subsystem_stress=opt_cfg.get("subsystem_stress", []),
            recommendation_strength=opt_cfg["recommendation_strength"],
        )
        for opt_id, opt_cfg in raw.get("options", {}).items()
    }

    return ScenarioConfig(
        scenario_id=raw["scenario_id"],
        description=raw["description"],
        mission=raw["mission"],
        phase=raw["phase"],
        next_maneuver_utc=raw["next_maneuver_utc"],
        abort_window_minutes=float(raw["abort_window_minutes"]),
        fault=fault,
        options=options,
    )
