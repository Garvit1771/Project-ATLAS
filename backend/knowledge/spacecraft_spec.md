# ALPHA-1 Spacecraft Specification

**Mission:** ALPHA-1 Lunar Orbiter  
**Classification:** Fictional / technically plausible demonstration mission  
**Purpose:** This document provides static spacecraft knowledge for ATLAS AI prompt context injection.

---

## Mission Overview

ALPHA-1 is a lunar orbiter mission conducting surface mapping and resource assessment in preparation for future crewed operations. The spacecraft is designed for a 90-day primary mission in a 100 km circular polar lunar orbit.

**Current mission phase:** Orbital Insertion  
**Next maneuver:** Orbital Insertion Burn 2 — scheduled 02:30 UTC  
**Mission constraint:** Maintain orbital insertion window. Delay > 8 minutes may require mission abort.

---

## Propulsion Subsystem

**Primary thrusters:** Thruster 1, Thruster 2 (main propulsion pair)  
**Redundant thruster:** Thruster 3 (rated for full mission profile; fuel reserve +7%)  
**Nominal thruster temperature:** 180–220 °C during active burns  
**Nominal vibration (Thruster 2):** 0.5–2.0 Hz  
**Nominal efficiency (Thruster 2):** 92–98%

Thruster 2 shares a thermal bus with the battery array. Elevated Thruster 2 temperatures will produce a minor secondary rise in battery temperature.

An attitude correction loop monitors pointing error and increases CPU load when compensating for propulsion imbalance. Reduced Thruster 2 efficiency causes measurable attitude error and CPU load increase.

---

## Power Subsystem

**Battery voltage (nominal):** 26.0–29.5 V  
**Battery temperature (nominal):** 15–35 °C  
**Solar array power output (nominal):** 80–120 W  
**Battery state transitions:** Charge / Discharge determined by solar exposure and load demand

---

## Computing Subsystem

**CPU load (nominal):** 20–70%  
**CPU temperature (nominal):** 40–70 °C  
**CPU load increases with:** attitude correction activity, telemetry burst transmission, radiation event handling

---

## Attitude Control Subsystem

**Attitude error (nominal):** 0.0–0.5°  
**Attitude error source when elevated:** propulsion imbalance, reaction wheel degradation  
**Impact of elevated attitude error:** increased CPU load for correction, potential pointing loss for communication antenna

---

## Communications Subsystem

**Signal strength (nominal):** -85 to -60 dBm  
**Packet loss (nominal):** 0–2%  
**Communication latency:** dependent on Earth-Moon distance and orbital geometry  
**Antenna pointing:** attitude-dependent; elevated attitude error degrades signal quality

---

## Environment

**Radiation level (nominal orbit):** 0.1–0.8 mGy/h  
**Radiation events:** Solar particle events can produce transient CPU load increases and single-event upsets
