# ATLAS — Master Implementation Plan

**Version:** 1.0  
**Date:** August 8, 2026  
**Deadline:** August 31, 2026  
**Status:** ACTIVE

---

## Overview

This plan governs the phased implementation of Project ATLAS from scaffold through competition submission. Each phase is a self-contained unit of work. Phases are implemented sequentially. No phase begins until the previous phase passes its acceptance criteria.

**Implementation mode:** IBM Bob in Agent mode, one phase at a time, with human review after each phase.

---

## Phase 0 — Project Scaffold

**Status:** [ ] pending

**Intent:** Create the complete repository structure — all directories, config files, skeleton entry points, data files, and knowledge documents — so that every subsequent phase has a stable place to put its work.

**Expected Outcomes:**
- Repository has the full directory structure defined in `docs/architecture.md` Section 7
- All placeholder/skeleton files exist (not implemented, but present)
- `data/normal_ranges.json` contains the operating envelope for all 13 telemetry variables
- `data/scenarios/alpha1_fault_01.json` contains the FAULT-01 scenario parameters
- All four knowledge Markdown files exist in `backend/knowledge/`
- `.gitignore`, `LICENSE`, and `README.md` are in place
- Frontend scaffold (package.json, vite.config.js, App.jsx skeleton) is initialised

**Todo List:**

*Already complete from Plan mode session:*
- [x] `backend/requirements.txt`
- [x] `backend/knowledge/spacecraft_spec.md`
- [x] `backend/knowledge/fault_modes.md`
- [x] `backend/knowledge/procedures.md`
- [x] `backend/knowledge/mission_context.md`
- [x] `data/normal_ranges_PENDING.txt` → content ready for `data/normal_ranges.json`
- [x] `data/scenarios/alpha1_fault_01_PENDING.txt` → content ready for `data/scenarios/alpha1_fault_01.json`

*To be completed in Agent mode:*
1. Create `.gitignore` (Python + Node + OS rules)
2. Create `LICENSE` (MIT)
3. Create `backend/app/__init__.py`
4. Create `backend/app/main.py` (FastAPI skeleton — no routes)
5. Create `backend/app/api/__init__.py`
6. Create `backend/app/analytics/__init__.py`
7. Create `backend/app/ai/__init__.py`
8. Create `backend/app/decision/__init__.py`
9. Create `backend/app/simulation/__init__.py`
10. Create `backend/app/models/__init__.py`
11. Create `backend/tests/__init__.py`
12. Create `data/normal_ranges.json` (use content from `data/normal_ranges_PENDING.txt`, then delete PENDING file)
13. Create `data/scenarios/alpha1_fault_01.json` (use content from `data/scenarios/alpha1_fault_01_PENDING.txt`, then delete PENDING file)
14. Create `frontend/package.json` (React 18 + Vite 5 + Tailwind + Recharts)
15. Create `frontend/vite.config.js`
16. Create `frontend/index.html`
17. Create `frontend/tailwind.config.js`
18. Create `frontend/postcss.config.js`
19. Create `frontend/src/App.jsx` (skeleton — no panels implemented)
20. Create `frontend/src/main.jsx`
21. Create `frontend/src/index.css` (Tailwind directives)
22. Create `frontend/src/components/.gitkeep`
23. Create `frontend/src/pages/.gitkeep`
24. Create `frontend/src/services/.gitkeep`

**Relevant Context:**
- Directory structure: `docs/architecture.md` Section 7
- Variable definitions: `docs/architecture.md` Section 4
- FAULT-01 scenario: `docs/architecture.md` Section 5
- Risk weights: `docs/methodology.md` Section 4

---

## Phase 1 — Telemetry Schema & Pydantic Models

**Status:** [ ] pending

**Intent:** Define the canonical data models for all telemetry records, analytics outputs, risk outputs, and decision outputs. All subsequent phases depend on these schemas.

**Expected Outcomes:**
- `backend/app/models/telemetry.py` — `TelemetryRecord` Pydantic model (13 fields)
- `backend/app/models/analytics.py` — `AnalyticsResult`, `AnomalyDetection` models
- `backend/app/models/risk.py` — `RiskResult` model
- `backend/app/models/decision.py` — `DecisionOption`, `DecisionResult` models
- `backend/app/models/mission.py` — `MissionContext` dataclass
- All models importable and passing Pytest schema tests
- `backend/tests/test_models.py` written and passing

