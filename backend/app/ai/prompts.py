"""
ATLAS — Prompt builders for IBM Granite.

Three prompt builders per docs/methodology.md Section 7 (Granite Prompt Contract):

1. build_anomaly_prompt   — max 300 tokens
2. build_decision_prompt  — max 400 tokens
3. build_copilot_prompt   — max 250 tokens

Rules enforced in every prompt:
- [EVIDENCE] block derived from analytics/decision outputs (not fabricated).
- Instructs Granite: "Base your explanation only on the evidence in the [EVIDENCE]
  block. If the evidence is insufficient, say so explicitly."
- Instructs Granite: no specific numerical values in output.
- Decision prompt explicitly forbids ranking/recommendation language.
- procedures.md text is NEVER injected into any prompt.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.app.models.analytics import AnalyticsResult
    from backend.app.models.risk import RiskResult
    from backend.app.models.decision import DecisionResult
    from backend.app.models.mission import MissionContext
    from backend.app.ai.context import KnowledgeContext


# ── Shared instruction footer ─────────────────────────────────────────────────

_GROUNDING_RULE = (
    "Base your explanation only on the evidence in the [EVIDENCE] block. "
    "If the evidence is insufficient, say so explicitly."
)

_NO_NUMBERS_RULE = (
    "Do not state specific numerical values in your response. "
    "Refer to trends and conditions qualitatively only."
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Anomaly explanation prompt
# ─────────────────────────────────────────────────────────────────────────────

def build_anomaly_prompt(
    analytics_result: "AnalyticsResult",
    risk_result: "RiskResult",
    mission_context: "MissionContext",
    knowledge_context: "KnowledgeContext",
) -> str:
    """
    Build a prompt asking Granite to explain an anomaly in natural language.

    Token budget: 300 (MAX_TOKENS_ANOMALY in client.py).
    procedures.md text is NOT included.
    """
    # ── [EVIDENCE] block ──────────────────────────────────────────────────────
    evidence_lines: list[str] = []

    for detection in analytics_result.detections:
        for stmt in detection.evidence:
            evidence_lines.append(f"  - {stmt}")
        if detection.trend_direction:
            evidence_lines.append(
                f"  - {detection.variable}: trend is {detection.trend_direction.value}"
            )

    if analytics_result.composite_anomaly:
        sigs = ", ".join(analytics_result.correlated_signals)
        evidence_lines.append(
            f"  - Cross-signal correlation detected across propulsion subsystem "
            f"signals: {sigs}"
        )
        if analytics_result.composite_severity:
            evidence_lines.append(
                f"  - Composite anomaly severity: {analytics_result.composite_severity.value}"
            )
        if analytics_result.composite_confidence_band:
            evidence_lines.append(
                f"  - Composite detection confidence: {analytics_result.composite_confidence_band.value}"
            )

    # Risk context
    evidence_lines.append(
        f"  - Overall risk severity: {risk_result.severity.value}"
    )
    if risk_result.dominant_variable:
        evidence_lines.append(
            f"  - Dominant contributing variable: {risk_result.dominant_variable}"
        )
    evidence_lines.append(
        f"  - Redundant system available: {'yes' if risk_result.redundancy_available else 'no'}"
    )

    evidence_block = "\n".join(evidence_lines) if evidence_lines else "  (no anomalies detected)"

    # ── Mission context block ─────────────────────────────────────────────────
    mission_block = _format_mission_context(mission_context)

    # ── Knowledge context block ───────────────────────────────────────────────
    knowledge_block = _format_knowledge_context(knowledge_context)

    return f"""\
You are ATLAS, an AI explanation module for a spacecraft mission-control system.
Your role is to explain anomaly evidence to a human operator in clear, concise language.

[MISSION CONTEXT]
{mission_block}

[SPACECRAFT KNOWLEDGE]
{knowledge_block}

[EVIDENCE]
{evidence_block}

