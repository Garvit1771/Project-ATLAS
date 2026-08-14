"""
ATLAS — Phase 7 API integration tests.

Coverage map:
  A. API model validation
  B. Session lifecycle
  C. REST endpoint behaviour (synchronous, TestClient)
  D. SSE behaviour (real uvicorn server on ephemeral port)
  E. Granite fallback
  F. Mocked Granite
  G. End-to-end pipeline (200-tick fault arc)

Design principles:
  - Tests prove behaviour, not implementation details.
  - Every test asserts exactly what the specification requires.
  - The session is reset before and after any test that touches shared state.
  - SSE tests connect to a real uvicorn server over TCP so that the infinite
    StreamingResponse is served correctly and client disconnect propagates
    as a real OS-level socket close.  httpx.ASGITransport cannot be used for
    infinite SSE because it buffers the complete response body before
    returning the Response object, causing an unresolvable hang.
  - The Granite fallback tests use monkeypatch to replace session.granite_client
    with a no-credential client; no real network calls are made.
  - The Phase 0-6 regression baseline (307 passed, 3 skipped) must be
    preserved — these tests are purely additive.
"""

from __future__ import annotations

import json
import socket
import threading
import time
import warnings
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import MagicMock

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.ai.client import GraniteClient, _UNAVAILABLE
from backend.app.api import session as _session
from backend.app.api.models import (
    AnalysisStatusResponse,
    CopilotRequest,
    CopilotResponse,
    ExplanationResponse,
    TelemetrySnapshotResponse,
    WhatIfRequest,
    WhatIfResponse,
)
from backend.app.main import app

# ── Shared fixtures ────────────────────────────────────────────────────────────

