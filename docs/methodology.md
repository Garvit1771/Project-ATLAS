# ATLAS — Analytics & Scoring Methodology

**Version:** 1.0  
**Date:** August 8, 2026  
**Status:** FINAL

This document defines every formula used in ATLAS to produce numerical outputs. Any value displayed in the UI that originates from a computation must be traceable to a formula in this document. IBM Granite never produces, modifies, or selects these values.

---

## 1. Feature Engineering

Applied to a rolling buffer of the last **N = 300** telemetry ticks (5 minutes at 1 Hz).

For each telemetry variable `v`:

| Feature | Formula |
|---|---|
| `rolling_mean(v, w)` | Mean of `v` over the last `w` ticks |
| `rolling_std(v, w)` | Standard deviation of `v` over the last `w` ticks |
| `z_score(v, w)` | `(v_current - rolling_mean(v, w)) / rolling_std(v, w)` |
| `delta(v)` | `v_current - v_previous` |
| `trend_direction(v, w)` | Sign of the slope of a linear regression of `v` over the last `w` ticks: +1 (rising), 0 (flat), -1 (falling) |

Default window `w = 60` ticks (1 minute). Minimum 10 ticks before z-score is computed (cold-start guard).

---

## 2. Anomaly Detection — Three-Layer Cascade

Layers are evaluated in order. Higher layers take precedence on severity.

### Layer 1 — Hard Threshold Breach

```
if v_current < v_min OR v_current > v_max:
    anomaly = True
    severity = CRITICAL
    detection_method = "hard_threshold"
```

Where `v_min` and `v_max` are the operating envelope values defined in `data/normal_ranges.json`.

### Layer 2 — Rolling Z-Score

```
z = z_score(v, w=60)
if |z| > Z_THRESHOLD:
    anomaly = True
    detection_method = "rolling_zscore"
```

Severity mapping:

| |z| range | Severity |
|---|---|
| 2.5 – 3.0 | LOW |
| 3.0 – 4.0 | MODERATE |
| > 4.0 | HIGH |

`Z_THRESHOLD = 2.5` (configurable in `data/normal_ranges.json`).

### Layer 3 — Cross-Signal Correlation

The correlation layer detects simultaneous anomalous behaviour across multiple signals of the same subsystem, consistent with a known fault mode. It does **not** require signals to trend in the same direction — fault modes routinely produce mixed directions (e.g., temperature and vibration rise while efficiency falls).

```
if len(anomalous_signals_in_subsystem) >= 2
   AND all first_anomaly_tick values are within correlation_window ticks of each other:
    composite_anomaly = True
    severity = escalated one level above highest individual severity
    detection_method = "rolling_zscore+correlation"
```

**Rationale for direction-agnostic rule:** In FAULT-01, `thruster_2_temp_c` and `thruster_2_vibration_hz` rise while `thruster_2_efficiency_pct` falls. Requiring same-direction trending would prevent this correlation from ever being detected. The correlation signal is the *simultaneous anomaly across the subsystem*, not a shared direction.

`correlation_window = 30` ticks.

Correlation rules are defined as a table in `data/normal_ranges.json` under `"correlation_rules"`. Each subsystem entry lists the signals that, when simultaneously anomalous, constitute a composite fault:
```json
{
  "propulsion": ["thruster_2_vibration_hz", "thruster_2_temp_c", "thruster_2_efficiency_pct"],
  "power": ["battery_voltage_v", "battery_temp_c"]
}
```

---

## 3. Confidence Calculation

Confidence is **not a fabricated statistical value**. It is derived directly from the detection method.

| Detection method | Confidence basis | Display |
|---|---|---|
| `hard_threshold` | Deterministic — value is outside defined envelope | HIGH |
| `rolling_zscore` only | Proportional to z-score magnitude | See formula below |
| `rolling_zscore+correlation` | Z-score confidence + correlation bonus | See formula below |

### Z-score confidence formula

```
z_confidence = min(1.0, (|z| - Z_THRESHOLD) / Z_THRESHOLD)
```

**Design rationale:** This formula maps:
- `|z| = Z_THRESHOLD (2.5)` → `confidence = 0.0` (threshold just crossed)
- `|z| = 2 × Z_THRESHOLD (5.0)` → `confidence = 1.0` (strongly anomalous), capped at 1.0

For the primary FAULT-01 scenario, expected z-scores at peak anomaly are approximately 3.5–4.5 for `thruster_2_vibration_hz` and `thruster_2_temp_c`:
- At `|z| = 3.5`: `confidence = (3.5 - 2.5) / 2.5 = 0.40` → MODERATE (pre-correlation)
- At `|z| = 4.0`: `confidence = (4.0 - 2.5) / 2.5 = 0.60` → MODERATE (pre-correlation)

