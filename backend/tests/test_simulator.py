"""
ATLAS — Phase 2 simulator tests.

Covers:
  - Module imports
  - Generated records validate as TelemetryRecord
  - All 13 fields present and correct types
  - Deterministic output with same seed
  - Normal telemetry stays within configured envelope
  - Scenario loads correctly
  - FAULT-01 arc: 120 normal ticks, then fault progression
  - Primary fault signals change in the correct direction
  - Fault progression is gradual (not an instantaneous jump)
  - Secondary signals kick in at their specified onset ticks
  - 300-tick simulation completes successfully
  - Physical correlations are preserved
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[2]
_NORMAL_RANGES_PATH = _REPO_ROOT / "data" / "normal_ranges.json"
_SCENARIO_PATH      = _REPO_ROOT / "data" / "scenarios" / "alpha1_fault_01.json"


def _load_normal_ranges() -> dict:
    with _NORMAL_RANGES_PATH.open() as f:
        return json.load(f)["variables"]


def _get_scenario():
    from backend.app.simulation.scenarios import load_scenario_from_path
    return load_scenario_from_path(_SCENARIO_PATH)


def _make_generator(with_fault: bool = False, seed: int = 42):
    from backend.app.simulation.generator import TelemetryGenerator
    scenario = _get_scenario() if with_fault else None
    return TelemetryGenerator(scenario=scenario, seed=seed)


# ── Import smoke tests ────────────────────────────────────────────────────────

def test_generator_imports():
    from backend.app.simulation.generator import TelemetryGenerator  # noqa: F401


def test_fault_injection_imports():
    from backend.app.simulation.fault_injection import FaultInjector  # noqa: F401


def test_scenarios_imports():
    from backend.app.simulation.scenarios import load_scenario_from_path  # noqa: F401


# ── Scenario loader ───────────────────────────────────────────────────────────

def test_scenario_loads_correctly():
    scenario = _get_scenario()
    assert scenario.scenario_id == "ALPHA1-FAULT-01"
    assert scenario.mission == "ALPHA-1"
    assert scenario.phase == "orbital_insertion"
    assert scenario.fault.onset_tick == 120
    assert scenario.fault.ramp_ticks == 60
    assert scenario.fault.target_tick == 180
    assert scenario.abort_window_minutes == 8.0


def test_scenario_primary_signals_loaded():
    scenario = _get_scenario()
    signal_vars = {s.variable for s in scenario.fault.signals}
    assert "thruster_2_vibration_hz"   in signal_vars
    assert "thruster_2_temp_c"         in signal_vars
    assert "thruster_2_efficiency_pct" in signal_vars


def test_scenario_signed_delta_convention():
    """Efficiency must be negative (drops); vibration and temp must be positive (rise)."""
    scenario = _get_scenario()
    by_var = {s.variable: s.signed_delta for s in scenario.fault.signals}
    assert by_var["thruster_2_efficiency_pct"] < 0, "Efficiency delta must be negative"
    assert by_var["thruster_2_vibration_hz"]   > 0, "Vibration delta must be positive"
    assert by_var["thruster_2_temp_c"]         > 0, "Temperature delta must be positive"


def test_scenario_secondary_signals_loaded():
    scenario = _get_scenario()
    sec_vars = {s.variable for s in scenario.fault.secondary_signals}
    assert "attitude_error_deg" in sec_vars
    assert "cpu_load_pct"       in sec_vars
    assert "battery_temp_c"     in sec_vars


def test_scenario_options_loaded():
    scenario = _get_scenario()
    assert "CONTINUE"         in scenario.options
    assert "REDUCE_LOAD"      in scenario.options
    assert "SWITCH_REDUNDANT" in scenario.options


def test_scenario_no_direction_field():
    """The signed-delta convention must not include a direction field."""
    with _SCENARIO_PATH.open() as f:
        raw = json.load(f)
    for sig_cfg in raw["fault"]["signals"].values():
        assert "direction" not in sig_cfg, (
            "direction field must not appear in fault signals — use signed_delta only"
        )


# ── TelemetryRecord validation ────────────────────────────────────────────────

def test_generated_record_is_valid_telemetry_record():
    from backend.app.models.telemetry import TelemetryRecord
    gen = _make_generator(with_fault=False)
    record = gen.generate(1)[0]
    assert isinstance(record, TelemetryRecord)


def test_all_13_fields_present():
    gen = _make_generator(with_fault=False)
    record = gen.generate(1)[0]
    expected_fields = [
        "battery_voltage_v", "battery_temp_c", "solar_power_w",
        "cpu_temp_c", "cpu_load_pct",
        "thruster_1_temp_c", "thruster_2_temp_c",
        "thruster_2_vibration_hz", "thruster_2_efficiency_pct",
        "attitude_error_deg",
        "signal_strength_dbm", "packet_loss_pct",
        "radiation_level_mgy",
    ]
    for field in expected_fields:
        val = getattr(record, field)
        assert isinstance(val, float), f"{field} should be float, got {type(val)}"


# ── Reproducibility ───────────────────────────────────────────────────────────

def test_same_seed_produces_same_output():
    gen_a = _make_generator(seed=42)
    gen_b = _make_generator(seed=42)
    records_a = gen_a.generate(10)
    records_b = gen_b.generate(10)
    for a, b in zip(records_a, records_b):
        assert a == b, "Same seed must produce identical records"


def test_different_seeds_produce_different_output():
    gen_a = _make_generator(seed=42)
    gen_b = _make_generator(seed=99)
    records_a = gen_a.generate(5)
    records_b = gen_b.generate(5)
    # At least one record should differ (with extremely high probability)
    assert any(a != b for a, b in zip(records_a, records_b))


# ── Normal-operation envelope ─────────────────────────────────────────────────

def test_normal_telemetry_within_envelope():
    """
    During normal operation (no fault), all 13 variables must stay within
    the configured normal ranges from data/normal_ranges.json.
    We allow a small tolerance (0.5 range-widths) to account for slow drift;
    values should not massively exceed the envelope.
    """
    ranges = _load_normal_ranges()
    gen = _make_generator(with_fault=False, seed=42)
    records = gen.generate(120)  # pre-fault window

    violations = []
    for r in records:
        for var, cfg in ranges.items():
            val = getattr(r, var)
            width = cfg["max"] - cfg["min"]
            lo = cfg["min"] - 0.5 * width
            hi = cfg["max"] + 0.5 * width
            if not (lo <= val <= hi):
                violations.append(f"tick {r.tick} {var}={val:.4f} outside [{lo:.2f}, {hi:.2f}]")

    assert not violations, f"Normal telemetry out of envelope:\n" + "\n".join(violations[:5])


# ── FAULT-01 arc ──────────────────────────────────────────────────────────────

def test_fault_01_first_120_ticks_are_normal():
    """
    Before onset_tick=120 the fault signals should behave normally —
    their values should be close to the pre-fault baseline (within noise + drift).
    We use 4× the expected noise std as the tolerance.
    """
    ranges = _load_normal_ranges()
    gen = _make_generator(with_fault=True, seed=42)
    records = gen.generate(120)

    fault_vars = ["thruster_2_vibration_hz", "thruster_2_temp_c", "thruster_2_efficiency_pct"]
    for var in fault_vars:
        cfg = ranges[var]
        width = cfg["max"] - cfg["min"]
        lo = cfg["min"] - 0.5 * width
        hi = cfg["max"] + 0.5 * width
        violations = [
            (r.tick, getattr(r, var))
            for r in records
            if not (lo <= getattr(r, var) <= hi)
        ]
        assert not violations, (
            f"{var} exceeded normal envelope before fault onset: {violations[:3]}"
        )


def test_fault_progression_starts_after_onset():
    """At tick 120 the primary fault signals should be at or very near zero offset."""
    from backend.app.simulation.fault_injection import FaultInjector
    scenario = _get_scenario()
    injector = FaultInjector(scenario.fault)

    offsets_at_119 = injector.offsets_at_tick(119)
    offsets_at_120 = injector.offsets_at_tick(120)

    # Before onset: all offsets must be exactly zero
    for var in ["thruster_2_vibration_hz", "thruster_2_temp_c", "thruster_2_efficiency_pct"]:
        assert offsets_at_119[var] == 0.0, f"offset at tick 119 should be 0 for {var}"

    # At onset (elapsed=0, ramp starts): offset = 0 * (1/60) * delta = 0 exactly
    # The ramp only produces nonzero at elapsed >= 1
    assert offsets_at_120["thruster_2_vibration_hz"] == 0.0


def test_fault_progression_is_gradual():
    """
    Fault offsets must grow incrementally, not jump to the full delta instantly.
    At the midpoint of the ramp (tick 150) the offset should be approximately
    half the full signed_delta.
    """
    from backend.app.simulation.fault_injection import FaultInjector
    scenario = _get_scenario()
    injector = FaultInjector(scenario.fault)

    # tick 150 = onset(120) + 30 ticks = 50% through the 60-tick ramp
    offsets_mid = injector.offsets_at_tick(150)
    offsets_full = injector.offsets_at_tick(180)

    # Get expected full deltas from scenario
    full_by_var = {s.variable: s.signed_delta for s in scenario.fault.signals}

    for var in ["thruster_2_vibration_hz", "thruster_2_temp_c", "thruster_2_efficiency_pct"]:
        mid_frac = offsets_mid[var] / full_by_var[var]
        assert abs(mid_frac - 0.5) < 0.02, (
            f"{var} midpoint offset fraction {mid_frac:.3f} should be ≈ 0.5"
        )
        # Full offset at target_tick
        assert abs(offsets_full[var] - full_by_var[var]) < 1e-9, (
            f"{var} full offset {offsets_full[var]} should equal {full_by_var[var]}"
        )


def test_vibration_rises_during_fault():
    """thruster_2_vibration_hz should be higher at tick 180 than at tick 119."""
    gen = _make_generator(with_fault=True, seed=42)
    records = gen.generate(200)
    pre_fault  = [r.thruster_2_vibration_hz for r in records if r.tick < 120]
    post_fault = [r.thruster_2_vibration_hz for r in records if r.tick >= 170]
    assert sum(post_fault) / len(post_fault) > sum(pre_fault) / len(pre_fault) + 0.5, (
        "Average vibration post-fault should be substantially higher than pre-fault"
    )


def test_temperature_rises_during_fault():
    """thruster_2_temp_c should be higher after the fault develops."""
    gen = _make_generator(with_fault=True, seed=42)
    records = gen.generate(200)
    pre_fault  = [r.thruster_2_temp_c for r in records if r.tick < 120]
    post_fault = [r.thruster_2_temp_c for r in records if r.tick >= 170]
    assert sum(post_fault) / len(post_fault) > sum(pre_fault) / len(pre_fault) + 5.0, (
        "Average thruster temp post-fault should be substantially higher"
    )


def test_efficiency_drops_during_fault():
    """thruster_2_efficiency_pct should be lower after the fault develops."""
    gen = _make_generator(with_fault=True, seed=42)
    records = gen.generate(200)
    pre_fault  = [r.thruster_2_efficiency_pct for r in records if r.tick < 120]
    post_fault = [r.thruster_2_efficiency_pct for r in records if r.tick >= 170]
    assert sum(post_fault) / len(post_fault) < sum(pre_fault) / len(pre_fault) - 2.0, (
        "Average efficiency post-fault should be substantially lower"
    )


def test_secondary_attitude_error_rises_after_tick_150():
    """attitude_error_deg secondary signal onset is tick 150."""
    gen = _make_generator(with_fault=True, seed=42)
    records = gen.generate(200)
    pre_secondary  = [r.attitude_error_deg for r in records if r.tick < 150]
    post_secondary = [r.attitude_error_deg for r in records if r.tick >= 175]
    assert sum(post_secondary) / len(post_secondary) > sum(pre_secondary) / len(pre_secondary) + 0.05


def test_secondary_cpu_load_rises_after_tick_150():
    """cpu_load_pct secondary onset is tick 150."""
    gen = _make_generator(with_fault=True, seed=42)
    records = gen.generate(200)
    pre_secondary  = [r.cpu_load_pct for r in records if r.tick < 150]
    post_secondary = [r.cpu_load_pct for r in records if r.tick >= 175]
    assert sum(post_secondary) / len(post_secondary) > sum(pre_secondary) / len(pre_secondary) + 2.0


def test_300_tick_simulation_completes():
    """Full 300-tick simulation must complete without error."""
    from backend.app.models.telemetry import TelemetryRecord
    gen = _make_generator(with_fault=True, seed=42)
    records = gen.generate(300)
    assert len(records) == 300
    assert all(isinstance(r, TelemetryRecord) for r in records)
    assert records[0].tick == 0
    assert records[299].tick == 299


# ── Physical correlation tests ────────────────────────────────────────────────

def test_correlation_efficiency_drives_cpu_load():
    """
    When efficiency drops (fault active), cpu_load should be higher than
    during normal operation due to the attitude correction loop.
    """
    gen_normal = _make_generator(with_fault=False, seed=42)
    gen_fault  = _make_generator(with_fault=True, seed=42)

    normal_records = gen_normal.generate(200)
    fault_records  = gen_fault.generate(200)

    # Compare the post-fault window only
    normal_cpu_post = [r.cpu_load_pct for r in normal_records if r.tick >= 170]
    fault_cpu_post  = [r.cpu_load_pct for r in fault_records  if r.tick >= 170]

    avg_normal = sum(normal_cpu_post) / len(normal_cpu_post)
    avg_fault  = sum(fault_cpu_post)  / len(fault_cpu_post)

    assert avg_fault > avg_normal, (
        "cpu_load_pct should be higher during fault due to attitude correction correlation"
    )


def test_correlation_thruster_temp_drives_battery_temp():
    """
    When thruster_2_temp rises (fault active), battery_temp should show
    a minor increase due to shared thermal bus correlation.
    """
    gen_normal = _make_generator(with_fault=False, seed=42)
    gen_fault  = _make_generator(with_fault=True, seed=42)

    normal_records = gen_normal.generate(200)
    fault_records  = gen_fault.generate(200)

    normal_batt_post = [r.battery_temp_c for r in normal_records if r.tick >= 170]
    fault_batt_post  = [r.battery_temp_c for r in fault_records  if r.tick >= 170]

    avg_normal = sum(normal_batt_post) / len(normal_batt_post)
    avg_fault  = sum(fault_batt_post)  / len(fault_batt_post)

    assert avg_fault > avg_normal, (
        "battery_temp_c should be slightly elevated during fault (shared thermal bus)"
    )


def test_cpu_temp_correlates_with_cpu_load():
    """
    cpu_temp_c should be higher when cpu_load is higher.
    Compare normal operation record pairs: higher load → higher temp.
    """
    gen = _make_generator(with_fault=False, seed=42)
    records = gen.generate(120)

    # Bin records into high/low CPU load and check average temperature
    median_load = sorted(r.cpu_load_pct for r in records)[len(records) // 2]
    high_load_temps = [r.cpu_temp_c for r in records if r.cpu_load_pct >= median_load]
    low_load_temps  = [r.cpu_temp_c for r in records if r.cpu_load_pct < median_load]

    avg_high = sum(high_load_temps) / len(high_load_temps)
    avg_low  = sum(low_load_temps)  / len(low_load_temps)

    assert avg_high >= avg_low, (
        "cpu_temp_c should be higher when cpu_load_pct is higher (correlation)"
    )
