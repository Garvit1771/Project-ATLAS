# ATLAS — Final Architecture

**Version:** 1.0  
**Date:** August 8, 2026  
**Status:** FINAL — do not modify without a documented architectural decision

---

## 1. System Identity

**ATLAS** — Autonomous Telemetry, Learning, Analytics & Support  
**Tagline:** From Telemetry to Intelligence.

ATLAS is an AI-powered mission-control decision-support system. It transforms spacecraft telemetry and mission data into actionable operational intelligence for a human operator.

**ATLAS is not:**
- An autonomous spacecraft controller
- A static telemetry dashboard
- A chatbot attached to charts
- A physics simulation engine

**ATLAS is:**
- A structured, multi-layer AI system where computation and generative reasoning are separated
- A human-in-the-loop decision-support tool
- A system where every number displayed is traceable to a defined computational method

---

## 2. Core Design Principles

### P1 — Computation is separate from generative reasoning
The analytics engine, risk engine, and decision engine produce all numerical outputs deterministically. IBM Granite explains those outputs. Granite never generates, invents, or selects numerical values.

### P2 — The human operator decides
ATLAS detects, analyses, ranks, and explains. The operator accepts, rejects, or investigates. ATLAS never issues commands. All final actions are operator actions.

### P3 — Every displayed value has a traceable source
Every value shown in the UI is tagged: `[COMPUTED]`, `[MISSION PARAMS]`, `[AI EXPLANATION]`, or `[OPERATOR]`. No value appears without a source.

### P4 — Confidence is honest
Confidence values are only displayed when they are backed by a defined calculation (see `methodology.md`). Where no calculation exists, qualitative bands are used: HIGH / MODERATE / LOW.

### P5 — The demo drives scope
The ALPHA-1-FAULT-01 scripted scenario is the primary deliverable. All architectural decisions that conflict with a reliable, repeatable demo are resolved in favour of the demo.

### P6 — Simplest credible implementation wins
No component is built at a complexity level beyond what is needed to produce a correct, demonstrable result.

---

## 3. System Architecture

### 3.1 High-Level Pipeline

```
TELEMETRY SIMULATOR
        │
        ▼
INGESTION & VALIDATION (Pydantic schema check)
        │
        ▼
FEATURE ENGINEERING (rolling stats, regression slope — Pandas)
        │
        ▼
ANALYTICS ENGINE
  ├─ Hard threshold detection
  ├─ Rolling z-score detection
  └─ Cross-signal correlation detection (direction-agnostic)
        │
        ▼
        │         ┌─────────────────────────────┐
        │         │   MISSION CONTEXT OBJECT     │
        │         │   phase · next_maneuver_time  │
        │         │   constraints · redundancy   │
        │         └──────────┬──────────────────┘
        │                    │
        │         ┌──────────┘ (injected into both Risk Engine
        │         │             and Decision Engine)
        ▼         ▼
RISK ENGINE (weighted composite formula — deterministic)
  uses: anomaly severity, trend rate, correlation count,
        time_pressure (from mission context), redundancy
        │
        ▼
DECISION SUPPORT ENGINE (option scoring — deterministic)
  uses: risk engine output, option config table,
        mission context (phase, constraints)
  ├─ Option A: Continue current operation
  ├─ Option B: Reduce thruster load
  └─ Option C: Switch to redundant thruster
        │ Computed scores + structured evidence
        ▼
AI REASONING LAYER — IBM Granite via watsonx.ai
  ├─ Anomaly explanation (grounded in evidence block)
  ├─ Decision tradeoff narration (grounded in option scores)
  └─ Copilot operator Q&A (grounded in context + evidence)
        │ Natural-language explanations only — no numbers
        ▼
FASTAPI BACKEND (REST + SSE)
        │
        ▼
REACT FRONTEND — 4-panel mission-control UI
        │
        ▼
HUMAN OPERATOR
  └─ Reviews → Accepts / Rejects / Investigates
```

### 3.2 Layer Descriptions

#### Telemetry Simulator
- Python generator emitting one telemetry record per tick (1 Hz)
- 13 telemetry variables (see Section 4)
- Physically plausible internal correlations (not a full orbital simulator)
- Parameterised fault injection via scenario config files
- Reproducible: given the same scenario config, the same sequence is always produced

