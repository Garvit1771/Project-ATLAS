# Project ATLAS

**Autonomous Telemetry, Learning, Analytics & Support**  
*From Telemetry to Intelligence.*

[![IBM AI Builders Challenge](https://img.shields.io/badge/IBM%20AI%20Builders%20Challenge-2026-blue)](https://)
[![Challenge Theme](https://img.shields.io/badge/Theme-Advance%20Space%20Exploration%20with%20AI-brightgreen)](https://)

---

## Problem Statement

Mission operators managing spacecraft in flight face a critical challenge: telemetry streams produce hundreds of data points per second, anomalies can emerge subtly across multiple subsystems simultaneously, and critical decisions — such as switching to redundant propulsion during orbital insertion — must be made quickly and with confidence. Current tools largely present data; they do not reason about it.

The consequence is cognitive overload at the worst possible moment. Operators must mentally correlate signals, estimate risk, recall procedures, and evaluate options — all under time pressure.

---

## Solution Description

ATLAS is an AI-powered mission-control decision-support system that transforms raw spacecraft telemetry into actionable operational intelligence.

ATLAS does not replace the human operator. It acts as an intelligent analytical co-pilot:

1. **Monitors** telemetry across all spacecraft subsystems in real time
2. **Detects** anomalies using a three-layer statistical detection cascade
3. **Assesses** operational risk using a defined, auditable composite scoring formula
4. **Compares** possible operational responses with deterministically computed tradeoffs
5. **Explains** findings, implications, and tradeoffs using IBM Granite generative AI — grounded in computed evidence
6. **Supports** what-if analysis: the operator can ask "what happens if we switch to the redundant thruster?" and receive a deterministic re-scored risk projection with an AI-generated narrative
7. **Defers** all final decisions to the human operator

The operator reviews the evidence, reads the AI explanation, examines the option comparison, and then accepts, rejects, or investigates. ATLAS never issues commands.

---

## AI Approach and Architecture

### Core architectural principle: computation is separated from generative reasoning

ATLAS uses a two-layer AI architecture:

**Computational layer (deterministic):**
- Rolling z-score anomaly detection
- Cross-signal correlation detection
- Weighted composite risk scoring
- Deterministic option evaluation and ranking

**Generative AI layer (IBM Granite):**
- Receives structured evidence produced by the computational layer
- Explains findings in natural language for the operator
- Narrates decision tradeoffs (does not select or rank options)
- Answers operator questions in the Copilot panel
- Never generates numerical values — all numbers come from computation

This separation means ATLAS cannot hallucinate a risk score. Every number displayed is traceable to a formula defined in [`docs/methodology.md`](docs/methodology.md).

### AI grounding techniques
- Structured prompt templates with an `[EVIDENCE]` block derived from analytics outputs
- Prompts instruct Granite not to state specific numerical values
- Prompts instruct Granite to base explanations only on the provided evidence block
- Temperature ≤ 0.3 for all inference calls
- Output length constrained per call type
- All UI values tagged with source: `[COMPUTED]`, `[MISSION PARAMS]`, `[AI EXPLANATION]`, or `[OPERATOR]`

---

## Challenge Theme

**Advance Space Exploration with AI**

ATLAS addresses: predictive spacecraft monitoring, anomaly detection, space operations decision support.

---

## How IBM Bob Was Used

IBM Bob was used as the primary development tool throughout this project:

- **Architecture design** — Full project specification reviewed by Bob; architectural weaknesses identified and corrected
- **Methodology definition** — Detection formulas, risk scoring, confidence calculation, and Granite prompt contract designed with Bob
- **Implementation** — All backend modules, frontend components, API endpoints, tests, and documentation generated with Bob
- **Debugging** — Bob used to diagnose and fix issues throughout development
- **Documentation** — README, architecture docs, and methodology docs produced with Bob

Full session-by-session record: [`docs/bob-development-log.md`](docs/bob-development-log.md)

---

## Technology Stack

| Component | Technology |
|---|---|
| Generative AI | IBM Granite via watsonx.ai (`ibm-watsonx-ai` SDK) |
| Backend | Python 3.11 + FastAPI |
| Data validation | Pydantic v2 |
| Analytics | Pandas + NumPy |
| Frontend | React 18 + Vite + Tailwind CSS + Recharts |
| Testing | Pytest + Vitest |
| Version control | Git + GitHub |

---

## Primary Demo Scenario

**Mission:** ALPHA-1 Lunar Orbiter — Orbital Insertion Phase  
**Scenario:** ALPHA-1-FAULT-01 — Thruster 2 progressive degradation

The demo shows:
1. Spacecraft operating normally
2. Thruster 2 vibration and temperature begin rising (fault onset)
3. ATLAS detects the anomaly (z-score + correlation cascade)
4. Risk score rises; Intelligence panel updates
5. Decision Center shows three ranked options with computed tradeoffs
6. IBM Granite explains the situation and the tradeoffs
7. Operator selects "Switch to Redundant Thruster 3"
8. What-if: ATLAS projects a significant risk reduction (demonstrating the deterministic re-scoring engine)
9. Operator confirms the action

---

## Repository Structure

```
project-atlas/
├── backend/          ← Python FastAPI backend, analytics, AI, simulation
├── frontend/         ← React + Vite + Tailwind mission-control UI
├── docs/             ← Architecture, methodology, development log
├── data/             ← Operating envelopes, scenario configs
└── README.md
```

---

## Local Development Setup

*Setup instructions will be added as the project is built.*

---

## Project Submission

*Submission link will be added prior to August 31, 2026.*

---

## License

MIT — see [`LICENSE`](LICENSE)