@pytest.fixture()
def client() -> TestClient:
    """Synchronous TestClient — used for all REST (non-SSE) tests."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=False)
def reset_state():
    """
    Reset the simulation session before and after every test that uses it.

    Not autouse — applied explicitly to tests that advance or read state so
    that session state never leaks between tests.
    """
    _session.reset_session()
    yield
    _session.reset_session()


@pytest.fixture()
def seeded_state(reset_state):
    """
    Advance the simulation 200 ticks synchronously so REST endpoints have
    live state to return.  Uses _process_tick directly (the same function
    the SSE loop calls) to advance state without going through HTTP.
    """
    from backend.app.api.telemetry import _process_tick
    gen_iter = _session.generator.stream()
    for _ in range(200):
        _process_tick(gen_iter)
    yield


@pytest.fixture()
def mock_granite(monkeypatch):
    """
    Replace session.granite_client with a mock returning a known string.
    """
    mock_model = MagicMock()
    mock_model.generate.return_value = {
        "results": [{"generated_text": "Mocked Granite response."}]
    }
    monkeypatch.setattr(_session, "granite_client", GraniteClient(model=mock_model))


@pytest.fixture()
def no_cred_granite(monkeypatch):
    """
    Replace session.granite_client with a no-credential client that always
    returns the Phase 6 fallback message.
    """
    monkeypatch.setattr(_session, "granite_client", GraniteClient())


# ── Live uvicorn server fixture ───────────────────────────────────────────────

@pytest.fixture()
def live_atlas_server():
    """
    Start a real uvicorn HTTP server on an ephemeral localhost port for SSE
    testing.

    Why a real server instead of httpx.ASGITransport:
    ASGITransport.handle_async_request() calls ``await self.app(scope,
    receive, send)`` and does not return until the ASGI application
    completes.  For an intentionally infinite SSE StreamingResponse the app
    never completes, so ASGITransport hangs before the Response object is
    even constructed.  A real TCP server streams bytes as they are produced
    and honours client-side socket closure as a genuine disconnect signal,
    which is the correct production path.

    Port allocation:
    A temporary socket is bound to port 0 to let the OS choose a free
    ephemeral port.  The socket is closed before uvicorn starts, so there
    is a narrow TOCTOU window.  Startup failure is detected explicitly via
    the readiness poll (see below).

    Readiness detection:
    The fixture polls the TCP port until it accepts a connection or a 5-
    second deadline is exceeded.  This fires as soon as uvicorn's listener
    is live, typically within 200-400 ms.

    Teardown:
    server.should_exit = True is uvicorn's documented graceful-shutdown
    mechanism.  The fixture joins the thread with a 5-second timeout and
    calls pytest.fail() if the server has not terminated — daemon=False
    ensures no silent thread leaks.
    """
    # Step 1: allocate an ephemeral port.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    # sock is now closed; port number is known.

    # Step 2: reset session so every SSE test starts at tick 0.
    _session.reset_session()

    # Step 3: configure and create the uvicorn server.
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="error",   # suppress uvicorn access/startup logs in test output
        loop="asyncio",
    )
    server = uvicorn.Server(config)

    # Step 4: run the server in a non-daemon background thread.
    #   daemon=False means pytest will not silently abandon the thread —
    #   teardown explicitly joins it and fails loudly if it does not exit.
    thread = threading.Thread(target=server.run, daemon=False, name="atlas-uvicorn")
    thread.start()

    # Step 5: wait for uvicorn to accept TCP connections (bounded to 5 s).
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break   # port is accepting connections
        except OSError:
            time.sleep(0.05)
    else:
        # Server did not start in time — fail immediately so the thread is
        # not left running.
        server.should_exit = True
        thread.join(timeout=5)
        pytest.fail(
            f"uvicorn did not start accepting connections on port {port} "
            "within 5 seconds."
        )

    base_url = f"http://127.0.0.1:{port}"

    try:
        yield base_url
    finally:
        # Graceful shutdown: signal uvicorn, then wait for the thread to exit.
        server.should_exit = True
        thread.join(timeout=5)
        if thread.is_alive():
            pytest.fail(
                "uvicorn server failed to shut down within 5 seconds. "
                "This indicates a resource leak in the SSE generator."
            )
        # Reset session state so downstream fixtures start clean.
        _session.reset_session()


# ── SSE HTTP client helper ────────────────────────────────────────────────────

def _collect_n_events(base_url: str, n: int) -> list[dict]:
    """
    Connect to the live SSE endpoint over a real TCP socket, collect exactly
    n tick events, then close the connection.

    Uses synchronous httpx.Client (not ASGITransport) with explicit bounded
    timeouts so a misbehaving server cannot hang pytest.

    The ``break`` after collecting n events closes the underlying socket,
    which uvicorn propagates as an ``http.disconnect`` ASGI message.
    Starlette's StreamingResponse cancels the generator, which executes
    its ``finally:`` block and clears ``_stream_active``.
    """
    events: list[dict] = []
    timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
    with httpx.Client(timeout=timeout) as http_client:
        with http_client.stream("GET", f"{base_url}/api/telemetry/stream") as response:
            for line in response.iter_lines():
                if line.startswith("data:"):
                    events.append(json.loads(line[len("data:"):].strip()))
                    if len(events) >= n:
                        break
    return events


# ══════════════════════════════════════════════════════════════════════════════
# A — API model validation
# ══════════════════════════════════════════════════════════════════════════════

class TestAPIModels:
    """Pydantic model behaviour — no HTTP, no session."""

    def test_whatif_request_rejects_empty_string(self):
        with pytest.raises(ValidationError):
            WhatIfRequest(option_id="")

    def test_whatif_request_accepts_valid_option_id(self):
        req = WhatIfRequest(option_id="SWITCH_REDUNDANT")
        assert req.option_id == "SWITCH_REDUNDANT"

    def test_copilot_request_rejects_empty_string(self):
        with pytest.raises(ValidationError):
            CopilotRequest(question="")

    def test_copilot_request_accepts_nonempty_question(self):
        req = CopilotRequest(question="What is wrong?")
        assert req.question == "What is wrong?"

    def test_copilot_request_accepts_whitespace_string(self):
        # Pydantic min_length=1 allows "  " — route handler validates semantic emptiness.
        req = CopilotRequest(question="  ")
        assert req.question == "  "

    def test_whatif_response_has_correct_fields(self):
        from backend.app.models.decision import WhatIfResult
        wir = WhatIfResult(option_id="A", current_risk=0.5, projected_risk=0.3, delta=-0.2)
        resp = WhatIfResponse(what_if=wir, ai_narrative="narrative text")
        assert resp.what_if.delta == pytest.approx(-0.2)
        assert resp.ai_narrative == "narrative text"

    def test_copilot_response_has_answer_field(self):
        resp = CopilotResponse(answer="some answer")
        assert resp.answer == "some answer"


# ══════════════════════════════════════════════════════════════════════════════
# B — Session lifecycle
# ══════════════════════════════════════════════════════════════════════════════

class TestSessionLifecycle:
    """Session module behaviour — verified without going through HTTP."""

    def test_session_imports_without_error(self):
        # Import is enough; GraniteClient warning is expected and fine.
        import backend.app.api.session  # noqa: F401

    def test_maneuver_time_is_not_none(self):
        assert _session.MANEUVER_TIME is not None

    def test_maneuver_time_is_utc_aware(self):
        """Regression: naive datetime causes TypeError in time_pressure_factor."""
        assert _session.MANEUVER_TIME.tzinfo is not None

    def test_maneuver_time_correct_value(self):
        expected = datetime(2026, 8, 9, 2, 30, 0, tzinfo=timezone.utc)
        assert _session.MANEUVER_TIME == expected

    def test_maneuver_time_on_mission_context_is_utc_aware(self):
        assert _session.mission_context.next_maneuver_time is not None
        assert _session.mission_context.next_maneuver_time.tzinfo is not None

    def test_maneuver_time_on_mission_context_matches_constant(self):
        assert _session.mission_context.next_maneuver_time == _session.MANEUVER_TIME

    def test_mission_context_phase(self):
        assert _session.mission_context.phase == "orbital_insertion"

    def test_initial_state_is_none(self):
        _session.reset_session()
        assert _session.latest_record is None
        assert _session.latest_analytics is None
        assert _session.latest_risk is None

    def test_reset_session_clears_state(self):
        # Dirty state deliberately
        from backend.app.api.telemetry import _process_tick
        gen_iter = _session.generator.stream()
        _process_tick(gen_iter)
        assert _session.latest_record is not None
        _session.reset_session()
        assert _session.latest_record is None
        assert _session.latest_analytics is None
        assert _session.latest_risk is None

    def test_reset_session_clears_stream_active(self):
        with _session._state_lock:
            _session._stream_active = True
        _session.reset_session()
        assert _session._stream_active is False

    def test_reset_session_produces_tick_zero_next(self):
        _session.reset_session()
        record = next(_session.generator.stream())
        assert record.tick == 0

    def test_get_state_snapshot_returns_none_triple_initially(self):
        _session.reset_session()
        r, a, k = _session.get_state_snapshot()
        assert r is None
        assert a is None
        assert k is None

    def test_naive_maneuver_datetime_causes_type_error(self):
        """
        Regression: if next_maneuver_time were naive, time_pressure_factor
        would raise TypeError when subtracting from an aware timestamp.
        This test proves the UTC-aware construction prevents that error.
        """
        from backend.app.risk.scoring import time_pressure_factor
        # Aware current time — this is what TelemetryRecord.timestamp gives us
        aware_now = datetime(2026, 8, 9, 2, 0, 0, tzinfo=timezone.utc)

        # Confirm our MANEUVER_TIME works fine (no TypeError)
        result = time_pressure_factor(_session.MANEUVER_TIME, aware_now)
        assert isinstance(result, float)

        # Confirm naive datetime raises TypeError
        naive_dt = datetime(2026, 8, 9, 2, 30, 0)  # no tzinfo
        with pytest.raises(TypeError):
            time_pressure_factor(naive_dt, aware_now)


# ══════════════════════════════════════════════════════════════════════════════
# C — REST endpoint behaviour
# ══════════════════════════════════════════════════════════════════════════════

class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        r = client.get("/health")
        assert r.status_code == 200

    def test_health_body(self, client):
        r = client.get("/health")
        assert r.json() == {"status": "ok", "service": "ATLAS"}


class TestPreTickEndpoints:
    """All state-dependent endpoints return 503 before any tick is processed."""

    def test_snapshot_503_before_ticks(self, client, reset_state):
        r = client.get("/api/telemetry/snapshot")
        assert r.status_code == 503

    def test_snapshot_503_detail_contains_useful_message(self, client, reset_state):
        r = client.get("/api/telemetry/snapshot")
        assert "detail" in r.json()
        assert "stream" in r.json()["detail"].lower()

    def test_analysis_status_503_before_ticks(self, client, reset_state):
        r = client.get("/api/analysis/status")
        assert r.status_code == 503

    def test_decision_options_503_before_ticks(self, client, reset_state):
        r = client.get("/api/decision/options")
        assert r.status_code == 503

    def test_whatif_503_before_ticks(self, client, reset_state):
        r = client.post("/api/decision/whatif", json={"option_id": "SWITCH_REDUNDANT"})
        assert r.status_code == 503

    def test_copilot_503_before_ticks(self, client, reset_state):
        r = client.post("/api/copilot/ask", json={"question": "What is happening?"})
        assert r.status_code == 503


class TestInputValidation:
    """Input validation at the endpoint level."""

    def test_copilot_empty_string_422(self, client, reset_state):
        """Empty string fails Pydantic min_length=1 validation → 422."""
        r = client.post("/api/copilot/ask", json={"question": ""})
        assert r.status_code == 422

    def test_copilot_whitespace_only_400(self, client, seeded_state):
        """Whitespace-only passes Pydantic but is rejected by route handler → 400."""
        r = client.post("/api/copilot/ask", json={"question": "   "})
        assert r.status_code == 400
        assert "whitespace" in r.json()["detail"].lower()

    def test_whatif_empty_option_id_422(self, client, reset_state):
        """Empty option_id fails Pydantic min_length=1 → 422."""
        r = client.post("/api/decision/whatif", json={"option_id": ""})
        assert r.status_code == 422

    def test_whatif_unknown_option_id_400(self, client, seeded_state):
        """Unknown option_id → 400 from KeyError in DecisionEngine."""
        r = client.post("/api/decision/whatif", json={"option_id": "NO_SUCH_OPTION"})
        assert r.status_code == 400
        assert "NO_SUCH_OPTION" in r.json()["detail"]


class TestSnapshotEndpoint:
    def test_snapshot_200_with_state(self, client, seeded_state):
        r = client.get("/api/telemetry/snapshot")
        assert r.status_code == 200

    def test_snapshot_has_tick(self, client, seeded_state):
        r = client.get("/api/telemetry/snapshot")
        body = r.json()
        assert "tick" in body
        assert isinstance(body["tick"], int)

    def test_snapshot_has_timestamp(self, client, seeded_state):
        body = client.get("/api/telemetry/snapshot").json()
        assert "timestamp" in body

    def test_snapshot_has_telemetry(self, client, seeded_state):
        body = client.get("/api/telemetry/snapshot").json()
        assert "telemetry" in body

    def test_snapshot_telemetry_has_all_13_fields(self, client, seeded_state):
        body = client.get("/api/telemetry/snapshot").json()
        t = body["telemetry"]
        expected_fields = {
            "battery_voltage_v", "battery_temp_c", "solar_power_w",
            "cpu_temp_c", "cpu_load_pct",
            "thruster_1_temp_c", "thruster_2_temp_c",
            "thruster_2_vibration_hz", "thruster_2_efficiency_pct",
            "attitude_error_deg",
            "signal_strength_dbm", "packet_loss_pct",
            "radiation_level_mgy",
        }
        assert expected_fields.issubset(t.keys())

    def test_snapshot_tick_equals_199_after_200_ticks(self, client, seeded_state):
        """200 ticks means last tick index is 199."""
        body = client.get("/api/telemetry/snapshot").json()
        assert body["tick"] == 199


class TestAnalysisStatusEndpoint:
    def test_analysis_status_200_with_state(self, client, seeded_state):
        r = client.get("/api/analysis/status")
        assert r.status_code == 200

    def test_analysis_status_has_analytics_and_risk(self, client, seeded_state):
        body = client.get("/api/analysis/status").json()
        assert "analytics" in body
        assert "risk" in body

    def test_analytics_has_tick(self, client, seeded_state):
        body = client.get("/api/analysis/status").json()
        assert "tick" in body["analytics"]

    def test_risk_has_risk_score(self, client, seeded_state):
        body = client.get("/api/analysis/status").json()
        rs = body["risk"]["risk_score"]
        assert isinstance(rs, float)
        assert 0.0 <= rs <= 1.0

    def test_risk_has_severity(self, client, seeded_state):
        body = client.get("/api/analysis/status").json()
        assert "severity" in body["risk"]

    def test_analytics_tick_matches_risk_tick(self, client, seeded_state):
        body = client.get("/api/analysis/status").json()
        assert body["analytics"]["tick"] == body["risk"]["tick"]


class TestDecisionOptionsEndpoint:
    def test_decision_options_200_with_state(self, client, seeded_state):
        r = client.get("/api/decision/options")
        assert r.status_code == 200

    def test_decision_options_has_three_options(self, client, seeded_state):
        body = client.get("/api/decision/options").json()
        assert len(body["options"]) == 3

    def test_decision_options_sorted_ascending_by_projected_risk(self, client, seeded_state):
        body = client.get("/api/decision/options").json()
        scores = [o["computed_risk_score_after"] for o in body["options"]]
        assert scores == sorted(scores), "Options must be sorted ascending by projected risk"

    def test_decision_options_has_current_risk_score(self, client, seeded_state):
        body = client.get("/api/decision/options").json()
        crs = body["current_risk_score"]
        assert isinstance(crs, float)
        assert 0.0 <= crs <= 1.0

    def test_decision_options_no_field_named_risk_score_after_target(self, client, seeded_state):
        """This field is a test fixture only and must never appear in the API response."""
        body = client.get("/api/decision/options").json()
        for opt in body["options"]:
            assert "risk_score_after_target" not in opt


class TestWhatIfEndpoint:
    def test_whatif_200_valid_option(self, client, seeded_state):
        r = client.post("/api/decision/whatif", json={"option_id": "SWITCH_REDUNDANT"})
        assert r.status_code == 200

    def test_whatif_has_what_if_and_ai_narrative(self, client, seeded_state):
        body = client.post("/api/decision/whatif", json={"option_id": "SWITCH_REDUNDANT"}).json()
        assert "what_if" in body
        assert "ai_narrative" in body

    def test_whatif_has_required_subfields(self, client, seeded_state):
        wi = client.post("/api/decision/whatif", json={"option_id": "SWITCH_REDUNDANT"}).json()["what_if"]
        assert "option_id" in wi
        assert "current_risk" in wi
        assert "projected_risk" in wi
        assert "delta" in wi

    def test_whatif_delta_is_correct_arithmetic(self, client, seeded_state):
        wi = client.post("/api/decision/whatif", json={"option_id": "SWITCH_REDUNDANT"}).json()["what_if"]
        assert wi["delta"] == pytest.approx(wi["projected_risk"] - wi["current_risk"], abs=1e-9)

    def test_whatif_ai_narrative_is_string(self, client, seeded_state):
        body = client.post("/api/decision/whatif", json={"option_id": "SWITCH_REDUNDANT"}).json()
        assert isinstance(body["ai_narrative"], str)
        assert len(body["ai_narrative"]) > 0


class TestCopilotEndpoint:
    def test_copilot_200_valid_question(self, client, seeded_state):
        r = client.post("/api/copilot/ask", json={"question": "What is happening?"})
        assert r.status_code == 200

    def test_copilot_response_has_answer(self, client, seeded_state):
        body = client.post("/api/copilot/ask", json={"question": "Status?"}).json()
        assert "answer" in body
        assert isinstance(body["answer"], str)
        assert len(body["answer"]) > 0


# ══════════════════════════════════════════════════════════════════════════════
# D — SSE behaviour (real uvicorn server on ephemeral port)
# ══════════════════════════════════════════════════════════════════════════════

class TestSSEBehaviour:
    """
    All SSE tests connect to a real uvicorn HTTP server over TCP.

    httpx.ASGITransport cannot be used here: it buffers the entire ASGI
    response body before constructing a Response object.  For an intentionally
    infinite SSE StreamingResponse this means handle_async_request() never
    returns and the test hangs before any assertion is reached.

    A real TCP server streams bytes as produced.  Client-side ``break`` /
    socket close propagates as a genuine OS-level disconnect, which uvicorn
    delivers to Starlette as ``http.disconnect``, causing the generator's
    ``finally:`` block to execute.  This is the correct production disconnect
    path and cannot be replicated with an in-process ASGI transport.
    """

    def test_sse_status_200(self, live_atlas_server):
        """HTTP 200 is returned immediately when a client connects."""
        timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
        with httpx.Client(timeout=timeout) as http_client:
            with http_client.stream("GET", f"{live_atlas_server}/api/telemetry/stream") as response:
                assert response.status_code == 200
                for line in response.iter_lines():
                    if line.startswith("data:"):
                        break

    def test_sse_content_type_is_event_stream(self, live_atlas_server):
        """Content-Type header must be text/event-stream."""
        timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
        with httpx.Client(timeout=timeout) as http_client:
            with http_client.stream("GET", f"{live_atlas_server}/api/telemetry/stream") as response:
                ct = response.headers.get("content-type", "")
                assert "text/event-stream" in ct
                for line in response.iter_lines():
                    if line.startswith("data:"):
                        break

    def test_sse_events_are_framed_with_data_prefix(self, live_atlas_server):
        """Raw wire lines must include 'event:' and 'data:' framing."""
        data_lines = []
        timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
        with httpx.Client(timeout=timeout) as http_client:
            with http_client.stream("GET", f"{live_atlas_server}/api/telemetry/stream") as response:
                for line in response.iter_lines():
                    if line.startswith("event:") or line.startswith("data:"):
                        data_lines.append(line)
                    if len([l for l in data_lines if l.startswith("data:")]) >= 3:
                        break
        data_only = [l for l in data_lines if l.startswith("data:")]
        assert len(data_only) >= 3

    def test_sse_events_are_valid_json(self, live_atlas_server):
        events = _collect_n_events(live_atlas_server, 3)
        assert len(events) == 3
        for e in events:
            assert isinstance(e, dict)

    def test_sse_event_has_required_top_level_keys(self, live_atlas_server):
        events = _collect_n_events(live_atlas_server, 1)
        e = events[0]
        assert "tick" in e
        assert "timestamp" in e
        assert "telemetry" in e
        assert "analytics" in e
        assert "risk" in e

    def test_sse_telemetry_payload_has_all_13_fields(self, live_atlas_server):
        events = _collect_n_events(live_atlas_server, 1)
        t = events[0]["telemetry"]
        expected = {
            "battery_voltage_v", "battery_temp_c", "solar_power_w",
            "cpu_temp_c", "cpu_load_pct",
            "thruster_1_temp_c", "thruster_2_temp_c",
            "thruster_2_vibration_hz", "thruster_2_efficiency_pct",
            "attitude_error_deg",
            "signal_strength_dbm", "packet_loss_pct",
            "radiation_level_mgy",
        }
        assert expected.issubset(t.keys())

    def test_sse_analytics_payload_has_expected_fields(self, live_atlas_server):
        events = _collect_n_events(live_atlas_server, 1)
        a = events[0]["analytics"]
        assert "tick" in a
        assert "detections" in a
        assert "composite_anomaly" in a
        assert isinstance(a["composite_anomaly"], bool)

    def test_sse_risk_payload_has_expected_fields(self, live_atlas_server):
        events = _collect_n_events(live_atlas_server, 1)
        r = events[0]["risk"]
        assert "tick" in r
        assert "risk_score" in r
        assert "severity" in r
        rs = r["risk_score"]
        assert isinstance(rs, float)
        assert 0.0 <= rs <= 1.0

    def test_sse_ticks_are_sequential(self, live_atlas_server):
        """Consecutive events must have strictly consecutive tick numbers."""
        events = _collect_n_events(live_atlas_server, 5)
        ticks = [e["tick"] for e in events]
        assert ticks == list(range(len(ticks))), f"Expected sequential ticks, got {ticks}"

    def test_sse_telemetry_analytics_risk_tick_consistent(self, live_atlas_server):
        """tick value in telemetry, analytics, and risk must all be the same."""
        events = _collect_n_events(live_atlas_server, 3)
        for e in events:
            assert e["telemetry"]["tick"] == e["analytics"]["tick"]
            assert e["analytics"]["tick"] == e["risk"]["tick"]

    def test_sse_latest_state_updated_after_events(self, live_atlas_server):
        """After consuming N events the session.latest_* state must be updated."""
        events = _collect_n_events(live_atlas_server, 5)
        # Stream has been closed; latest state should reflect tick 4.
        r, a, k = _session.get_state_snapshot()
        assert r is not None
        assert r.tick == 4
        assert a is not None
        assert k is not None

    def test_sse_client_disconnect_clears_stream_active(self, live_atlas_server):
        """After client disconnects, _stream_active must be False (no leak)."""
        timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
        with httpx.Client(timeout=timeout) as http_client:
            with http_client.stream("GET", f"{live_atlas_server}/api/telemetry/stream") as response:
                for line in response.iter_lines():
                    if line.startswith("data:"):
                        break  # disconnect immediately after first event

        # Give uvicorn a brief moment to deliver the disconnect ASGI message
        # and execute the generator's finally block.  This is bounded — we
        # do not loop indefinitely.
        time.sleep(0.2)

        with _session._state_lock:
            active = _session._stream_active
        assert active is False, "_stream_active must be False after client disconnect"

    def test_sse_second_connection_returns_409(self, live_atlas_server):
        """A second SSE connection while one is active must return 409 Conflict."""
        timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
        with httpx.Client(timeout=timeout) as first_client:
            with first_client.stream(
                "GET", f"{live_atlas_server}/api/telemetry/stream"
            ) as first_response:
                # Advance the iterator once to confirm _stream_active=True.
                #
                # IMPORTANT: we retain `first_lines` as an explicit reference
                # throughout the second-connection block.  A bare `for/break`
                # loop abandons the iterator, which allows Python/httpx to GC
                # the underlying stream and close the TCP socket.  That TCP FIN
                # reaches uvicorn, triggers the generator's finally: block, and
                # clears _stream_active — so the second request sees False and
                # opens a new stream instead of returning 409.  Holding the
                # iterator alive keeps the TCP connection open for the duration
                # of the second request.
                first_lines = first_response.iter_lines()
                next(line for line in first_lines if line.startswith("data:"))

                # First stream is provably still open (_stream_active=True).
                # Attempt a second connection — must return 409 Conflict.
                with httpx.Client(timeout=timeout) as second_client:
                    r2 = second_client.get(
                        f"{live_atlas_server}/api/telemetry/stream"
                    )
                assert r2.status_code == 409

                # `first_lines` still holds the iterator; keep it referenced
                # until after the assertion so the compiler/GC cannot collect
                # it early.  The del is explicit documentation of intent.
                del first_lines

            # first_response context manager exits here, closing the TCP
            # connection and triggering the generator's finally: block.

        # Deterministically wait for the generator's finally: block to clear
        # _stream_active.  No public API exposes this signal — _stream_active
        # is the exact invariant being tested (single-operator enforcement), so
        # direct inspection is appropriate here.
        #
        # Bounded to 3 s; on a local uvicorn server the generator responds to
        # CancelledError at its next asyncio.sleep() checkpoint, typically
        # within one event-loop tick after the TCP disconnect is delivered.
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            with _session._state_lock:
                if not _session._stream_active:
                    break
            time.sleep(0.05)
        else:
            pytest.fail(
                "_stream_active was not cleared within 3 s after the first "
                "stream closed. This indicates the generator finally: block "
                "did not run."
            )

    def test_sse_no_concurrent_ticks(self, live_atlas_server):
        """
        Ticks must be strictly sequential — proof that _process_tick is never
        called concurrently.  Non-sequential ticks would indicate a race
        between two worker-thread invocations.
        """
        events = _collect_n_events(live_atlas_server, 10)
        ticks = [e["tick"] for e in events]
        assert ticks == list(range(10)), f"Non-sequential ticks indicate concurrency: {ticks}"


# ══════════════════════════════════════════════════════════════════════════════
# E — Granite fallback
# ══════════════════════════════════════════════════════════════════════════════

class TestGraniteFallback:
    """Verify that Granite unavailability never causes a 500 error."""

    def test_whatif_returns_200_when_granite_unavailable(
        self, client, seeded_state, no_cred_granite
    ):
        r = client.post("/api/decision/whatif", json={"option_id": "SWITCH_REDUNDANT"})
        assert r.status_code == 200

    def test_whatif_ai_narrative_is_fallback_string(
        self, client, seeded_state, no_cred_granite
    ):
        body = client.post("/api/decision/whatif", json={"option_id": "SWITCH_REDUNDANT"}).json()
        assert body["ai_narrative"] == _UNAVAILABLE

    def test_whatif_deterministic_result_present_even_with_fallback(
        self, client, seeded_state, no_cred_granite
    ):
        """Granite failure must not affect the deterministic what_if computation."""
        body = client.post("/api/decision/whatif", json={"option_id": "SWITCH_REDUNDANT"}).json()
        wi = body["what_if"]
        assert "delta" in wi
        assert isinstance(wi["delta"], float)

    def test_copilot_returns_200_when_granite_unavailable(
        self, client, seeded_state, no_cred_granite
    ):
        r = client.post("/api/copilot/ask", json={"question": "What is happening?"})
        assert r.status_code == 200

    def test_copilot_answer_is_fallback_string(
        self, client, seeded_state, no_cred_granite
    ):
        body = client.post("/api/copilot/ask", json={"question": "What is happening?"}).json()
        assert body["answer"] == _UNAVAILABLE


# ══════════════════════════════════════════════════════════════════════════════
# F — Mocked Granite
# ══════════════════════════════════════════════════════════════════════════════

class TestMockedGranite:
    """Verify that a successful Granite response is passed through correctly."""

    def test_whatif_ai_narrative_passes_through_granite_output(
        self, client, seeded_state, mock_granite
    ):
        body = client.post("/api/decision/whatif", json={"option_id": "SWITCH_REDUNDANT"}).json()
        assert body["ai_narrative"] == "Mocked Granite response."

    def test_copilot_answer_passes_through_granite_output(
        self, client, seeded_state, mock_granite
    ):
        body = client.post("/api/copilot/ask", json={"question": "Status?"}).json()
        assert body["answer"] == "Mocked Granite response."

    def test_granite_generate_called_for_whatif(
        self, client, seeded_state, monkeypatch
    ):
        """The mock's generate() must have been called exactly once."""
        mock_model = MagicMock()
        mock_model.generate.return_value = {
            "results": [{"generated_text": "Called."}]
        }
        monkeypatch.setattr(_session, "granite_client", GraniteClient(model=mock_model))
        client.post("/api/decision/whatif", json={"option_id": "SWITCH_REDUNDANT"})
        assert mock_model.generate.call_count == 1

    def test_granite_generate_called_for_copilot(
        self, client, seeded_state, monkeypatch
    ):
        mock_model = MagicMock()
        mock_model.generate.return_value = {
            "results": [{"generated_text": "Called."}]
        }
        monkeypatch.setattr(_session, "granite_client", GraniteClient(model=mock_model))
        client.post("/api/copilot/ask", json={"question": "Hello?"})
        assert mock_model.generate.call_count == 1


