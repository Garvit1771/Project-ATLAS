/**
 * ATLAS — Severity utility tests
 */

import { describe, it, expect } from 'vitest'
import {
  severityTextColor,
  severityBadgeClasses,
  severityDotColor,
  severityLabel,
  isElevatedSeverity,
  isCriticalSeverity,
  confidenceBandTextColor,
  detectionMethodLabel,
  strengthBadgeClasses,
  connectionLabel,
  connectionDotColor,
} from '../utils/severity.js'

describe('severityTextColor', () => {
  it('returns red for CRITICAL', () => {
    expect(severityTextColor('CRITICAL')).toContain('red')
  })
  it('returns orange for HIGH', () => {
    expect(severityTextColor('HIGH')).toContain('orange')
  })
  it('returns yellow for MODERATE', () => {
    expect(severityTextColor('MODERATE')).toContain('yellow')
  })
  it('returns blue for LOW', () => {
    expect(severityTextColor('LOW')).toContain('blue')
  })
  it('returns slate for NONE', () => {
    expect(severityTextColor('NONE')).toContain('slate')
  })
})

describe('severityLabel', () => {
  it('returns Nominal for NONE', () => expect(severityLabel('NONE')).toBe('Nominal'))
  it('returns Low for LOW', () => expect(severityLabel('LOW')).toBe('Low'))
  it('returns Moderate for MODERATE', () => expect(severityLabel('MODERATE')).toBe('Moderate'))
  it('returns High for HIGH', () => expect(severityLabel('HIGH')).toBe('High'))
  it('returns Critical for CRITICAL', () => expect(severityLabel('CRITICAL')).toBe('Critical'))
})

describe('isElevatedSeverity', () => {
  it('returns false for NONE', () => expect(isElevatedSeverity('NONE')).toBe(false))
  it('returns false for undefined', () => expect(isElevatedSeverity(undefined)).toBeFalsy())
  it('returns true for LOW', () => expect(isElevatedSeverity('LOW')).toBe(true))
  it('returns true for HIGH', () => expect(isElevatedSeverity('HIGH')).toBe(true))
  it('returns true for CRITICAL', () => expect(isElevatedSeverity('CRITICAL')).toBe(true))
})

describe('isCriticalSeverity', () => {
  it('returns false for NONE', () => expect(isCriticalSeverity('NONE')).toBe(false))
  it('returns false for LOW', () => expect(isCriticalSeverity('LOW')).toBe(false))
  it('returns false for MODERATE', () => expect(isCriticalSeverity('MODERATE')).toBe(false))
  it('returns true for HIGH', () => expect(isCriticalSeverity('HIGH')).toBe(true))
  it('returns true for CRITICAL', () => expect(isCriticalSeverity('CRITICAL')).toBe(true))
})

describe('detectionMethodLabel', () => {
  it('labels hard_threshold correctly', () => {
    expect(detectionMethodLabel('hard_threshold')).toBe('Hard threshold breach')
  })
  it('labels rolling_zscore correctly', () => {
    expect(detectionMethodLabel('rolling_zscore')).toBe('Rolling z-score')
  })
  it('labels rolling_zscore+correlation correctly', () => {
    expect(detectionMethodLabel('rolling_zscore+correlation')).toContain('correlation')
  })
  it('returns fallback for unknown', () => {
    expect(detectionMethodLabel('unknown')).toBe('unknown')
  })
  it('returns em dash for null/undefined', () => {
    expect(detectionMethodLabel(null)).toBe('—')
    expect(detectionMethodLabel(undefined)).toBe('—')
  })
})

describe('connectionLabel', () => {
  it('returns Connected for CONNECTED', () => expect(connectionLabel('CONNECTED')).toBe('Connected'))
  it('returns Connecting for CONNECTING', () => expect(connectionLabel('CONNECTING')).toContain('Connecting'))
  it('returns operator conflict for CONFLICT', () => expect(connectionLabel('CONFLICT')).toContain('conflict'))
  it('returns failed for FAILED', () => expect(connectionLabel('FAILED')).toContain('failed'))
})

describe('strengthBadgeClasses', () => {
  it('STRONG uses emerald', () => expect(strengthBadgeClasses('STRONG')).toContain('emerald'))
  it('MODERATE uses yellow', () => expect(strengthBadgeClasses('MODERATE')).toContain('yellow'))
  it('WEAK uses red', () => expect(strengthBadgeClasses('WEAK')).toContain('red'))
})
