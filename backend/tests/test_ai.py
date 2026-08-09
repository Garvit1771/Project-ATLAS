"""
ATLAS Phase 6 — test_ai.py
Comprehensive tests for the IBM Granite AI reasoning layer.

Coverage:
- GraniteClient: import, construction, configuration values
- GraniteClient: fallback when credentials absent (returns "unavailable" message)
- GraniteClient: mocked successful response returns the mocked text
- GraniteClient: is_available property
- GraniteClient: constructor injection pattern (mock model)
- build_anomaly_prompt: [EVIDENCE] block present, no procedures text, no numbers instruction
- build_decision_prompt: [EVIDENCE] block present, no procedures text, no ranking language,
                         explicit "Do NOT recommend" instruction present in template
- build_copilot_prompt: [EVIDENCE] block present, no procedures text
- Token limit constants: 300 / 400 / 250
- Temperature: <= 0.3
- KnowledgeContextLoader: loads spec and fault sections for propulsion subsystem
- KnowledgeContextLoader: NEVER loads procedures.md (raises ValueError on attempt)
- KnowledgeContextLoader: static mission profile sections loaded, current-state sections excluded
- KnowledgeContext.to_prompt_block(): renders non-empty fields correctly
- Live MissionContext values override static current-state fields in prompts
- Deterministic evidence preserved in fallback path (anomaly prompt still built)
- No procedures.md text present in any of the three prompt outputs
- Integration test (skipped by default): requires real credentials, marked with
  pytest.mark.integration and also pytest.mark.skip

No network calls are made in the normal test run.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ── Imports under test ─────────────────────────────────────────────────────────
from backend.app.ai.client import (
    GraniteClient,
    MAX_TOKENS_ANOMALY,
    MAX_TOKENS_DECISION,
    MAX_TOKENS_COPILOT,
    TEMPERATURE,
    _UNAVAILABLE,
    DEFAULT_MODEL_ID,
)
from backend.app.ai.prompts import (
    build_anomaly_prompt,
    build_decision_prompt,
    build_copilot_prompt,
)
from backend.app.ai.context import (
    KnowledgeContext,
    KnowledgeContextLoader,
    _extract_markdown_section,
    _extract_section_containing,
)
from backend.app.models.analytics import (
    AnalyticsResult,
    AnomalyDetection,
    Severity,
    DetectionMethod,
    ConfidenceBand,
    TrendDirection,
)
from backend.app.models.risk import RiskResult
from backend.app.models.decision import (
    DecisionOption,
    DecisionResult,
    RecommendationStrength,
)
from backend.app.models.mission import MissionContext


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def mission_context() -> MissionContext:
    return MissionContext(
        mission_name="ALPHA-1",
        mission_type="Lunar Orbiter",
        phase="orbital_insertion",
        next_maneuver_time=datetime(2026, 8, 9, 2, 30, 0),
        abort_window_minutes=8.0,
        thruster_1_active=True,
        thruster_2_active=True,
        thruster_3_active=False,
        redundancy_available=True,
        constraints=[
            "Maintain orbital insertion window",
            "Attitude within 0.5° of burn attitude",
        ],
        scenario_id="ALPHA1-FAULT-01",
    )


@pytest.fixture()
def propulsion_detection() -> AnomalyDetection:
    return AnomalyDetection(
        variable="thruster_2_vibration_hz",
        subsystem="propulsion",
        anomaly_detected=True,
        severity=Severity.HIGH,
        detection_method=DetectionMethod.ZSCORE_CORRELATION,
        z_score=4.1,
        confidence_value=0.90,
        confidence_band=ConfidenceBand.HIGH,
        trend_direction=TrendDirection.RISING,
        regression_slope=0.03,
        first_anomaly_tick=160,
        evidence=[
            "thruster_2_vibration_hz is statistically anomalous (z-score elevated)",
            "Vibration signal trending upward over the past 60 ticks",
        ],
    )


@pytest.fixture()
def temp_detection() -> AnomalyDetection:
    return AnomalyDetection(
        variable="thruster_2_temp_c",
        subsystem="propulsion",
        anomaly_detected=True,
        severity=Severity.MODERATE,
        detection_method=DetectionMethod.ROLLING_ZSCORE,
        z_score=3.2,
        confidence_value=0.55,
        confidence_band=ConfidenceBand.MODERATE,
        trend_direction=TrendDirection.RISING,
        regression_slope=0.25,
        first_anomaly_tick=165,
        evidence=[
            "thruster_2_temp_c is statistically anomalous (z-score elevated)",
        ],
    )


@pytest.fixture()
def analytics_result(propulsion_detection, temp_detection) -> AnalyticsResult:
    return AnalyticsResult(
        tick=180,
        detections=[propulsion_detection, temp_detection],
        composite_anomaly=True,
        composite_subsystem="propulsion",
        composite_severity=Severity.CRITICAL,
        composite_confidence_value=0.90,
        composite_confidence_band=ConfidenceBand.HIGH,
        correlated_signals=["thruster_2_vibration_hz", "thruster_2_temp_c", "thruster_2_efficiency_pct"],
    )


@pytest.fixture()
def analytics_result_no_anomaly() -> AnalyticsResult:
    return AnalyticsResult(tick=50, detections=[])


@pytest.fixture()
def risk_result() -> RiskResult:
    return RiskResult(
        tick=180,
        risk_score=0.71,
        severity=Severity.HIGH,
        estimated_threshold_breach_minutes=22.5,
        dominant_variable="thruster_2_vibration_hz",
        redundancy_available=True,
    )


@pytest.fixture()
def decision_result() -> DecisionResult:
    options = [
        DecisionOption(
            option_id="SWITCH_REDUNDANT",
            label="Switch to Redundant Thruster 3",
            description="Deactivate Thruster 2 and transfer burn to Redundant Thruster 3.",
            computed_risk_score_after=0.18,
            recommendation_strength=RecommendationStrength.STRONG,
            fuel_cost_pct=7.0,
            time_delay_min=4.0,
            mission_constraint_satisfied=True,
            subsystem_stress=["propulsion"],
        ),
        DecisionOption(
            option_id="REDUCE_LOAD",
            label="Reduce Thruster 2 load by 30%",
            description="Reduce burn output to decrease thermal and mechanical stress.",
            computed_risk_score_after=0.45,
            recommendation_strength=RecommendationStrength.MODERATE,
            fuel_cost_pct=2.0,
            time_delay_min=2.0,
            mission_constraint_satisfied=True,
            subsystem_stress=["propulsion"],
        ),
        DecisionOption(
            option_id="CONTINUE",
            label="Continue current operation",
            description="Maintain current thruster configuration and monitor.",
            computed_risk_score_after=0.73,
            recommendation_strength=RecommendationStrength.WEAK,
            fuel_cost_pct=0.0,
            time_delay_min=0.0,
            mission_constraint_satisfied=True,
            subsystem_stress=["propulsion"],
        ),
    ]
    return DecisionResult(
        tick=180,
        options=options,
        current_risk_score=0.71,
        fault_type="thruster_degradation",
        mission_phase="orbital_insertion",
    )


@pytest.fixture()
def knowledge_context() -> KnowledgeContext:
    return KnowledgeContext(
        subsystem_spec="Thruster 2 nominal temperature 180–220 °C; nominal vibration 0.5–2.0 Hz.",
        fault_mode_info="FAULT-01: rising vibration and temperature; declining efficiency.",
        mission_profile="ALPHA-1 Lunar Orbiter — 90-day primary mission.",
        mission_priorities="1. Complete orbital insertion. 2. Maintain spacecraft health.",
    )


@pytest.fixture()
def mock_model() -> MagicMock:
    """A MagicMock that mimics ibm-watsonx-ai ModelInference.generate()."""
    m = MagicMock()
    m.generate.return_value = {
        "results": [{"generated_text": "Mocked Granite response."}]
    }
    return m


# ─────────────────────────────────────────────────────────────────────────────
# GraniteClient — configuration tests
# ─────────────────────────────────────────────────────────────────────────────

class TestGraniteClientConfiguration:
    def test_token_limit_anomaly(self):
        assert MAX_TOKENS_ANOMALY == 300

    def test_token_limit_decision(self):
        assert MAX_TOKENS_DECISION == 400

    def test_token_limit_copilot(self):
        assert MAX_TOKENS_COPILOT == 250

    def test_temperature_lte_0_3(self):
        assert TEMPERATURE <= 0.3

    def test_default_model_id(self):
        assert DEFAULT_MODEL_ID == "ibm/granite-3-8b-instruct"

    def test_client_stores_temperature(self):
        client = GraniteClient(model=MagicMock())
        assert client.temperature <= 0.3

    def test_client_stores_token_limits(self):
        client = GraniteClient(model=MagicMock())
        assert client.max_tokens_anomaly  == MAX_TOKENS_ANOMALY
        assert client.max_tokens_decision == MAX_TOKENS_DECISION
        assert client.max_tokens_copilot  == MAX_TOKENS_COPILOT

    def test_client_model_id_default(self):
        client = GraniteClient(model=MagicMock())
        assert client.model_id == DEFAULT_MODEL_ID

    def test_client_model_id_override(self):
        client = GraniteClient(model_id="ibm/granite-3-3b-instruct", model=MagicMock())
        assert client.model_id == "ibm/granite-3-3b-instruct"

    def test_client_model_id_from_env(self, monkeypatch):
        monkeypatch.setenv("WATSONX_MODEL_ID", "ibm/granite-13b-instruct-v2")
        # No injected model, no API key → falls back gracefully
        client = GraniteClient()
        assert client.model_id == "ibm/granite-13b-instruct-v2"


# ─────────────────────────────────────────────────────────────────────────────
# GraniteClient — fallback behaviour (no credentials)
# ─────────────────────────────────────────────────────────────────────────────

class TestGraniteClientFallback:
    """Tests that verify the client degrades gracefully when unavailable."""

    def _make_no_cred_client(self, monkeypatch) -> GraniteClient:
        """Create a client with all credential env vars cleared."""
        monkeypatch.delenv("WATSONX_API_KEY",    raising=False)
        monkeypatch.delenv("WATSONX_PROJECT_ID", raising=False)
        monkeypatch.delenv("WATSONX_URL",         raising=False)
        monkeypatch.delenv("WATSONX_MODEL_ID",    raising=False)
        return GraniteClient()

    def test_no_credentials_is_not_available(self, monkeypatch):
        client = self._make_no_cred_client(monkeypatch)
        assert client.is_available is False

    def test_explain_anomaly_fallback_returns_unavailable_message(self, monkeypatch):
        client = self._make_no_cred_client(monkeypatch)
        result = client.explain_anomaly("any prompt")
        assert result == _UNAVAILABLE

    def test_narrate_decision_fallback_returns_unavailable_message(self, monkeypatch):
        client = self._make_no_cred_client(monkeypatch)
        result = client.narrate_decision("any prompt")
        assert result == _UNAVAILABLE

    def test_answer_copilot_fallback_returns_unavailable_message(self, monkeypatch):
        client = self._make_no_cred_client(monkeypatch)
        result = client.answer_copilot("any prompt")
        assert result == _UNAVAILABLE

    def test_fallback_is_not_fabricated_text(self, monkeypatch):
        """The fallback message must be explicit 'unavailable', not invented AI text."""
        client = self._make_no_cred_client(monkeypatch)
        result = client.explain_anomaly("test")
        assert "unavailable" in result.lower()
        # Must NOT look like a fabricated explanation
        assert len(result) < 200, "Fallback should be a short explicit message"


# ─────────────────────────────────────────────────────────────────────────────
# GraniteClient — mocked successful responses
# ─────────────────────────────────────────────────────────────────────────────

class TestGraniteClientMockedResponses:
    def test_explain_anomaly_returns_mocked_text(self, mock_model):
        client = GraniteClient(model=mock_model)
        result = client.explain_anomaly("test prompt")
        assert result == "Mocked Granite response."

    def test_narrate_decision_returns_mocked_text(self, mock_model):
        client = GraniteClient(model=mock_model)
        result = client.narrate_decision("test prompt")
        assert result == "Mocked Granite response."

    def test_answer_copilot_returns_mocked_text(self, mock_model):
        client = GraniteClient(model=mock_model)
        result = client.answer_copilot("test prompt")
        assert result == "Mocked Granite response."

    def test_explain_anomaly_passes_correct_max_tokens(self, mock_model):
        client = GraniteClient(model=mock_model)
        client.explain_anomaly("prompt")
        call_kwargs = mock_model.generate.call_args[1]
        assert call_kwargs["params"]["max_new_tokens"] == MAX_TOKENS_ANOMALY

    def test_narrate_decision_passes_correct_max_tokens(self, mock_model):
        client = GraniteClient(model=mock_model)
        client.narrate_decision("prompt")
        call_kwargs = mock_model.generate.call_args[1]
        assert call_kwargs["params"]["max_new_tokens"] == MAX_TOKENS_DECISION

    def test_answer_copilot_passes_correct_max_tokens(self, mock_model):
        client = GraniteClient(model=mock_model)
        client.answer_copilot("prompt")
        call_kwargs = mock_model.generate.call_args[1]
        assert call_kwargs["params"]["max_new_tokens"] == MAX_TOKENS_COPILOT

    def test_generate_passes_temperature(self, mock_model):
        client = GraniteClient(model=mock_model)
        client.explain_anomaly("prompt")
        call_kwargs = mock_model.generate.call_args[1]
        assert call_kwargs["params"]["temperature"] <= 0.3

    def test_is_available_true_with_injected_model(self, mock_model):
        client = GraniteClient(model=mock_model)
        assert client.is_available is True

    def test_generate_returns_fallback_when_model_raises(self, mock_model):
        mock_model.generate.side_effect = RuntimeError("connection timeout")
        client = GraniteClient(model=mock_model)
        result = client.explain_anomaly("prompt")
        assert result == _UNAVAILABLE

    def test_generate_returns_fallback_when_empty_text(self, mock_model):
        mock_model.generate.return_value = {"results": [{"generated_text": ""}]}
        client = GraniteClient(model=mock_model)
        result = client.explain_anomaly("prompt")
        assert result == _UNAVAILABLE


# ─────────────────────────────────────────────────────────────────────────────
# build_anomaly_prompt
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildAnomalyPrompt:
    def test_evidence_block_present(self, analytics_result, risk_result, mission_context, knowledge_context):
        prompt = build_anomaly_prompt(analytics_result, risk_result, mission_context, knowledge_context)
        assert "[EVIDENCE]" in prompt

    def test_evidence_contains_detection_statements(self, analytics_result, risk_result, mission_context, knowledge_context):
        prompt = build_anomaly_prompt(analytics_result, risk_result, mission_context, knowledge_context)
        # Evidence items from the fixture detections should appear
        assert "thruster_2_vibration_hz" in prompt

    def test_evidence_contains_composite_correlation(self, analytics_result, risk_result, mission_context, knowledge_context):
        prompt = build_anomaly_prompt(analytics_result, risk_result, mission_context, knowledge_context)
        assert "correlation" in prompt.lower()

    def test_no_numbers_instruction_present(self, analytics_result, risk_result, mission_context, knowledge_context):
        prompt = build_anomaly_prompt(analytics_result, risk_result, mission_context, knowledge_context)
        assert "numerical values" in prompt or "specific numerical" in prompt

    def test_grounding_rule_present(self, analytics_result, risk_result, mission_context, knowledge_context):
        prompt = build_anomaly_prompt(analytics_result, risk_result, mission_context, knowledge_context)
        assert "Base your explanation only on the evidence" in prompt

    def test_no_procedures_content(self, analytics_result, risk_result, mission_context, knowledge_context):
        prompt = build_anomaly_prompt(analytics_result, risk_result, mission_context, knowledge_context)
        _assert_no_procedures_text(prompt)

    def test_no_procedures_keywords(self, analytics_result, risk_result, mission_context, knowledge_context):
        prompt = build_anomaly_prompt(analytics_result, risk_result, mission_context, knowledge_context)
        # Key phrases that appear in procedures.md but not in other knowledge files
        for phrase in ["PROC-PROP-01", "Apply if anomaly", "escalate to Option C"]:
            assert phrase not in prompt

    def test_mission_context_phase_present(self, analytics_result, risk_result, mission_context, knowledge_context):
        prompt = build_anomaly_prompt(analytics_result, risk_result, mission_context, knowledge_context)
        assert mission_context.phase in prompt

    def test_mission_context_mission_name_present(self, analytics_result, risk_result, mission_context, knowledge_context):
        prompt = build_anomaly_prompt(analytics_result, risk_result, mission_context, knowledge_context)
        assert mission_context.mission_name in prompt

    def test_no_anomaly_prompt_still_builds(self, analytics_result_no_anomaly, risk_result, mission_context, knowledge_context):
        # Should not raise even when there are no detections
        risk = RiskResult(
            tick=50, risk_score=0.05, severity=Severity.NONE,
            estimated_threshold_breach_minutes=None,
            dominant_variable=None, redundancy_available=True,
        )
        prompt = build_anomaly_prompt(analytics_result_no_anomaly, risk, mission_context, knowledge_context)
        assert "[EVIDENCE]" in prompt

    def test_prompt_is_non_empty_string(self, analytics_result, risk_result, mission_context, knowledge_context):
        prompt = build_anomaly_prompt(analytics_result, risk_result, mission_context, knowledge_context)
        assert isinstance(prompt, str) and len(prompt) > 50


# ─────────────────────────────────────────────────────────────────────────────
# build_decision_prompt
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildDecisionPrompt:
    def test_evidence_block_present(self, decision_result, analytics_result, risk_result, mission_context, knowledge_context):
        prompt = build_decision_prompt(decision_result, analytics_result, risk_result, mission_context, knowledge_context)
        assert "[EVIDENCE]" in prompt

    def test_evidence_contains_option_labels(self, decision_result, analytics_result, risk_result, mission_context, knowledge_context):
        prompt = build_decision_prompt(decision_result, analytics_result, risk_result, mission_context, knowledge_context)
        for option in decision_result.options:
            assert option.label in prompt

    def test_evidence_contains_fuel_cost_band(self, decision_result, analytics_result, risk_result, mission_context, knowledge_context):
        prompt = build_decision_prompt(decision_result, analytics_result, risk_result, mission_context, knowledge_context)
        # Fuel costs are expressed as qualitative bands
        assert "fuel" in prompt.lower() or "cost" in prompt.lower()

    def test_evidence_contains_mission_constraint(self, decision_result, analytics_result, risk_result, mission_context, knowledge_context):
        prompt = build_decision_prompt(decision_result, analytics_result, risk_result, mission_context, knowledge_context)
        assert "constraint" in prompt.lower()

    def test_no_ranking_instruction_present(self, decision_result, analytics_result, risk_result, mission_context, knowledge_context):
        """The prompt template must contain the explicit anti-ranking instruction."""
        prompt = build_decision_prompt(decision_result, analytics_result, risk_result, mission_context, knowledge_context)
        assert "Do NOT recommend" in prompt or "Do not recommend" in prompt

    def test_human_operator_decides_instruction_present(self, decision_result, analytics_result, risk_result, mission_context, knowledge_context):
        prompt = build_decision_prompt(decision_result, analytics_result, risk_result, mission_context, knowledge_context)
        assert "human operator" in prompt.lower()

    def test_prompt_does_not_itself_rank_options(self, decision_result, analytics_result, risk_result, mission_context, knowledge_context):
        """The prompt TEMPLATE itself must not use recommendation language."""
        prompt = build_decision_prompt(decision_result, analytics_result, risk_result, mission_context, knowledge_context)
        lower = prompt.lower()
        # These phrases should not appear in the fixed template text
        # (they are forbidden by the Granite Prompt Contract)
        forbidden = ["recommend option", "best option", "you should choose", "the preferred option"]
        for phrase in forbidden:
            assert phrase not in lower, f"Prompt template contains forbidden phrase: '{phrase}'"

    def test_no_procedures_content(self, decision_result, analytics_result, risk_result, mission_context, knowledge_context):
        prompt = build_decision_prompt(decision_result, analytics_result, risk_result, mission_context, knowledge_context)
        _assert_no_procedures_text(prompt)

    def test_no_procedures_step_language(self, decision_result, analytics_result, risk_result, mission_context, knowledge_context):
        prompt = build_decision_prompt(decision_result, analytics_result, risk_result, mission_context, knowledge_context)
        for phrase in ["PROC-PROP-01", "Step 1 —", "Step 2 —", "escalate to Option C"]:
            assert phrase not in prompt

    def test_grounding_rule_present(self, decision_result, analytics_result, risk_result, mission_context, knowledge_context):
        prompt = build_decision_prompt(decision_result, analytics_result, risk_result, mission_context, knowledge_context)
        assert "Base your explanation only on the evidence" in prompt

    def test_no_numbers_instruction_present(self, decision_result, analytics_result, risk_result, mission_context, knowledge_context):
        prompt = build_decision_prompt(decision_result, analytics_result, risk_result, mission_context, knowledge_context)
        assert "numerical values" in prompt or "specific numerical" in prompt

    def test_options_presented_in_pre_ranked_order(self, decision_result, analytics_result, risk_result, mission_context, knowledge_context):
        """Options must appear in the order provided (pre-ranked ascending by risk)."""
        prompt = build_decision_prompt(decision_result, analytics_result, risk_result, mission_context, knowledge_context)
        idx_first  = prompt.index(decision_result.options[0].label)
        idx_second = prompt.index(decision_result.options[1].label)
        idx_third  = prompt.index(decision_result.options[2].label)
        assert idx_first < idx_second < idx_third

    def test_prompt_is_non_empty_string(self, decision_result, analytics_result, risk_result, mission_context, knowledge_context):
        prompt = build_decision_prompt(decision_result, analytics_result, risk_result, mission_context, knowledge_context)
        assert isinstance(prompt, str) and len(prompt) > 50


# ─────────────────────────────────────────────────────────────────────────────
# build_copilot_prompt
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildCopilotPrompt:
    def test_evidence_block_present(self, analytics_result, risk_result, mission_context, knowledge_context):
        prompt = build_copilot_prompt("What is wrong with Thruster 2?", analytics_result, risk_result, mission_context, knowledge_context)
        assert "[EVIDENCE]" in prompt

    def test_question_present_in_prompt(self, analytics_result, risk_result, mission_context, knowledge_context):
        question = "What is wrong with Thruster 2?"
        prompt = build_copilot_prompt(question, analytics_result, risk_result, mission_context, knowledge_context)
        assert question in prompt

    def test_no_procedures_content(self, analytics_result, risk_result, mission_context, knowledge_context):
        prompt = build_copilot_prompt("How long until breach?", analytics_result, risk_result, mission_context, knowledge_context)
        _assert_no_procedures_text(prompt)

    def test_grounding_rule_present(self, analytics_result, risk_result, mission_context, knowledge_context):
        prompt = build_copilot_prompt("Test?", analytics_result, risk_result, mission_context, knowledge_context)
        assert "Base your explanation only on the evidence" in prompt

    def test_no_numbers_instruction_present(self, analytics_result, risk_result, mission_context, knowledge_context):
        prompt = build_copilot_prompt("Test?", analytics_result, risk_result, mission_context, knowledge_context)
        assert "numerical values" in prompt or "specific numerical" in prompt

    def test_mission_phase_present(self, analytics_result, risk_result, mission_context, knowledge_context):
        prompt = build_copilot_prompt("What phase are we in?", analytics_result, risk_result, mission_context, knowledge_context)
        assert mission_context.phase in prompt

    def test_composite_correlation_present_when_detected(self, analytics_result, risk_result, mission_context, knowledge_context):
        prompt = build_copilot_prompt("Q?", analytics_result, risk_result, mission_context, knowledge_context)
        # analytics_result has composite_anomaly=True with correlated signals
        assert "correlation" in prompt.lower() or "thruster_2_vibration_hz" in prompt

    def test_prompt_is_non_empty_string(self, analytics_result, risk_result, mission_context, knowledge_context):
        prompt = build_copilot_prompt("Q?", analytics_result, risk_result, mission_context, knowledge_context)
        assert isinstance(prompt, str) and len(prompt) > 50


# ─────────────────────────────────────────────────────────────────────────────
# KnowledgeContextLoader
# ─────────────────────────────────────────────────────────────────────────────

class TestKnowledgeContextLoader:
    """These tests use the actual knowledge files on disk."""

    @pytest.fixture()
    def loader(self) -> KnowledgeContextLoader:
        return KnowledgeContextLoader()

    def test_loader_constructs(self, loader):
        assert loader is not None

    def test_load_propulsion_returns_knowledge_context(self, loader, mission_context):
        kc = loader.load("propulsion", mission_context)
        assert isinstance(kc, KnowledgeContext)

    def test_propulsion_spec_section_loaded(self, loader, mission_context):
        kc = loader.load("propulsion", mission_context)
        assert len(kc.subsystem_spec) > 0, "Propulsion spec section should be non-empty"

    def test_propulsion_spec_contains_thruster_info(self, loader, mission_context):
        kc = loader.load("propulsion", mission_context)
        assert "thruster" in kc.subsystem_spec.lower() or "propulsion" in kc.subsystem_spec.lower()

    def test_propulsion_fault_mode_loaded(self, loader, mission_context):
        kc = loader.load("propulsion", mission_context)
        assert len(kc.fault_mode_info) > 0, "Fault mode section should be non-empty for propulsion"

    def test_fault_mode_contains_fault01_info(self, loader, mission_context):
        kc = loader.load("propulsion", mission_context)
        assert "vibration" in kc.fault_mode_info.lower() or "degradation" in kc.fault_mode_info.lower()

    def test_mission_profile_loaded(self, loader, mission_context):
        kc = loader.load("propulsion", mission_context)
        assert len(kc.mission_profile) > 0

    def test_mission_priorities_loaded(self, loader, mission_context):
        kc = loader.load("propulsion", mission_context)
        assert len(kc.mission_priorities) > 0

    def test_procedures_md_raises_value_error(self, loader):
        """Attempting to read procedures.md must raise ValueError."""
        with pytest.raises(ValueError, match="procedures.md"):
            loader._read_file("procedures.md")

    def test_procedures_md_not_in_spec_content(self, loader, mission_context):
        """No procedures.md content should leak into the loaded context."""
        kc = loader.load("propulsion", mission_context)
        full_text = kc.to_prompt_block()
        _assert_no_procedures_text(full_text)

    def test_static_current_state_section_excluded(self, loader, mission_context):
        """The 'Current Mission State' section from mission_context.md must not be loaded."""
        kc = loader.load("propulsion", mission_context)
        # This section heading is explicitly blocked
        assert "Current Mission State" not in kc.mission_profile
        # Verify the static section content (specific time strings) from mission_context.md
        # that appear ONLY in "Current Mission State" are absent
        assert "02:38 UTC" not in kc.mission_profile

    def test_unknown_subsystem_returns_empty_spec(self, loader, mission_context):
        kc = loader.load("unknown_subsystem", mission_context)
        assert kc.subsystem_spec == ""
        assert kc.fault_mode_info == ""

    def test_power_subsystem_loads_spec(self, loader, mission_context):
        kc = loader.load("power", mission_context)
        assert len(kc.subsystem_spec) > 0

    def test_comms_subsystem_loads_spec(self, loader, mission_context):
        kc = loader.load("comms", mission_context)
        assert len(kc.subsystem_spec) > 0


# ─────────────────────────────────────────────────────────────────────────────
# KnowledgeContext.to_prompt_block
# ─────────────────────────────────────────────────────────────────────────────

class TestKnowledgeContextToPromptBlock:
    def test_empty_context_returns_no_knowledge_message(self):
        kc = KnowledgeContext()
        block = kc.to_prompt_block()
        assert "no additional knowledge context" in block.lower()

    def test_non_empty_fields_appear_in_block(self, knowledge_context):
        block = knowledge_context.to_prompt_block()
        assert "SUBSYSTEM SPECIFICATION" in block
        assert "KNOWN FAULT MODE" in block
        assert "MISSION PROFILE" in block
        assert "MISSION PRIORITIES" in block

    def test_empty_fields_omitted_from_block(self):
        kc = KnowledgeContext(subsystem_spec="Some spec.")
        block = kc.to_prompt_block()
        assert "KNOWN FAULT MODE" not in block
        assert "MISSION PROFILE" not in block
        assert "Some spec." in block


# ─────────────────────────────────────────────────────────────────────────────
# Live MissionContext overrides static current-state fields in prompts
# ─────────────────────────────────────────────────────────────────────────────

class TestLiveMissionContextOverride:
    def test_anomaly_prompt_uses_live_phase(self, analytics_result, risk_result, knowledge_context):
        """Live MissionContext.phase appears in the prompt, not a static string from .md."""
        ctx = MissionContext(phase="transit")  # non-default phase
        prompt = build_anomaly_prompt(analytics_result, risk_result, ctx, knowledge_context)
        assert "transit" in prompt

    def test_anomaly_prompt_uses_live_thruster_state(self, analytics_result, risk_result, knowledge_context):
        ctx = MissionContext(thruster_2_active=False, thruster_3_active=True)
        prompt = build_anomaly_prompt(analytics_result, risk_result, ctx, knowledge_context)
        # thruster_3 should show as "active" in the prompt
        assert "active" in prompt.lower()

    def test_decision_prompt_uses_live_phase(self, decision_result, analytics_result, risk_result, knowledge_context):
        ctx = MissionContext(phase="science_operations")
        prompt = build_decision_prompt(decision_result, analytics_result, risk_result, ctx, knowledge_context)
        assert "science_operations" in prompt

    def test_decision_prompt_uses_live_redundancy_state(self, decision_result, analytics_result, risk_result, knowledge_context):
        ctx = MissionContext(redundancy_available=False)
        prompt = build_decision_prompt(decision_result, analytics_result, risk_result, ctx, knowledge_context)
        assert "no" in prompt.lower()

    def test_copilot_prompt_uses_live_phase(self, analytics_result, risk_result, knowledge_context):
        ctx = MissionContext(phase="reentry")
        prompt = build_copilot_prompt("Q?", analytics_result, risk_result, ctx, knowledge_context)
        assert "reentry" in prompt

    def test_next_maneuver_time_injected_from_live_context(self, analytics_result, risk_result, knowledge_context):
        ctx = MissionContext(next_maneuver_time=datetime(2026, 8, 9, 14, 45, 0))
        prompt = build_anomaly_prompt(analytics_result, risk_result, ctx, knowledge_context)
        assert "14:45" in prompt


# ─────────────────────────────────────────────────────────────────────────────
# Markdown parsing helpers
# ─────────────────────────────────────────────────────────────────────────────

class TestMarkdownParsing:
    _doc = """\