**Relevant Context:**
- Schema definitions: `docs/architecture.md` Sections 3.2 and 4
- Analytics output schema: `docs/methodology.md` end of Section 2
- Decision output schema: `docs/methodology.md` Section 5
- Source tag enum: `docs/methodology.md` Section 8

---

## Phase 2 — Telemetry Simulator & Fault Injection

**Status:** [ ] pending

**Intent:** Build the telemetry generator that produces physically plausible, correlated telemetry records at 1 Hz, with support for parameterised fault injection.

**Expected Outcomes:**
- `backend/app/simulation/generator.py` — `TelemetryGenerator` class
- `backend/app/simulation/fault_injection.py` — `FaultInjector` class
- `backend/app/simulation/scenarios.py` — scenario loader from JSON config
- Simulator produces `TelemetryRecord` instances matching the Pydantic schema
- ALPHA-1-FAULT-01 scenario: normal for 120 ticks, then thruster 2 vibration/temp rise and efficiency drop over 60 ticks
- Physical correlations implemented (cpu_load → cpu_temp, thruster efficiency → cpu_load, etc.)
- `backend/tests/test_simulator.py` written and passing (run for 300 ticks, verify fault behaviour)

**Relevant Context:**
- Variable list and correlations: `docs/architecture.md` Section 4
- FAULT-01 parameters: `data/scenarios/alpha1_fault_01.json`
- Normal ranges: `data/normal_ranges.json`

---

## Phase 3 — Analytics Engine

**Status:** [ ] pending

**Intent:** Implement the three-layer anomaly detection cascade and feature engineering on the telemetry rolling buffer.

**Expected Outcomes:**
- `backend/app/analytics/features.py` — rolling stats, z-score, delta, trend direction
- `backend/app/analytics/detector.py` — hard threshold, z-score, correlation detection
- `backend/app/analytics/engine.py` — orchestrates feature engineering + detection cascade
- Engine accepts a rolling buffer (deque of `TelemetryRecord`) and returns `List[AnalyticsResult]`
- `backend/tests/test_analytics.py` — verify each detection layer fires correctly on synthetic data; verify no false positives on normal data

**Relevant Context:**
- Formulas: `docs/methodology.md` Sections 1–3
- Correlation rules: `data/normal_ranges.json` under `"correlation_rules"`
- Z-score thresholds: `docs/methodology.md` Section 2

---

## Phase 4 — Risk Engine

**Status:** [ ] pending

**Intent:** Implement the weighted composite risk formula and time-to-breach estimation.

**Expected Outcomes:**
- `backend/app/analytics/risk.py` — `RiskEngine` class
- Accepts `List[AnalyticsResult]` + `MissionContext` + current telemetry state
- Returns `RiskResult` with risk_score, severity, estimated_threshold_breach_minutes
- Weights loaded from `data/normal_ranges.json`
- `backend/tests/test_risk.py` — verify score increases correctly as severity/correlation increases

**Relevant Context:**
- Formula: `docs/methodology.md` Section 4
- `RiskResult` schema: Phase 1 output

---

## Phase 5 — Decision Support Engine & What-If

**Status:** [ ] pending

**Intent:** Implement deterministic option scoring, ranking, and what-if re-scoring.

**Expected Outcomes:**
- `backend/app/decision/engine.py` — `DecisionEngine` class
- Loads option configs from `data/scenarios/alpha1_fault_01.json`
- Evaluates each option, applies state deltas, re-runs risk engine for what-if
- Returns `DecisionResult` with sorted options and what-if projections
- **Granite does NOT participate in this phase — purely deterministic**
- `backend/tests/test_decision.py` — verify options are ranked correctly for FAULT-01

**Relevant Context:**
- Option scoring schema: `docs/methodology.md` Section 5
- What-if method: `docs/methodology.md` Section 6
- Granite contract: `docs/methodology.md` Section 7

---

## Phase 6 — IBM Granite AI Reasoning Layer

**Status:** [ ] pending

**Intent:** Integrate IBM Granite via watsonx.ai for anomaly explanation, decision narration, and Copilot Q&A. Verify latency. Establish fallback.

