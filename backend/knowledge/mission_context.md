# ALPHA-1 Mission Context

**Purpose:** This document provides mission profile knowledge for ATLAS AI prompt context injection.

> **RUNTIME NOTE — FOR IMPLEMENTATION USE:**
> This document contains static reference values for the mission profile.
> At runtime, the live `MissionContext` object (populated from `data/scenarios/alpha1_fault_01.json`
> and updated as the simulation runs) is the authoritative source for all current-state fields:
> phase, next maneuver time, thruster availability, and constraint status.
> The AI context injector must use live object values for these fields, not the static text below.
> Static content in this file (mission type, orbit parameters, priorities) may be injected directly.

---

## Mission Profile

**Mission name:** ALPHA-1 Lunar Orbiter  
**Mission type:** Robotic lunar orbiter — surface mapping and resource assessment  
**Target orbit:** 100 km circular polar lunar orbit  
**Primary mission duration:** 90 days  
**Launch vehicle:** Classified (demonstration mission)

---

## Current Mission State

**Phase:** Orbital Insertion  
**Description:** The spacecraft is completing the sequence of burns required to transition from translunar trajectory into stable lunar orbit. This is the highest-risk mission phase. A failure to complete orbital insertion results in mission loss.

**Next maneuver:** Orbital Insertion Burn 2  
**Scheduled time:** 02:30 UTC  
**Maneuver duration:** Approximately 18 minutes  
**Window constraint:** The burn window closes at 02:38 UTC. Delay beyond 8 minutes requires mission abort and trajectory correction for a second insertion attempt (fuel cost: significant; timeline impact: 72 hours).

---

## Available Propulsion

> **RUNTIME NOTE:** Thruster status below reflects the scenario start state.
> At runtime, inject current thruster state from the live `MissionContext` object.

| Thruster | Status | Notes |
|---|---|---|
| Thruster 1 | Nominal | Primary |
| Thruster 2 | Nominal at scenario start — degrades during FAULT-01 | Primary |
| Thruster 3 | Standby | Redundant — rated for full mission profile |

Switching to Thruster 3: estimated +4 minutes to burn timeline, +7% fuel consumption for this burn.

---

## Mission Priorities (in order)

1. Complete orbital insertion — spacecraft must achieve stable lunar orbit
2. Maintain spacecraft health — avoid subsystem damage that would compromise the primary mission
3. Preserve fuel margins — fuel reserve is required for the 90-day orbital maintenance and end-of-mission disposal

---

## Operational Constraints

- Orbital insertion burn must not be interrupted once initiated (minimum burn to achieve stable orbit)
- Communication blackout expected during lunar orbit insertion: 22 minutes
- Science instruments are in safe mode during orbital insertion
- Attitude must be maintained within 0.5° of burn attitude throughout the maneuver