# Top Level

## Section A

Content A line 1.
Content A line 2.

## Section B

Content B.

### Subsection B1

Sub content.

## Section C

Content C.
"""

    def test_extract_section_a(self):
        result = _extract_markdown_section(self._doc, "Section A")
        assert "Content A line 1." in result
        assert "Content A line 2." in result
        assert "Content B" not in result

    def test_extract_section_b_stops_at_same_level(self):
        result = _extract_markdown_section(self._doc, "Section B")
        assert "Content B." in result
        assert "Content A" not in result
        assert "Content C" not in result

    def test_extract_subsection_b1(self):
        result = _extract_markdown_section(self._doc, "Subsection B1")
        assert "Sub content." in result
        assert "Content B." not in result

    def test_extract_nonexistent_section_returns_empty(self):
        result = _extract_markdown_section(self._doc, "Section Z")
        assert result == ""

    def test_extract_section_containing_keyword(self):
        result = _extract_section_containing(self._doc, "Content B")
        assert "Content B." in result
        assert "Content A" not in result


# ─────────────────────────────────────────────────────────────────────────────
# Procedures exclusion — end-to-end cross-prompt check
# ─────────────────────────────────────────────────────────────────────────────

class TestNoProceduressInAnyPrompt:
    """
    Exhaustive check: procedures.md text must not appear in any of the three
    prompt types under any circumstances.
    """
    def test_all_three_prompts_exclude_procedures(
        self,
        analytics_result,
        risk_result,
        decision_result,
        mission_context,
    ):
        # Use the real loader to build a knowledge context that actually reads disk
        loader = KnowledgeContextLoader()
        kc = loader.load("propulsion", mission_context)

        anomaly_prompt   = build_anomaly_prompt(analytics_result, risk_result, mission_context, kc)
        decision_prompt  = build_decision_prompt(decision_result, analytics_result, risk_result, mission_context, kc)
        copilot_prompt   = build_copilot_prompt("What is happening?", analytics_result, risk_result, mission_context, kc)

        for name, prompt in [
            ("anomaly", anomaly_prompt),
            ("decision", decision_prompt),
            ("copilot", copilot_prompt),
        ]:
            _assert_no_procedures_text(prompt, context=name)


# ─────────────────────────────────────────────────────────────────────────────
# Integration test (skipped by default)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.skip(reason="Integration test — requires real watsonx.ai credentials. Run with -m integration.")
@pytest.mark.integration
class TestGraniteIntegration:
    """
    Live integration test. Requires WATSONX_API_KEY and WATSONX_PROJECT_ID
    environment variables to be set.

    Run explicitly:
        WATSONX_API_KEY=... WATSONX_PROJECT_ID=... pytest -m integration backend/tests/test_ai.py
    """

    def test_live_anomaly_explanation(self, analytics_result, risk_result, mission_context):
        loader = KnowledgeContextLoader()
        kc     = loader.load("propulsion", mission_context)
        prompt = build_anomaly_prompt(analytics_result, risk_result, mission_context, kc)
        client = GraniteClient()
        assert client.is_available, "No credentials configured — cannot run integration test"
        result = client.explain_anomaly(prompt)
        assert isinstance(result, str)
        assert result != _UNAVAILABLE
        assert len(result) > 20

    def test_live_decision_narrative(self, decision_result, analytics_result, risk_result, mission_context):
        loader = KnowledgeContextLoader()
        kc     = loader.load("propulsion", mission_context)
        prompt = build_decision_prompt(decision_result, analytics_result, risk_result, mission_context, kc)
        client = GraniteClient()
        assert client.is_available
        result = client.narrate_decision(prompt)
        assert isinstance(result, str)
        assert result != _UNAVAILABLE
        assert len(result) > 20

    def test_live_copilot_response(self, analytics_result, risk_result, mission_context):
        loader = KnowledgeContextLoader()
        kc     = loader.load("propulsion", mission_context)
        prompt = build_copilot_prompt("What is wrong with Thruster 2?", analytics_result, risk_result, mission_context, kc)
        client = GraniteClient()
        assert client.is_available
        result = client.answer_copilot(prompt)
        assert isinstance(result, str)
        assert result != _UNAVAILABLE
        assert len(result) > 20


# ─────────────────────────────────────────────────────────────────────────────
# Helper — shared procedures.md text exclusion checker
# ─────────────────────────────────────────────────────────────────────────────

# Key phrases from procedures.md that must never appear in prompts.
_PROCEDURES_SENTINEL_PHRASES = [
    "PROC-PROP-01",
    "PROC-PWR-01",
    "PROC-COMM-01",
    "Apply if anomaly is MODERATE",
    "Apply if anomaly is HIGH",
    "escalate to Option C",
    "Step 1 — Assess severity",
    "Step 2 — Evaluate options",
    "Step 3 — Execute selected option",
    "Acceptable only if anomaly is LOW",
]


def _assert_no_procedures_text(prompt: str, context: str = "") -> None:
    """Assert that none of the procedures.md sentinel phrases appear in the prompt."""
    label = f"[{context}] " if context else ""
    for phrase in _PROCEDURES_SENTINEL_PHRASES:
        assert phrase not in prompt, (
            f"{label}procedures.md sentinel phrase found in prompt: '{phrase}'"
        )
