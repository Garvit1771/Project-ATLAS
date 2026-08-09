"""
ATLAS — Fault injection.

Computes per-tick fault offsets for each affected telemetry variable based on a
loaded ScenarioConfig. The injector is stateless — it maps a tick number to an
offset dict; the generator applies those offsets to the baseline values.

Progression model:
  - Before onset_tick: zero offset (no fault)
  - onset_tick to target_tick (ramp_ticks): linear ramp from 0 → signed_delta
  - After target_tick: constant at signed_delta (fault fully developed)

Secondary signals use the same linear-ramp model but start from their own
onset_tick. Their "target" is onset_tick + ramp_remaining, where ramp_remaining
= fault.target_tick - secondary.onset_tick (i.e. they join the ramp in progress).
This keeps secondary effects gradual and correlated with the primary fault arc.
"""

from __future__ import annotations

from backend.app.simulation.scenarios import FaultConfig, ScenarioConfig


class FaultInjector:
    """
    Computes signed telemetry offsets for a given tick based on a fault config.

    Usage:
        injector = FaultInjector(scenario.fault)
        offsets = injector.offsets_at_tick(tick)
        # offsets is a dict[str, float]: variable -> signed offset to add to baseline
    """

    def __init__(self, fault: FaultConfig) -> None:
        self._fault = fault

    # ── Public API ────────────────────────────────────────────────────────────

    def offsets_at_tick(self, tick: int) -> dict[str, float]:
        """
        Return the signed offset for each affected variable at this tick.
        Zero for variables not in the fault definition, or before their onset.
        """
        offsets: dict[str, float] = {}

        # Primary signals: linear ramp from onset_tick to target_tick
        primary_onset = self._fault.onset_tick
        primary_target = self._fault.target_tick
        primary_ramp = self._fault.ramp_ticks  # = target_tick - onset_tick

        for sig in self._fault.signals:
            offsets[sig.variable] = _linear_ramp(
                tick=tick,
                onset_tick=primary_onset,
                ramp_ticks=primary_ramp,
                signed_delta=sig.signed_delta,
            )

        # Secondary signals: linear ramp from their own onset_tick, completing
        # at the same target_tick as the primary fault.
        for sec in self._fault.secondary_signals:
            sec_ramp = max(1, primary_target - sec.onset_tick)
            offsets[sec.variable] = _linear_ramp(
                tick=tick,
                onset_tick=sec.onset_tick,
                ramp_ticks=sec_ramp,
                signed_delta=sec.signed_delta,
            )

        return offsets

    def is_fault_active(self, tick: int) -> bool:
        """Return True if the fault has started at this tick."""
        return tick >= self._fault.onset_tick


# ── Internal helpers ──────────────────────────────────────────────────────────

def _linear_ramp(
    tick: int,
    onset_tick: int,
    ramp_ticks: int,
    signed_delta: float,
) -> float:
    """
    Linear interpolation from 0 to signed_delta over ramp_ticks.

    Returns:
      0.0                     if tick < onset_tick
      signed_delta * progress if onset_tick <= tick <= onset_tick + ramp_ticks
      signed_delta            if tick > onset_tick + ramp_ticks
    """
    if tick < onset_tick:
        return 0.0
    elapsed = tick - onset_tick
    if elapsed >= ramp_ticks:
        return float(signed_delta)
    progress = elapsed / ramp_ticks
    return float(signed_delta) * progress