**Expected Outcomes:**
- `backend/app/ai/client.py` — `GraniteClient` wrapping `ibm-watsonx-ai` SDK
- `backend/app/ai/prompts.py` — all prompt templates (anomaly explanation, decision narrative, copilot)
- `backend/app/ai/context.py` — knowledge context loader (reads relevant Markdown section by subsystem; injects live `MissionContext` values for current-state fields, not static `mission_context.md` text)
- `backend/.env.example` — template for watsonx.ai API credentials (WATSONX_API_KEY, WATSONX_PROJECT_ID, WATSONX_URL)
- Prompt templates comply with the Granite Prompt Contract in `docs/methodology.md` Section 7
- Prompt for decision narratives must NOT include raw `procedures.md` text (see Granite Prompt Contract)
- Latency measured and documented; if > 5s, fallback caching strategy implemented
- `ibm-watsonx-ai` version verified and pinned correctly in `requirements.txt` before SDK use
- `backend/tests/test_ai.py` — mock Granite client; verify prompt construction; verify no numbers in fallback templates

**Relevant Context:**
- Granite Prompt Contract: `docs/methodology.md` Section 7
- Knowledge files: `backend/knowledge/`
- Boolean state change handling: `docs/methodology.md` Section 6

---

## Phase 7 — FastAPI Backend Integration

**Status:** [ ] pending

**Intent:** Wire all backend components into FastAPI endpoints. Expose SSE telemetry stream and REST endpoints for frontend consumption.

**Expected Outcomes:**
- `backend/app/api/telemetry.py` — SSE stream endpoint + snapshot endpoint
- `backend/app/api/analysis.py` — analytics + risk status endpoint
- `backend/app/api/decision.py` — decision options + what-if endpoint
- `backend/app/api/copilot.py` — operator Q&A endpoint (calls Granite)
- All endpoints return typed Pydantic responses
- `backend/app/main.py` registers all routers, configures CORS for local dev
- End-to-end integration test: simulator → analytics → risk → decision → Granite → API response

**Relevant Context:**
- All Phase 1–6 outputs
- `docs/architecture.md` Section 3.1 (pipeline)

---

## Phase 8 — React Frontend

**Status:** [ ] pending

**Intent:** Build the four-panel mission-control UI wired to the backend API.

**Expected Outcomes:**
- Mission header: health status, mission phase, active alert banner
- Telemetry panel: Recharts time-series for selected subsystem; subsystem filter
- Intelligence panel: anomaly card (severity, confidence band, evidence list, AI explanation with `[AI EXPLANATION]` tag)
- Decision Center: option cards (computed scores with `[COMPUTED]` tags), risk comparison, ACCEPT / REJECT / INVESTIGATE buttons, what-if result
- Copilot panel: chat input → calls `/api/copilot` → streams response
- All panels connected to live SSE telemetry stream
- Dark theme (Tailwind slate-900/slate-800)
- Source tags visible on all computed values

**Relevant Context:**
- UI layout: `docs/architecture.md` Section 3.2 (React Frontend)
- Source tag definitions: `docs/methodology.md` Section 8
- ALPHA-1-FAULT-01 demo arc: `docs/architecture.md` Section 5

---

## Phase 9 — End-to-End Demo Rehearsal

**Status:** [ ] pending

**Intent:** Run the complete ALPHA-1-FAULT-01 scenario from start to finish. Verify the demo story works reliably and repeatedly.

**Expected Outcomes:**
- Demo runs from tick 0 (normal) through anomaly detection, risk escalation, decision support, and operator action without any broken steps
- All UI panels update correctly during the fault arc
- Granite explanations are coherent and correctly grounded
- What-if projection displays correctly
- Demo is repeatable: same result every run
- Any bugs discovered are fixed before moving to Phase 10

**Relevant Context:**
- Demo arc: `docs/architecture.md` Section 5
- Full pipeline: `docs/architecture.md` Section 3.1

---

## Phase 10 — Documentation & Competition Submission Prep

**Status:** [ ] pending

**Intent:** Complete all competition deliverables.

**Expected Outcomes:**
- `README.md` complete with all required sections
- `docs/bob-development-log.md` up to date with all sessions
- GitHub repository public
- 3-minute demo video recorded and uploaded
- Competition submission form completed

**Relevant Context:**
- Competition requirements: architecture review Section B (competition requirements)
- README template: `README.md`
- Development log: `docs/bob-development-log.md`

---

## Stretch Features (post-MVP only)

These are not planned and must not be started until Phase 9 passes:

- Second fault scenario (communication degradation)
- Isolation Forest as secondary anomaly detector
- Operator action log persistence
- Space weather live API integration (NOAA SWPC)
- Multiple mission phases with context-sensitive analysis
- ChromaDB RAG (if Copilot needs broader knowledge)
