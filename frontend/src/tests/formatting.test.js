/**
 * ATLAS — Formatting utility tests
 */

import { describe, it, expect } from 'vitest'
import {
  formatRiskScore,
  formatRiskDelta,
  formatTimestamp,
  formatBreachMinutes,
  TELEMETRY_META,
  SUBSYSTEM_VARIABLES,
  SUBSYSTEM_LABELS,
} from '../utils/formatting.js'

describe('formatRiskScore', () => {
  it('formats 0.0 as 0.0%', () => expect(formatRiskScore(0)).toBe('0.0%'))
  it('formats 1.0 as 100.0%', () => expect(formatRiskScore(1)).toBe('100.0%'))
  it('formats 0.735 as 73.5%', () => expect(formatRiskScore(0.735)).toBe('73.5%'))
  it('returns em dash for null', () => expect(formatRiskScore(null)).toBe('—'))
  it('returns em dash for undefined', () => expect(formatRiskScore(undefined)).toBe('—'))
})

describe('formatRiskDelta', () => {
  it('negative delta is a reduction', () => {
    const result = formatRiskDelta(-0.25)
    expect(result.isReduction).toBe(true)
    expect(result.text).toContain('25.0')
  })
  it('positive delta is not a reduction', () => {
    const result = formatRiskDelta(0.10)
    expect(result.isReduction).toBe(false)
    expect(result.text).toContain('10.0')
  })
  it('zero delta is not a reduction', () => {
    const result = formatRiskDelta(0)
    expect(result.isReduction).toBe(false)
  })
})

describe('formatTimestamp', () => {
  it('formats an ISO string to HH:MM:SS UTC', () => {
    const result = formatTimestamp('2026-08-09T02:05:30.000Z')
    expect(result).toBe('02:05:30 UTC')
  })
  it('returns em dash for null', () => expect(formatTimestamp(null)).toBe('—'))
  it('returns em dash for empty string', () => expect(formatTimestamp('')).toBe('—'))
})

describe('formatBreachMinutes', () => {
  it('returns null for null input', () => expect(formatBreachMinutes(null)).toBeNull())
  it('returns Imminent for 0', () => expect(formatBreachMinutes(0)).toBe('Imminent'))
  it('returns < 1 min for values < 1', () => expect(formatBreachMinutes(0.5)).toBe('< 1 min'))
  it('formats whole minutes', () => expect(formatBreachMinutes(5)).toBe('5 min'))
  it('formats minutes and seconds', () => expect(formatBreachMinutes(5.5)).toBe('5m 30s'))
})

describe('TELEMETRY_META', () => {
  it('has all 13 telemetry variables', () => {
    const keys = Object.keys(TELEMETRY_META)
    expect(keys.length).toBe(13)
  })
  it('thruster_2_vibration_hz has unit Hz', () => {
    expect(TELEMETRY_META.thruster_2_vibration_hz.unit).toBe('Hz')
  })
  it('battery_voltage_v has unit V', () => {
    expect(TELEMETRY_META.battery_voltage_v.unit).toBe('V')
  })
  it('every entry has label, unit, fmt', () => {
    for (const [key, meta] of Object.entries(TELEMETRY_META)) {
      expect(meta.label, `${key} missing label`).toBeTruthy()
      expect(meta.unit, `${key} missing unit`).toBeTruthy()
      expect(typeof meta.fmt, `${key} fmt should be number`).toBe('number')
    }
  })
})

describe('SUBSYSTEM_VARIABLES', () => {
  it('has propulsion, power, computing, attitude, comms, environment', () => {
    const keys = Object.keys(SUBSYSTEM_VARIABLES)
    expect(keys).toContain('propulsion')
    expect(keys).toContain('power')
    expect(keys).toContain('computing')
    expect(keys).toContain('attitude')
    expect(keys).toContain('comms')
    expect(keys).toContain('environment')
  })
  it('propulsion has 3 variables', () => {
    expect(SUBSYSTEM_VARIABLES.propulsion.length).toBe(3)
  })
  it('propulsion includes thruster_2_temp_c, thruster_2_vibration_hz, thruster_2_efficiency_pct', () => {
    const propKeys = SUBSYSTEM_VARIABLES.propulsion.map(([k]) => k)
    expect(propKeys).toContain('thruster_2_temp_c')
    expect(propKeys).toContain('thruster_2_vibration_hz')
    expect(propKeys).toContain('thruster_2_efficiency_pct')
  })
  it('each variable entry has a variable key and color', () => {
    for (const [sub, vars] of Object.entries(SUBSYSTEM_VARIABLES)) {
      for (const entry of vars) {
        expect(entry.length, `${sub} entry should be [key, color]`).toBe(2)
        expect(typeof entry[0]).toBe('string')
        expect(entry[1]).toMatch(/^#/)
      }
    }
  })
})