[INSTRUCTIONS]
{_GROUNDING_RULE}
{_NO_NUMBERS_RULE}
Explain what the evidence indicates about the current spacecraft health and why it matters for this mission phase.
Keep your explanation under 200 words.
Do not suggest actions or procedures — the operator uses a separate decision support panel for that.

[EXPLANATION]
""".strip()


# ─────────────────────────────────────────────────────────────────────────────
# 2. Decision narrative prompt
# ─────────────────────────────────────────────────────────────────────────────

def build_decision_prompt(
    decision_result: "DecisionResult",
    analytics_result: "AnalyticsResult",
    risk_result: "RiskResult",
    mission_context: "MissionContext",
    knowledge_context: "KnowledgeContext",
) -> str:
    """
    Build a prompt asking Granite to describe the tradeoffs of each decision option.

    Token budget: 400 (MAX_TOKENS_DECISION in client.py).
    Options are pre-ranked by computed_risk_score_after ascending (lowest risk first)
    before this function is called — Granite receives them in that order.
    procedures.md text is NOT included.

    Explicit prohibition: Granite must NOT recommend, rank, prioritise, or use
    language that implies one option is preferable to another.
    """
    # ── [EVIDENCE] block ──────────────────────────────────────────────────────
    evidence_lines: list[str] = []

    # Current risk context
    evidence_lines.append(f"  - Current mission phase: {mission_context.phase}")
    evidence_lines.append(
        f"  - Overall risk severity before action: {risk_result.severity.value}"
    )
    if risk_result.dominant_variable:
        evidence_lines.append(
            f"  - Dominant anomalous variable: {risk_result.dominant_variable}"
        )

    # Per-option evidence (pre-ranked, presented as received — no re-ordering)
    for option in decision_result.options:
        evidence_lines.append(f"  - Option [{option.label}]:")
        evidence_lines.append(
            f"      Projected risk category: {option.recommendation_strength.value}"
        )
        evidence_lines.append(
            f"      Additional fuel cost: {_pct_band(option.fuel_cost_pct)}"
        )
        evidence_lines.append(
            f"      Mission timeline impact: {_time_band(option.time_delay_min)}"
        )
        evidence_lines.append(
            f"      Mission constraints satisfied: {'yes' if option.mission_constraint_satisfied else 'no'}"
        )
        if option.subsystem_stress:
            evidence_lines.append(
                f"      Systems under increased stress: {', '.join(option.subsystem_stress)}"
            )

    evidence_block = "\n".join(evidence_lines)

    # ── Mission context block ─────────────────────────────────────────────────
    mission_block = _format_mission_context(mission_context)

    # ── Knowledge context block ───────────────────────────────────────────────
    knowledge_block = _format_knowledge_context(knowledge_context)

    return f"""\
You are ATLAS, an AI explanation module for a spacecraft mission-control system.
Your role is to describe the operational tradeoffs of each decision option to a human operator.

[MISSION CONTEXT]
{mission_block}

[SPACECRAFT KNOWLEDGE]
{knowledge_block}

[EVIDENCE]
{evidence_block}

[INSTRUCTIONS]
{_GROUNDING_RULE}
{_NO_NUMBERS_RULE}
Describe the tradeoffs of each option as presented in the [EVIDENCE] block.
Do NOT recommend, rank, prioritise, or use language that implies one option is preferable to another.
The human operator makes the final decision.
Describe what each option does to the spacecraft state and what operational consequences follow from it.
Keep your response under 300 words.

