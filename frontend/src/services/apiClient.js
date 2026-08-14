/**
 * ATLAS — REST API client
 *
 * Thin wrappers around every Phase 7 + Phase 8 backend endpoint.
 * All functions return plain objects (parsed JSON) or throw an Error.
 *
 * Error convention:
 *   - Throws an Error with a human-readable message for HTTP errors.
 *   - The message includes the HTTP status code so callers can distinguish
 *     503 (not ready), 400 (bad input), 409 (conflict) etc.
 *   - Network failures produce an Error with message starting "Network error".
 *
 * All paths are relative (/api/...) so that the Vite dev-server proxy
 * routes them to http://localhost:8000 during development.
 */

const JSON_HEADERS = { 'Content-Type': 'application/json' }

/**
 * Generic fetch wrapper with error handling.
 * @param {string} path
 * @param {RequestInit} [options]
 * @returns {Promise<object>}
 */
async function apiFetch(path, options = {}) {
  let response
  try {
    response = await fetch(path, options)
  } catch (err) {
    throw new Error(`Network error: ${err.message}`)
  }
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json()
      if (body?.detail) detail = body.detail
    } catch {
      // ignore parse error — use statusText
    }
    throw new Error(`HTTP ${response.status}: ${detail}`)
  }
  return response.json()
}

// ── Telemetry ─────────────────────────────────────────────────────────────────

/**
 * GET /api/telemetry/snapshot
 * Returns the most recently processed TelemetryRecord.
 * Throws HTTP 503 if stream has not started.
 * @returns {Promise<{ tick: number, timestamp: string, telemetry: object }>}
 */
export function fetchSnapshot() {
  return apiFetch('/api/telemetry/snapshot')
}

// ── Analysis ──────────────────────────────────────────────────────────────────

/**
 * GET /api/analysis/status
 * Returns { analytics: AnalyticsResult, risk: RiskResult }.
 * Throws HTTP 503 if stream has not started.
 * @returns {Promise<{ analytics: object, risk: object }>}
 */
export function fetchAnalysisStatus() {
  return apiFetch('/api/analysis/status')
}

/**
 * GET /api/analysis/explain
 * Returns { explanation: string, subsystem: string }.
 * May be slow (calls Granite).  Returns fallback string if Granite unavailable.
 * Throws HTTP 503 if stream has not started.
 * @returns {Promise<{ explanation: string, subsystem: string }>}
 */
export function fetchAnomalyExplanation() {
  return apiFetch('/api/analysis/explain')
}

// ── Decision ──────────────────────────────────────────────────────────────────

/**
 * GET /api/decision/options
 * Returns DecisionResult (options ranked by projected risk ascending).
 * Throws HTTP 503 if stream has not started.
 * @returns {Promise<object>}
 */
export function fetchDecisionOptions() {
  return apiFetch('/api/decision/options')
}

/**
 * POST /api/decision/whatif
 * @param {string} optionId  — scenario option key (e.g. "SWITCH_REDUNDANT")
 * Returns { what_if: WhatIfResult, ai_narrative: string }.
 * Throws HTTP 400 if option_id unknown, 503 if no ticks.
 * @returns {Promise<{ what_if: object, ai_narrative: string }>}
 */
export function fetchWhatIf(optionId) {
  return apiFetch('/api/decision/whatif', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ option_id: optionId }),
  })
}

// ── Copilot ───────────────────────────────────────────────────────────────────

/**
 * POST /api/copilot/ask
 * @param {string} question  — operator question (non-empty, non-whitespace-only)
 * Returns { answer: string }.
 * Throws HTTP 400 if question empty, 503 if no ticks.
 * @returns {Promise<{ answer: string }>}
 */
export function askCopilot(question) {
  return apiFetch('/api/copilot/ask', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ question }),
  })
}

// ── Health ────────────────────────────────────────────────────────────────────

/**
 * GET /health
 * Returns { status: "ok", service: "ATLAS" }.
 * Used to verify backend is reachable before the SSE stream is started.
 * @returns {Promise<{ status: string, service: string }>}
 */
export function fetchHealth() {
  return apiFetch('/health')
}
