# ALPHA-1 Known Fault Modes

**Purpose:** This document provides fault mode knowledge for ATLAS AI prompt context injection. It describes known failure signatures and their operational implications.

---

## FAULT-01: Thruster 2 Progressive Degradation

**Subsystem:** Propulsion  
**Component:** Thruster 2  
**Type:** Progressive mechanical / thermal degradation

**Signal signatures:**
- `thruster_2_vibration_hz`: Rising — typically precedes temperature increase by 5–10 ticks
- `thruster_2_temp_c`: Rising — thermal runaway risk if unaddressed
- `thruster_2_efficiency_pct`: Declining — attitude correction loop compensates, increasing CPU load
- `attitude_error_deg`: Rising secondary effect from propulsion imbalance
- `cpu_load_pct`: Rising secondary effect from attitude correction
- `battery_temp_c`: Minor secondary rise from shared thermal bus

**Operational significance during orbital insertion:**  
Orbital insertion requires sustained and accurate thrust. Progressive Thruster 2 degradation during this phase risks incomplete orbital insertion, increased fuel consumption for correction, or trajectory deviation. If left unaddressed, the failure mode can progress to thruster shutdown and mission abort.

**Available responses:**
1. Continue current operation — acceptable only if degradation is early-stage and trend is not confirmed
2. Reduce thruster load — reduces thermal and mechanical stress, may be insufficient if degradation is advanced
3. Switch to Redundant Thruster 3 — eliminates the degradation risk; incurs minor fuel and time cost

**Risk escalation timeline (reference range — not the computed estimate):**
Based on the FAULT-01 ramp parameters, the failure mode progresses from detectable anomaly to critical threshold breach in approximately 20–35 minutes if unaddressed. This is a qualitative reference range for Granite context only. The authoritative value for the operator is the `estimated_threshold_breach_minutes` field computed by the Risk Engine in real time — that value must be used in the UI, not this range.

---

## FAULT-02: Communication Degradation (Reference — not primary demo scenario)

**Subsystem:** Communications  
**Signal signatures:** Declining `signal_strength_dbm`, rising `packet_loss_pct`  
**Common causes:** Antenna pointing degradation (attitude-related), transponder thermal issue, deep space geometry  
**Operational significance:** Loss of telemetry and command uplink; loss of mission control visibility

---

## FAULT-03: Battery Degradation (Reference)

**Subsystem:** Power  
**Signal signatures:** Declining `battery_voltage_v`, rising `battery_temp_c`, declining charge efficiency  
**Operational significance:** Power system failure can affect all subsystems simultaneously; mission-ending if voltage drops below minimum operating threshold