[TRADEOFF ANALYSIS]
""".strip()


# ─────────────────────────────────────────────────────────────────────────────
# 3. Copilot Q&A prompt
# ─────────────────────────────────────────────────────────────────────────────

def build_copilot_prompt(
    question: str,
    analytics_result: "AnalyticsResult",
    risk_result: "RiskResult",
    mission_context: "MissionContext",
    knowledge_context: "KnowledgeContext",
) -> str:
    """
    Build a prompt for a stateless operator Q&A response.

    Token budget: 250 (MAX_TOKENS_COPILOT in client.py).
    Each question is independent (no conversation history).
    procedures.md text is NOT included.
    """
    # ── [EVIDENCE] block — abbreviated for context ────────────────────────────
    evidence_lines: list[str] = []

    evidence_lines.append(f"  - Mission phase: {mission_context.phase}")
    evidence_lines.append(f"  - Risk severity: {risk_result.severity.value}")
    if risk_result.dominant_variable:
        evidence_lines.append(
            f"  - Dominant anomalous variable: {risk_result.dominant_variable}"
        )

    for detection in analytics_result.detections:
        for stmt in detection.evidence:
            evidence_lines.append(f"  - {stmt}")

    if analytics_result.composite_anomaly:
        sigs = ", ".join(analytics_result.correlated_signals)
        evidence_lines.append(
            f"  - Cross-signal correlation across: {sigs}"
        )

    evidence_block = "\n".join(evidence_lines) if evidence_lines else "  (no active anomalies)"

    # ── Mission context block ─────────────────────────────────────────────────
    mission_block = _format_mission_context(mission_context)

    # ── Knowledge context block ───────────────────────────────────────────────
    knowledge_block = _format_knowledge_context(knowledge_context)

    return f"""\
You are ATLAS Copilot, an AI assistant for spacecraft mission-control operators.
Answer the operator's question using only the provided evidence and context.

[MISSION CONTEXT]
{mission_block}

[SPACECRAFT KNOWLEDGE]
{knowledge_block}

[EVIDENCE]
{evidence_block}

[OPERATOR QUESTION]
{question}

[INSTRUCTIONS]
{_GROUNDING_RULE}
{_NO_NUMBERS_RULE}
Answer concisely. If you cannot answer from the available evidence, say so explicitly.
Do not suggest specific procedures or actions.
Keep your answer under 150 words.

[ANSWER]
""".strip()


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _format_mission_context(mission_context: "MissionContext") -> str:
    """Format the live MissionContext fields into a readable block."""
    lines = [
        f"Mission: {mission_context.mission_name} ({mission_context.mission_type})",
        f"Current phase: {mission_context.phase}",
    ]
    if mission_context.next_maneuver_time:
        lines.append(f"Next critical maneuver: {mission_context.next_maneuver_time.strftime('%H:%M UTC')}")
    lines.append(f"Abort window: {mission_context.abort_window_minutes} minutes")
    lines.append(
        f"Thruster 1: {'active' if mission_context.thruster_1_active else 'inactive'}, "
        f"Thruster 2: {'active' if mission_context.thruster_2_active else 'inactive'}, "
        f"Thruster 3: {'active' if mission_context.thruster_3_active else 'standby'}"
    )
    lines.append(
        f"Redundant system available: {'yes' if mission_context.redundancy_available else 'no'}"
    )
    if mission_context.constraints:
        lines.append("Active constraints: " + "; ".join(mission_context.constraints))
    return "\n".join(lines)


def _format_knowledge_context(knowledge_context: "KnowledgeContext") -> str:
    """Render a KnowledgeContext dict/object into a readable block."""
    if hasattr(knowledge_context, "to_prompt_block"):
        return knowledge_context.to_prompt_block()
    # Fallback: treat as dict
    parts: list[str] = []
    kc = knowledge_context if isinstance(knowledge_context, dict) else vars(knowledge_context)
    for section, content in kc.items():
        if content:
            parts.append(f"[{section.upper()}]\n{content}")
    return "\n\n".join(parts) if parts else "(no additional knowledge context)"


def _pct_band(pct: float) -> str:
    """Convert a fuel cost percentage to a qualitative band (no raw number in prompt)."""
    if pct == 0.0:
        return "none"
    if pct <= 2.0:
        return "minor"
    if pct <= 5.0:
        return "moderate"
    return "significant"


def _time_band(minutes: float) -> str:
    """Convert a time delay to a qualitative band (no raw number in prompt)."""
    if minutes == 0.0:
        return "none"
    if minutes <= 2.0:
        return "minor"
    if minutes <= 5.0:
        return "moderate"
    return "significant"
