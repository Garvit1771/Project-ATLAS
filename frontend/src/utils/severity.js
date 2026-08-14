/**
 * ATLAS — Severity and state utilities
 *
 * Maps severity levels, confidence bands, connection states, and
 * recommendation strengths to their visual representation (Tailwind
 * class names, labels, and priority ordering).
 *
 * All visual decisions are centralised here so components stay clean.
 */

// ── Severity ──────────────────────────────────────────────────────────────────

/**
 * Tailwind text-color class for a given severity string.
 */
export function severityTextColor(severity) {
  switch (severity) {
    case 'CRITICAL': return 'text-red-400'
    case 'HIGH':     return 'text-orange-400'
    case 'MODERATE': return 'text-yellow-400'
    case 'LOW':      return 'text-blue-400'
    default:         return 'text-slate-400'
  }
}

/**
 * Tailwind border + background badge classes for a given severity.
 */
export function severityBadgeClasses(severity) {
  switch (severity) {
    case 'CRITICAL': return 'bg-red-950 border border-red-700 text-red-300'
    case 'HIGH':     return 'bg-orange-950 border border-orange-700 text-orange-300'
    case 'MODERATE': return 'bg-yellow-950 border border-yellow-700 text-yellow-300'
    case 'LOW':      return 'bg-blue-950 border border-blue-700 text-blue-300'
    default:         return 'bg-slate-800 border border-slate-600 text-slate-400'
  }
}

/**
 * Tailwind ring / indicator dot color for a severity level.
 * Used for the health indicator dot in the Mission Header.
 */
export function severityDotColor(severity) {
  switch (severity) {
    case 'CRITICAL': return 'bg-red-500'
    case 'HIGH':     return 'bg-orange-500'
    case 'MODERATE': return 'bg-yellow-500'
    case 'LOW':      return 'bg-blue-500'
    default:         return 'bg-green-500'
  }
}

/**
 * Human-readable severity label including an accessible text descriptor.
 */
export function severityLabel(severity) {
  switch (severity) {
    case 'CRITICAL': return 'Critical'
    case 'HIGH':     return 'High'
    case 'MODERATE': return 'Moderate'
    case 'LOW':      return 'Low'
    default:         return 'Nominal'
  }
}

/**
 * True when the severity is elevated (not NONE/undefined).
 */
export function isElevatedSeverity(severity) {
  return severity && severity !== 'NONE'
}

/**
 * True when the severity warrants an alert banner (HIGH or CRITICAL).
 */
export function isCriticalSeverity(severity) {
  return severity === 'HIGH' || severity === 'CRITICAL'
}

// ── Confidence band ───────────────────────────────────────────────────────────

export function confidenceBandTextColor(band) {
  switch (band) {
    case 'HIGH':     return 'text-emerald-400'
    case 'MODERATE': return 'text-yellow-400'
    case 'LOW':      return 'text-slate-400'
    default:         return 'text-slate-500'
  }
}

// ── Detection method ──────────────────────────────────────────────────────────

export function detectionMethodLabel(method) {
  switch (method) {
    case 'hard_threshold':             return 'Hard threshold breach'
    case 'rolling_zscore':             return 'Rolling z-score'
    case 'rolling_zscore+correlation': return 'Z-score + cross-signal correlation'
    default:                           return method || '—'
  }
}

// ── Recommendation strength ───────────────────────────────────────────────────

export function strengthBadgeClasses(strength) {
  switch (strength) {
    case 'STRONG':   return 'bg-emerald-950 border border-emerald-700 text-emerald-300'
    case 'MODERATE': return 'bg-yellow-950 border border-yellow-700 text-yellow-300'
    case 'WEAK':     return 'bg-red-950 border border-red-700 text-red-300'
    default:         return 'bg-slate-800 border border-slate-600 text-slate-400'
  }
}

// ── Connection state ──────────────────────────────────────────────────────────

export function connectionLabel(sseState) {
  switch (sseState) {
    case 'CONNECTED':    return 'Connected'
    case 'CONNECTING':   return 'Connecting…'
    case 'DISCONNECTED': return 'Reconnecting…'
    case 'CONFLICT':     return 'Operator conflict'
    case 'FAILED':       return 'Connection failed'
    default:             return 'Unknown'
  }
}

export function connectionDotColor(sseState) {
  switch (sseState) {
    case 'CONNECTED':    return 'bg-green-500'
    case 'CONNECTING':   return 'bg-yellow-500'
    case 'DISCONNECTED': return 'bg-orange-500'
    case 'CONFLICT':     return 'bg-red-500'
    case 'FAILED':       return 'bg-red-700'
    default:             return 'bg-slate-500'
  }
}