#### Ingestion & Validation
- Pydantic model validates every incoming record
- Out-of-schema records are rejected with a structured error
- No complex ETL — the simulator produces clean data

#### Feature Engineering
- Computed on a rolling buffer (last 300 ticks = 5 minutes)
- Per-variable: rolling mean, rolling std, delta-per-tick, z-score
- Implemented as Pandas operations on the buffer DataFrame

#### Analytics Engine
Three-layer detection cascade (see `methodology.md` for exact formulas):
1. **Hard threshold** — immediate CRITICAL flag for out-of-envelope values
2. **Rolling z-score** — flags statistically anomalous values within envelope
3. **Cross-signal correlation** — escalates severity when related signals are simultaneously anomalous

Outputs a structured `AnalyticsResult` per detection event.

#### Risk Engine
- Weighted composite formula over analytics outputs
- All weights defined in `data/normal_ranges.json`
- Produces: `risk_score` (0–1), `severity`, `estimated_threshold_breach_minutes`
- Formula documented in `methodology.md`
- Granite never touches these calculations

#### Mission Context Object
- Python dataclass: mission name, phase, next maneuver time, available subsystems, active constraints
- Injected into prompts and option-evaluation logic
- Updated when mission phase changes
- Not a microservice — a structured object

#### Decision Support Engine
- Evaluates each candidate option against a configuration table keyed by `[fault_type][mission_phase][option_id]`
- Produces per-option: `computed_risk_score_after`, `fuel_cost_pct`, `time_delay_min`, `mission_constraint_satisfied`, `recommendation_strength`
- `computed_risk_score_after` — runtime output of the what-if re-scoring formula; never read from the scenario file
- `risk_score_after_target` — scenario config field used for Phase 5 validation only; not part of the runtime API response
- **Ranking is deterministic** — options are sorted by `computed_risk_score_after` ascending
- Granite does NOT choose, rank, or decide which option is best
- Granite receives the pre-ranked option list and explains the tradeoffs

#### What-If Engine
- Re-runs the risk engine on a hypothetical state
- Hypothetical state = current telemetry state with option-specific parameter deltas applied
- Produces a risk delta: current score vs. projected score after action
- Granite explains the delta in natural language
- No physics simulation — deterministic re-scoring only

#### AI Reasoning Layer (IBM Granite via watsonx.ai)
- Accessed via `ibm-watsonx-ai` Python SDK
- Temperature ≤ 0.3 for all inference calls
- Every prompt is a structured template with an evidence block — never an open question
- Granite outputs: natural-language explanation only — no numbers, no rankings, no decisions
- Static knowledge context (Markdown files) injected per subsystem — no RAG for MVP
- Fallback: if API unavailable, display computed evidence without AI explanation

#### FastAPI Backend
- Single Python process
- SSE endpoint: streams telemetry records to frontend in real time
- REST endpoints: analytics snapshot, risk status, decision options, what-if, copilot Q&A
- Pydantic models for all request/response types

#### React Frontend
- Four panels: Telemetry, Intelligence, Decision Center, Copilot
- All computed values labeled with source tag
- Dark theme (Tailwind slate-900/slate-800)
- Human-in-the-loop: ACCEPT / REJECT / INVESTIGATE buttons in Decision Center
- Recharts for time-series plots

---

## 4. Telemetry Variable Set (MVP)

| Variable | Unit | Subsystem | Normal Range | Fault Behaviour |
|---|---|---|---|---|
| `battery_voltage_v` | V | power | 26.0–29.5 | drops during battery fault |
| `battery_temp_c` | °C | power | 15–35 | rises during thermal fault |
| `solar_power_w` | W | power | 80–120 | stable |
| `cpu_temp_c` | °C | computing | 40–70 | rises under load |
| `cpu_load_pct` | % | computing | 20–70 | spikes during maneuver |
| `thruster_1_temp_c` | °C | propulsion | 180–220 | stable |
| `thruster_2_temp_c` | °C | propulsion | 180–220 | **rises in FAULT-01** |
| `thruster_2_vibration_hz` | Hz | propulsion | 0.5–2.0 | **rises in FAULT-01** |
| `thruster_2_efficiency_pct` | % | propulsion | 92–98 | **drops in FAULT-01** |
| `attitude_error_deg` | ° | attitude | 0.0–0.5 | rises as propulsion degrades |
| `signal_strength_dbm` | dBm | comms | -85 to -60 | drops (more negative) in comms fault |
| `packet_loss_pct` | % | comms | 0–2 | rises in comms fault |
| `radiation_level_mgy` | mGy/h | environment | 0.1–0.8 | varies by orbit position |

