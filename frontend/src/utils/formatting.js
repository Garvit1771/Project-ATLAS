/**
 * ATLAS — Value formatting utilities
 *
 * Centralises number formatting, unit display, and telemetry variable
 * metadata so that all panels display values consistently.
 */

// ── Telemetry variable metadata ───────────────────────────────────────────────

/**
 * Human-readable label, unit, and normal-range info for each telemetry variable.
 * Matches data/normal_ranges.json.
 */
export const TELEMETRY_META = {
  battery_voltage_v:         { label: 'Battery Voltage',       unit: 'V',      fmt: 1 },
  battery_temp_c:            { label: 'Battery Temp',          unit: '°C',     fmt: 1 },
  solar_power_w:             { label: 'Solar Power',           unit: 'W',      fmt: 1 },
  cpu_temp_c:                { label: 'CPU Temp',              unit: '°C',     fmt: 1 },
  cpu_load_pct:              { label: 'CPU Load',              unit: '%',      fmt: 1 },
  thruster_1_temp_c:         { label: 'Thruster 1 Temp',       unit: '°C',     fmt: 1 },
  thruster_2_temp_c:         { label: 'Thruster 2 Temp',       unit: '°C',     fmt: 1 },
  thruster_2_vibration_hz:   { label: 'Thruster 2 Vibration',  unit: 'Hz',     fmt: 2 },
  thruster_2_efficiency_pct: { label: 'Thruster 2 Efficiency', unit: '%',      fmt: 1 },
  attitude_error_deg:        { label: 'Attitude Error',        unit: '°',      fmt: 3 },
  signal_strength_dbm:       { label: 'Signal Strength',       unit: 'dBm',   fmt: 1 },
  packet_loss_pct:           { label: 'Packet Loss',           unit: '%',      fmt: 2 },
  radiation_level_mgy:       { label: 'Radiation',             unit: 'mGy/h', fmt: 3 },
}

/**
 * Variables to display per subsystem in the Telemetry panel.
 * Each entry is [variable_key, line_color_hex].
 * Colors are chosen to be distinct and readable on a dark background.
 */
export const SUBSYSTEM_VARIABLES = {
  propulsion: [
    ['thruster_2_temp_c',         '#f97316'],  // orange
    ['thruster_2_vibration_hz',   '#ef4444'],  // red
    ['thruster_2_efficiency_pct', '#22c55e'],  // green
  ],
  power: [
    ['battery_voltage_v',  '#60a5fa'],  // blue
    ['battery_temp_c',     '#f472b6'],  // pink
    ['solar_power_w',      '#facc15'],  // yellow
  ],
  computing: [
    ['cpu_temp_c',    '#a78bfa'],  // violet
    ['cpu_load_pct',  '#34d399'],  // emerald
  ],
  attitude: [
    ['attitude_error_deg', '#fb923c'],  // orange
  ],
  comms: [
    ['signal_strength_dbm', '#38bdf8'],  // sky
    ['packet_loss_pct',     '#f87171'],  // red-light
  ],
  environment: [
    ['radiation_level_mgy', '#4ade80'],  // green-light
  ],
}

export const SUBSYSTEM_LABELS = {
  propulsion:  'Propulsion',
  power:       'Power',
  computing:   'Computing',
  attitude:    'Attitude',
  comms:       'Comms',
  environment: 'Environment',
}

// ── Formatters ────────────────────────────────────────────────────────────────

/**
 * Format a telemetry value with the appropriate decimal places.
 * @param {string} variable
 * @param {number} value
 * @returns {string}
 */
export function formatTelemetryValue(variable, value) {
  const meta = TELEMETRY_META[variable]
  if (!meta) return String(value)
  return `${value.toFixed(meta.fmt)} ${meta.unit}`
}

/**
 * Format a risk score as a percentage string.
 * @param {number} score — 0.0 to 1.0
 * @returns {string}
 */
export function formatRiskScore(score) {
  if (score == null) return '—'
  return `${(score * 100).toFixed(1)}%`
}

/**
 * Format a risk delta (projected - current) with sign and percentage.
 * @param {number} delta
 * @returns {{ text: string, isReduction: boolean }}
 */
export function formatRiskDelta(delta) {
  const pct = (Math.abs(delta) * 100).toFixed(1)
  const isReduction = delta < 0
  return {
    text: `${isReduction ? '−' : '+'}${pct}%`,
    isReduction,
  }
}

/**
 * Format a timestamp string to HH:MM:SS UTC.
 * @param {string} isoString
 * @returns {string}
 */
export function formatTimestamp(isoString) {
  if (!isoString) return '—'
  try {
    const d = new Date(isoString)
    return d.toISOString().substring(11, 19) + ' UTC'
  } catch {
    return isoString
  }
}

/**
 * Format minutes as "X min Y sec" or "< 1 min".
 * @param {number|null} minutes
 * @returns {string}
 */
export function formatBreachMinutes(minutes) {
  if (minutes == null) return null
  if (minutes === 0) return 'Imminent'
  if (minutes < 1) return '< 1 min'
  const m = Math.floor(minutes)
  const s = Math.round((minutes - m) * 60)
  return s > 0 ? `${m}m ${s}s` : `${m} min`
}
