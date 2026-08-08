# ALPHA-1 Standard Operating Procedures

**Purpose:** This document provides operational procedure knowledge for ATLAS AI prompt context injection. It describes standard responses to anomaly conditions.

---

## PROC-PROP-01: Response to Propulsion Anomaly During Orbital Insertion

**Trigger:** Propulsion subsystem anomaly detected during orbital insertion phase  
**Priority:** HIGH — orbital insertion window is time-critical

**Step 1 — Assess severity and trend**
- Confirm anomaly is not a measurement artifact (check for corroborating signals)
- Assess trend direction and rate
- Determine estimated time to threshold breach

**Step 2 — Evaluate options**
- **Option A (Continue):** Acceptable only if anomaly is LOW severity, single-signal, and not trending
- **Option B (Reduce load):** Apply if anomaly is MODERATE severity and trend is early-stage. Reduces thermal and mechanical stress. Monitor for stabilisation over next 5 minutes.
- **Option C (Switch to Redundant Thruster 3):** Apply if anomaly is HIGH severity, trend is confirmed, or estimated threshold breach < 30 minutes. Thruster 3 is rated for full mission profile.

**Step 3 — Execute selected option and monitor**
- Confirm anomaly signals stabilise or improve following action
- If anomaly continues to escalate after Option B, escalate to Option C

**Constraint:** Switching to Thruster 3 adds approximately 4 minutes to the orbital insertion burn timeline. This is within the 8-minute abort window.

---

## PROC-PWR-01: Response to Power Subsystem Anomaly

**Trigger:** Battery voltage decline or battery temperature rise  
**Step 1:** Assess solar array output and load demand  
**Step 2:** If voltage declining — shed non-critical loads (science instruments first)  
**Step 3:** If temperature rising — check for thermal bus anomaly on connected subsystems

---

## PROC-COMM-01: Response to Communication Degradation

**Trigger:** Signal strength decline or packet loss increase  
**Step 1:** Check attitude error — antenna pointing may be affected  
**Step 2:** If attitude-related — assess propulsion and attitude control subsystem health  
**Step 3:** If not attitude-related — assess transponder thermal status
