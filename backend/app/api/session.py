"""
ATLAS — Phase 7 shared session state.

Single-process, single-operator architecture: one scenario, one simulation,
one analytics engine, one operator.  All state is module-level so that the
SSE stream and every REST endpoint share the same running simulation.

Thread-safety
-------------
The event loop is single (uvicorn workers=1), but FastAPI dispatches
synchronous route handlers via run_in_threadpool — meaning sync REST
handlers and the SSE process_tick function can execute concurrently in
different anyio worker threads.

A single threading.Lock (_state_lock) protects:
  - latest_record, latest_analytics, latest_risk  (the consistent triple)
  - _stream_active                                  (SSE exclusion flag)

Rules enforced throughout this module and in all callers:
  - Expensive work (simulation, analytics, risk) happens OUTSIDE the lock.
  - The lock is acquired only for atomic reads/writes of the state triple.
  - The lock is never held across any await, sleep, I/O, or Granite call.
  - reset_session() acquires the lock to reset all state atomically.

next_maneuver_utc
-----------------
The scenario file stores "02:30" — a time-only string with no date.
We construct a UTC-aware datetime using the same reference date as
TelemetryGenerator._REFERENCE_START (2026-08-09).  This must be
timezone-aware so that time_pressure_factor() can subtract it from the
timezone-aware record timestamps without raising TypeError.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Optional

from backend.app.ai.client import GraniteClient
from backend.app.ai.context import KnowledgeContextLoader
from backend.app.analytics.engine import AnalyticsEngine
from backend.app.decision.engine import DecisionEngine
from backend.app.models.analytics import AnalyticsResult
from backend.app.models.mission import MissionContext
from backend.app.models.risk import RiskResult
from backend.app.models.telemetry import TelemetryRecord
from backend.app.risk.engine import RiskEngine
from backend.app.simulation.generator import TelemetryGenerator
from backend.app.simulation.scenarios import ScenarioConfig, load_scenario

# ── Scenario — loaded once at import time ────────────────────────────────────

scenario: ScenarioConfig = load_scenario("ALPHA1-FAULT-01")

# ── next_maneuver_utc → UTC-aware datetime ───────────────────────────────────
#
# The scenario stores "02:30" (HH:MM, no date).  The reference date
# 2026-08-09 comes from TelemetryGenerator._REFERENCE_START, ensuring
# timestamps produced by the generator are consistent with the maneuver time.
#
# The datetime MUST carry tzinfo=timezone.utc so that subtraction from the
# timezone-aware TelemetryRecord.timestamp never raises TypeError.

_REF_DATE = datetime(2026, 8, 9, tzinfo=timezone.utc)
_h, _m = map(int, scenario.next_maneuver_utc.split(":"))
MANEUVER_TIME: datetime = _REF_DATE.replace(
    hour=_h, minute=_m, second=0, microsecond=0
)

# ── Mission context ──────────────────────────────────────────────────────────

mission_context: MissionContext = MissionContext(
    phase=scenario.phase,
    next_maneuver_time=MANEUVER_TIME,
    abort_window_minutes=scenario.abort_window_minutes,
    scenario_id=scenario.scenario_id,
)

# ── Stateless / scenario-bound engines ──────────────────────────────────────

risk_engine: RiskEngine = RiskEngine()
decision_engine: DecisionEngine = DecisionEngine(scenario)
granite_client: GraniteClient = GraniteClient()
knowledge_loader: KnowledgeContextLoader = KnowledgeContextLoader()

# ── Stateful objects reset between runs ─────────────────────────────────────

def _make_generator() -> TelemetryGenerator:
    """Create a fresh TelemetryGenerator at tick 0 with the fixed seed."""
    return TelemetryGenerator(scenario=scenario, seed=42)


generator: TelemetryGenerator = _make_generator()
analytics_engine: AnalyticsEngine = AnalyticsEngine()

# ── Shared mutable state ─────────────────────────────────────────────────────
#
# These three are written atomically (under _state_lock) by process_tick and
# read (also under _state_lock) by REST endpoint handlers.  They start as None
# — any endpoint that depends on them must return 503 if still None.

latest_record: Optional[TelemetryRecord] = None
latest_analytics: Optional[AnalyticsResult] = None
latest_risk: Optional[RiskResult] = None

# ── Concurrency primitives ───────────────────────────────────────────────────

_state_lock: threading.Lock = threading.Lock()

# True while an SSE stream is actively driving the simulation.
# Protected by _state_lock.  A second SSE connection while this is True
# receives HTTP 409 — enforcing the single-operator contract.
_stream_active: bool = False


# ── State snapshot helper ────────────────────────────────────────────────────

def get_state_snapshot() -> tuple[
    Optional[TelemetryRecord],
    Optional[AnalyticsResult],
    Optional[RiskResult],
]:
    """
    Return a consistent (record, analytics, risk) triple from the same tick.

    Acquires _state_lock briefly for the read, then releases before returning.
    Callers must check for None before using the values.
    """
    with _state_lock:
        return latest_record, latest_analytics, latest_risk


# ── Reset ────────────────────────────────────────────────────────────────────

def reset_session() -> None:
    """
    Reset simulation to tick 0.

    Resets the generator and analytics engine state, clears the latest_*
    triple, and clears _stream_active.  Called from test fixtures; never
    exposed as an HTTP endpoint.

    Acquires _state_lock for the full reset to ensure no partial state is
    visible to concurrent readers during the transition.
    """
    global generator, analytics_engine, latest_record, latest_analytics, latest_risk, _stream_active

    with _state_lock:
        generator = _make_generator()
        analytics_engine = AnalyticsEngine()
        latest_record = None
        latest_analytics = None
        latest_risk = None
        _stream_active = False