After the correlation bonus is applied (see below), the composite confidence reaches HIGH. This correctly represents the detection state: individual signal anomalies are moderate; the composite correlated anomaly is high-confidence.

The previous denominator `Z_THRESHOLD * 2` would have required `|z| ≥ 7.5` for full confidence — an unrealistic threshold for this telemetry set.

### Correlation bonus

```
if composite_anomaly:
    confidence = min(1.0, z_confidence + 0.35)
```

**Design rationale:** The correlation of ≥ 2 simultaneously anomalous signals within the same subsystem provides strong additional evidence. A bonus of 0.35 is chosen so that a moderate individual z-score (confidence ≈ 0.50–0.60) combined with cross-signal correlation produces a HIGH composite confidence (≥ 0.85). This reflects the genuine increase in diagnostic certainty when multiple independent signals confirm the same fault.

### Display bands

Confidence values are always displayed as qualitative bands in the UI, never as raw decimals:

| Value range | Display |
|---|---|
| ≥ 0.85 | HIGH |
| 0.65 – 0.84 | MODERATE |
| < 0.65 | LOW |

The underlying numeric value is available in the API response for transparency; the UI shows bands only.

---

## 4. Risk Score

### Formula

```
risk_score = (
    w_severity    * severity_normalized
  + w_trend       * trend_rate_normalized
  + w_correlation * correlation_count_normalized
  + w_time        * time_pressure_factor
  + w_redundancy  * redundancy_factor
)
```

All weights sum to 1.0. Default weights (overridable in `data/normal_ranges.json`):

| Weight | Default value | Meaning |
|---|---|---|
| `w_severity` | 0.35 | Anomaly severity contribution |
| `w_trend` | 0.25 | Rate of degradation |
| `w_correlation` | 0.20 | Number of correlated signals |
| `w_time` | 0.10 | Proximity to next critical mission event |
| `w_redundancy` | 0.10 | Availability of redundant systems |

### Input normalizations

**`severity_normalized`**

| Severity | Value |
|---|---|
| NONE | 0.0 |
| LOW | 0.25 |
| MODERATE | 0.5 |
| HIGH | 0.75 |
| CRITICAL | 1.0 |

**`trend_rate_normalized`**

```
trend_rate_normalized = min(1.0, |regression_slope| / delta_max)
```

Where:
- `regression_slope` is the slope of a linear regression of variable `v` over the last `w = 60` ticks (same window as z-score). This is the same `trend_direction` feature from Section 1, but here the *magnitude* of the slope is used rather than its sign.
- `delta_max` is the maximum expected rate of change per tick for the variable, defined in `data/normal_ranges.json`.

**Rationale for regression slope over single-tick delta:** A single-tick delta `(v_current - v_previous)` is dominated by measurement noise and produces a jittery `trend_rate_normalized` that causes the risk score to oscillate rapidly even during steady degradation. The regression slope over 60 ticks smooths this noise and reflects the true degradation rate. Implementation note: `numpy.polyfit(range(w), buffer[-w:], 1)[0]` returns the slope directly.

**`correlation_count_normalized`**

```
correlation_count_normalized = min(1.0, correlated_signal_count / 3)
```

**`time_pressure_factor`**

```
minutes_to_next_event = (next_maneuver_time - current_time).total_seconds() / 60
time_pressure_factor = max(0.0, 1.0 - (minutes_to_next_event / 60))
```
Reaches 1.0 when next event is ≤ 0 minutes away, 0.0 when ≥ 60 minutes away.

**`redundancy_factor`**

```
redundancy_factor = 1.0 if no_redundant_system_available else 0.3
```

### Estimated time to threshold breach

```
if regression_slope != 0:
    # regression_slope is in units/tick (e.g. degC/tick at 1 Hz)
    # v_threshold: use v_max if slope > 0, v_min if slope < 0
    distance_to_threshold = v_threshold - v_current  # signed
    estimated_ticks = abs(distance_to_threshold / regression_slope)
    estimated_minutes = estimated_ticks / 60
else:
    estimated_minutes = None  # signal has no detectable trend
```

Note: `v_threshold` is the relevant limit from `data/normal_ranges.json` — the boundary the signal is trending toward (`v_max` if regression_slope > 0, `v_min` if regression_slope < 0).

---

## 5. Decision Option Scoring

Options are evaluated deterministically from a configuration table in `data/scenarios/alpha1_fault_01.json`.

### Per-option output schema

This is the schema of the `DecisionOption` object returned by the Decision Engine to the API and frontend. `computed_risk_score_after` is the output of the what-if re-scoring formula — it is never read directly from the scenario config.

