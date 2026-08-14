/**
 * ATLAS — API client tests
 *
 * Tests fetch wrapping, error handling, and response parsing.
 * All network calls are intercepted with vi.stubGlobal('fetch', ...).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  fetchSnapshot,
  fetchAnalysisStatus,
  fetchAnomalyExplanation,
  fetchDecisionOptions,
  fetchWhatIf,
  askCopilot,
  fetchHealth,
} from '../services/apiClient.js'

function mockFetch(status, body) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'Error',
    json: () => Promise.resolve(body),
  })
}

function mockFetchNetworkError() {
  return vi.fn().mockRejectedValue(new Error('Failed to fetch'))
}

describe('fetchHealth', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('returns parsed body on 200', async () => {
    vi.stubGlobal('fetch', mockFetch(200, { status: 'ok', service: 'ATLAS' }))
    const result = await fetchHealth()
    expect(result.status).toBe('ok')
    expect(result.service).toBe('ATLAS')
  })

  it('throws on network error', async () => {
    vi.stubGlobal('fetch', mockFetchNetworkError())
    await expect(fetchHealth()).rejects.toThrow('Network error')
  })

  it('throws on HTTP 500 with status code in message', async () => {
    vi.stubGlobal('fetch', mockFetch(500, {}))
    await expect(fetchHealth()).rejects.toThrow('HTTP 500')
  })
})

describe('fetchSnapshot', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('calls /api/telemetry/snapshot', async () => {
    const spy = mockFetch(200, { tick: 0, timestamp: 'T', telemetry: {} })
    vi.stubGlobal('fetch', spy)
    await fetchSnapshot()
    expect(spy).toHaveBeenCalledWith('/api/telemetry/snapshot', {})
  })

  it('throws HTTP 503 when backend returns 503', async () => {
    vi.stubGlobal('fetch', mockFetch(503, { detail: 'No data' }))
    await expect(fetchSnapshot()).rejects.toThrow('HTTP 503')
  })
})

describe('fetchAnalysisStatus', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('calls /api/analysis/status', async () => {
    const spy = mockFetch(200, { analytics: {}, risk: {} })
    vi.stubGlobal('fetch', spy)
    await fetchAnalysisStatus()
    expect(spy).toHaveBeenCalledWith('/api/analysis/status', {})
  })
})

describe('fetchAnomalyExplanation', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('calls /api/analysis/explain', async () => {
    const spy = mockFetch(200, { explanation: 'Test explanation', subsystem: 'propulsion' })
    vi.stubGlobal('fetch', spy)
    const result = await fetchAnomalyExplanation()
    expect(spy).toHaveBeenCalledWith('/api/analysis/explain', {})
    expect(result.explanation).toBe('Test explanation')
    expect(result.subsystem).toBe('propulsion')
  })
})

describe('fetchDecisionOptions', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('calls /api/decision/options', async () => {
    const spy = mockFetch(200, { options: [], current_risk_score: 0.5 })
    vi.stubGlobal('fetch', spy)
    await fetchDecisionOptions()
    expect(spy).toHaveBeenCalledWith('/api/decision/options', {})
  })
})

describe('fetchWhatIf', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('calls /api/decision/whatif with POST and option_id', async () => {
    const spy = mockFetch(200, { what_if: {}, ai_narrative: 'narrative' })
    vi.stubGlobal('fetch', spy)
    await fetchWhatIf('SWITCH_REDUNDANT')
    expect(spy).toHaveBeenCalledWith('/api/decision/whatif', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ option_id: 'SWITCH_REDUNDANT' }),
    })
  })

  it('throws HTTP 400 for unknown option', async () => {
    vi.stubGlobal('fetch', mockFetch(400, { detail: 'Option not found' }))
    await expect(fetchWhatIf('BOGUS')).rejects.toThrow('HTTP 400')
  })
})

describe('askCopilot', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('calls /api/copilot/ask with POST and question', async () => {
    const spy = mockFetch(200, { answer: 'The anomaly is in the propulsion subsystem.' })
    vi.stubGlobal('fetch', spy)
    await askCopilot('What is happening?')
    expect(spy).toHaveBeenCalledWith('/api/copilot/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: 'What is happening?' }),
    })
  })

  it('returns answer in response', async () => {
    vi.stubGlobal('fetch', mockFetch(200, { answer: 'Propulsion anomaly detected.' }))
    const result = await askCopilot('Status?')
    expect(result.answer).toBe('Propulsion anomaly detected.')
  })

  it('throws HTTP 400 for whitespace-only question', async () => {
    vi.stubGlobal('fetch', mockFetch(400, { detail: 'whitespace' }))
    await expect(askCopilot('   ')).rejects.toThrow('HTTP 400')
  })
})