### Physical correlations modelled in simulator
- Higher `cpu_load_pct` → higher `cpu_temp_c`
- Lower `thruster_2_efficiency_pct` → higher `cpu_load_pct` (attitude correction loop compensating)
- Higher `thruster_2_temp_c` → minor rise in `battery_temp_c` (shared thermal bus)
- Higher `radiation_level_mgy` → minor rise in `cpu_load_pct`

---

## 5. Primary Demo Scenario — ALPHA-1-FAULT-01

**Mission:** ALPHA-1 Lunar Orbiter  
**Phase:** Orbital Insertion  
**Fault:** Thruster 2 progressive degradation

| Phase | Ticks | Real time | What happens |
|---|---|---|---|
| Normal operation | 0–119 | 0–2 min | All telemetry nominal |
| Fault onset | 120 | 2:00 | Vibration and temperature begin rising |
| Detectable anomaly | 150–180 | 2:30–3:00 | Z-score thresholds breached; correlation detected |
| ATLAS alert | ~180 | ~3:00 | Intelligence panel updates; risk score rises |
| Decision support | ~180 | ~3:00 | Decision Center shows 3 ranked options |
| Operator review | — | — | Human reviews evidence, accepts/rejects |

---

## 6. Technology Stack

| Layer | Technology | Version target |
|---|---|---|
| Frontend framework | React + Vite | React 18, Vite 5 |
| Frontend styling | Tailwind CSS | v3 |
| Frontend charts | Recharts | v2 |
| Frontend tests | Vitest | latest |
| Backend framework | Python + FastAPI | Python 3.11+, FastAPI 0.110+ |
| Data validation | Pydantic | v2 |
| Analytics | Pandas + NumPy | latest stable |
| ML (stretch only) | Scikit-learn | latest stable |
| Generative AI | IBM Granite via watsonx.ai | ibm-watsonx-ai SDK |
| Backend tests | Pytest | latest stable |
| Version control | Git + GitHub | — |

**Explicitly excluded from MVP:**
ChromaDB, Sentence Transformers, Redis, Celery, Kafka, Docker, authentication, 3D visualization, Isolation Forest (stretch only), SQLite (only if replay is needed post-MVP).

---

## 7. Repository Structure

```
project-atlas/
│
├── backend/
│   ├── app/
│   │   ├── api/              ← FastAPI routers
│   │   ├── analytics/        ← z-score, correlation, risk engine
│   │   ├── ai/               ← Granite client, prompt templates
│   │   ├── decision/         ← option evaluation, what-if
│   │   ├── simulation/       ← telemetry generator, fault injection
│   │   ├── models/           ← Pydantic schemas
│   │   └── main.py
│   ├── knowledge/            ← static Markdown for prompt injection
│   ├── tests/
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── services/
│   │   └── App.jsx
│   ├── package.json
│   └── vite.config.js
│
├── docs/
│   ├── architecture.md       ← this file
│   ├── methodology.md        ← detection and scoring formulas
│   └── bob-development-log.md
│
├── data/
│   ├── normal_ranges.json    ← operating envelopes + risk weights
│   └── scenarios/
│       └── alpha1_fault_01.json
│
├── README.md
├── .gitignore
└── LICENSE
```

---

## 8. Out of Scope (MVP)

The following are explicitly deferred and must not be started until the MVP demo works end-to-end:

- RAG / ChromaDB / Sentence Transformers
- Isolation Forest anomaly detection
- Second fault scenario
- Historical mission replay
- Operator action log persistence
- Space weather live API integration
- Multiple mission phases
- Authentication or user management
- 3D spacecraft visualization
- Orbit track / map view