# ══════════════════════════════════════════════════════════════════════════════
# G — End-to-end pipeline (200-tick fault arc)
# ══════════════════════════════════════════════════════════════════════════════

class TestEndToEndPipeline:
    """
    After 200 ticks the FAULT-01 arc has fired:
      - Fault onset at tick 120
      - Analytics correlation detects by ~tick 170-180
      - At tick 199 the system should show elevated risk and composite anomaly.
    """

    def test_composite_anomaly_fires_by_200_ticks(self, seeded_state):
        """Layer 3 correlation must have fired at some point in the 200-tick run."""
        _, analytics, _ = _session.get_state_snapshot()
        assert analytics is not None
        # The analytics at tick 199 should show the composite anomaly
        assert analytics.composite_anomaly is True

    def test_risk_score_elevated_after_200_ticks(self, seeded_state):
        _, _, risk = _session.get_state_snapshot()
        assert risk is not None
        assert risk.risk_score > 0.3, f"Expected elevated risk, got {risk.risk_score}"

    def test_risk_severity_not_none_after_200_ticks(self, seeded_state):
        from backend.app.models.analytics import Severity
        _, _, risk = _session.get_state_snapshot()
        assert risk.severity != Severity.NONE

    def test_decision_options_three_items(self, client, seeded_state):
        body = client.get("/api/decision/options").json()
        assert len(body["options"]) == 3

    def test_decision_options_sorted_ascending(self, client, seeded_state):
        body = client.get("/api/decision/options").json()
        scores = [o["computed_risk_score_after"] for o in body["options"]]
        assert scores == sorted(scores)

    def test_switch_redundant_has_lowest_projected_risk(self, client, seeded_state):
        body = client.get("/api/decision/options").json()
        opts = {o["option_id"]: o for o in body["options"]}
        # SWITCH_REDUNDANT must strictly beat the alternatives.
        assert (
            opts["SWITCH_REDUNDANT"]["computed_risk_score_after"]
            < opts["REDUCE_LOAD"]["computed_risk_score_after"]
        )
        # REDUCE_LOAD and CONTINUE may score identically at tick 199 (the
        # deterministic engine produces equal projected risk for both at the
        # seed-42 / 200-tick state).  Assert non-strict ordering so the test
        # reflects actual engine behaviour rather than an assumed ranking.
        assert (
            opts["REDUCE_LOAD"]["computed_risk_score_after"]
            <= opts["CONTINUE"]["computed_risk_score_after"]
        )

    def test_whatif_switch_redundant_reduces_risk(self, client, seeded_state):
        body = client.post(
            "/api/decision/whatif", json={"option_id": "SWITCH_REDUNDANT"}
        ).json()
        assert body["what_if"]["delta"] < 0, "SWITCH_REDUNDANT must reduce risk"

    def test_whatif_continue_near_zero_delta(self, client, seeded_state):
        body = client.post(
            "/api/decision/whatif", json={"option_id": "CONTINUE"}
        ).json()
        # CONTINUE makes no state changes — projected risk ≈ current risk
        assert abs(body["what_if"]["delta"]) < 0.15

    def test_whatif_all_projected_risks_in_range(self, client, seeded_state):
        for opt_id in ("SWITCH_REDUNDANT", "REDUCE_LOAD", "CONTINUE"):
            body = client.post(
                "/api/decision/whatif", json={"option_id": opt_id}
            ).json()
            pr = body["what_if"]["projected_risk"]
            assert 0.0 <= pr <= 1.0, f"{opt_id}: projected_risk {pr} out of range"

    def test_correlated_signals_include_propulsion_variables(self, seeded_state):
        _, analytics, _ = _session.get_state_snapshot()
        assert analytics is not None
        propulsion_vars = {
            "thruster_2_vibration_hz",
            "thruster_2_temp_c",
            "thruster_2_efficiency_pct",
        }
        assert len(set(analytics.correlated_signals) & propulsion_vars) >= 2