```json
{
  "option_id": "string",
  "label": "string",
  "description": "string",
  "computed_risk_score_after": "float 0-1 (what-if formula output)",
  "fuel_cost_pct": "float (from scenario config - MISSION PARAMS)",
  "time_delay_min": "float (from scenario config - MISSION PARAMS)",
  "mission_constraint_satisfied": "boolean",
  "subsystem_stress": ["string"],
  "recommendation_strength": "STRONG | MODERATE | WEAK"
}
```

The scenario config field `risk_score_after_target` is used during Phase 5 testing only, to verify that the formula produces the expected value. It is not part of the runtime API response.

### Ranking

Options are ranked by `computed_risk_score_after` ascending (lowest post-action risk ranked first). This ranking is deterministic and computed before any LLM call.

**Granite receives the pre-ranked list. Granite does not rerank, select, or recommend a specific option. Granite explains the computed tradeoffs.**

### Recommendation strength mapping

| `computed_risk_score_after` | Strength |
|---|---|
| < 0.30 | STRONG |
| 0.30 - 0.60 | MODERATE |
| > 0.60 | WEAK |

---

## 6. What-If Scoring

The what-if engine re-runs the risk formula on a hypothetical modified state. The `risk_score_after` values stored in the scenario config file are **reference/validation targets only** — they exist to verify that the formula produces the expected output, not to be returned directly as the answer. The engine must always execute the formula.

### Procedure

1. Copy current telemetry state to a hypothetical state dict
2. Apply the option's `numeric_state_deltas` (signed floats) to the relevant telemetry variables
3. Apply the option's `boolean_state_changes` to the spacecraft state flags (see below)
4. Re-derive the feature values (rolling mean, std, z-score, regression slope) on the hypothetical state
5. Re-run the full risk formula (Section 4) on the hypothetical derived features
6. Return: `{ "current_risk": float, "projected_risk": float, "delta": float }`

The result is deterministic. Granite explains the delta in natural language.

### Handling boolean state changes

Some options change spacecraft state in ways that cannot be expressed as a numeric telemetry delta. These are recorded separately as `boolean_state_changes` in the scenario config and are handled as follows:

| State change | Effect on risk formula input |
|---|---|
| `thruster_2_active: false` | The anomalous thruster is deactivated. Set `thruster_2_vibration_hz`, `thruster_2_temp_c`, and `thruster_2_efficiency_pct` anomaly flags to False and their hypothetical values to nominal midpoint. Remove them from the correlated anomaly set. |
| `thruster_3_active: true` | Redundant system is now active. Set `redundancy_available: true`, which causes `redundancy_factor = 0.3` (lower risk contribution) in the formula. |

**Rationale:** Boolean state transitions do not change a telemetry reading directly — they change which signals are active and whether redundancy is available. The risk engine must be aware of the active subsystem state when evaluating `redundancy_factor` and when selecting which signals to include in the correlation check.

---

## 7. Granite Prompt Contract

These rules govern all LLM interactions. They are not suggestions — violating them undermines the architecture.

| Rule | Detail |
|---|---|
| **No numbers in output** | Prompts instruct Granite not to state specific numerical values. Numbers appear in the UI from computed sources only. |
| **Evidence-block grounding** | Every prompt contains a `[EVIDENCE]` block derived from analytics/decision outputs. |
| **Source restriction** | Prompts instruct: "Base your explanation only on the evidence in the [EVIDENCE] block. If the evidence is insufficient, say so explicitly." |
| **Temperature** | ≤ 0.3 for all calls |
| **Max tokens** | 300 for anomaly explanations, 400 for decision narratives, 250 for Copilot responses |
| **No ranking, no implied preference** | Prompts for decision narratives explicitly state: "Describe the tradeoffs of each option as presented. Do not recommend, rank, prioritise, or use language that implies one option is preferable to another. The human operator makes the final decision." |
| **No procedure paraphrasing** | Prompts must not include the raw text of `procedures.md` operating procedures, as those documents contain action-guiding language (e.g., "Apply Option C if severity is HIGH"). Inject mission context and spacecraft specifications; do not inject procedure steps directly into decision-narrative prompts. |

---

## 8. Source Tags

All values displayed in the frontend carry one of these tags:

| Tag | Meaning |
|---|---|
| `COMPUTED` | Produced by analytics engine, risk engine, or decision engine formula |
| `MISSION PARAMS` | Loaded from scenario config or mission context object |
| `AI EXPLANATION` | Produced by IBM Granite; grounded in evidence block |
| `OPERATOR` | Action taken or confirmed by the human operator |