# ══════════════════════════════════════════════════════════════════════════════
# H — Analysis explain endpoint (Phase 8 addition)
# ══════════════════════════════════════════════════════════════════════════════

class TestAnalysisExplainEndpoint:
    """
    Tests for GET /api/analysis/explain.

    This endpoint calls GraniteClient.explain_anomaly() using the same
    evidence-grounded prompt architecture as the Phase 6 copilot and
    what-if endpoints.  It is intentionally separate from /api/analysis/status
    so that Granite latency never blocks the SSE telemetry tick loop.
    """

    def test_explain_503_before_ticks(self, client, reset_state):
        """Endpoint must return 503 if the SSE stream has not produced a tick."""
        r = client.get("/api/analysis/explain")
        assert r.status_code == 503

    def test_explain_200_with_state_and_fallback(self, client, seeded_state, no_cred_granite):
        """Endpoint returns 200 even when Granite is unavailable (fallback)."""
        r = client.get("/api/analysis/explain")
        assert r.status_code == 200

    def test_explain_response_has_explanation_field(self, client, seeded_state, no_cred_granite):
        """Response must have an 'explanation' string field."""
        body = client.get("/api/analysis/explain").json()
        assert "explanation" in body
        assert isinstance(body["explanation"], str)
        assert len(body["explanation"]) > 0

    def test_explain_response_has_subsystem_field(self, client, seeded_state, no_cred_granite):
        """Response must include the 'subsystem' field derived from analytics state."""
        body = client.get("/api/analysis/explain").json()
        assert "subsystem" in body
        assert isinstance(body["subsystem"], str)
        assert len(body["subsystem"]) > 0

    def test_explain_fallback_is_unavailability_message(self, client, seeded_state, no_cred_granite):
        """When Granite is unavailable the explanation must be the fallback sentinel."""
        from backend.app.ai.client import _UNAVAILABLE
        body = client.get("/api/analysis/explain").json()
        assert body["explanation"] == _UNAVAILABLE

    def test_explain_mocked_granite_passes_through_text(self, client, seeded_state, mock_granite):
        """Mocked Granite response is passed through as the explanation."""
        body = client.get("/api/analysis/explain").json()
        assert body["explanation"] == "Mocked Granite response."

    def test_explain_subsystem_is_valid_string(self, client, seeded_state, no_cred_granite):
        """subsystem must be a non-empty string (e.g. 'propulsion')."""
        body = client.get("/api/analysis/explain").json()
        subsystem = body["subsystem"]
        assert isinstance(subsystem, str)
        assert len(subsystem) > 0
        # After 200 ticks with FAULT-01, composite_subsystem should be 'propulsion'
        assert subsystem == "propulsion"

    def test_explain_model_validates(self, client, seeded_state, no_cred_granite):
        """Response body must deserialise into ExplanationResponse without error."""
        body = client.get("/api/analysis/explain").json()
        resp = ExplanationResponse(**body)
        assert resp.explanation
        assert resp.subsystem
