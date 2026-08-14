/**
 * ATLAS — App integration smoke test
 *
 * Verifies the application shell renders without throwing.
 * All context-consuming panels are mocked to avoid SSE connection
 * and complex rendering dependencies.
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

// Mock SSE client so AtlasProvider doesn't open real connections in tests
vi.mock('../services/sseClient.js', () => ({
  SSE_STATE: {
    CONNECTING: 'CONNECTING',
    CONNECTED: 'CONNECTED',
    DISCONNECTED: 'DISCONNECTED',
    CONFLICT: 'CONFLICT',
    FAILED: 'FAILED',
  },
  createSSEClient: vi.fn(() => ({
    destroy: vi.fn(),
  })),
}))

// Mock apiClient to avoid fetch calls during mount
vi.mock('../services/apiClient.js', () => ({
  fetchAnomalyExplanation: vi.fn().mockResolvedValue({ explanation: '', subsystem: '' }),
  fetchDecisionOptions: vi.fn().mockResolvedValue({ options: [], current_risk_score: 0 }),
  fetchWhatIf: vi.fn().mockResolvedValue({ what_if: {}, ai_narrative: '' }),
  askCopilot: vi.fn().mockResolvedValue({ answer: '' }),
  fetchHealth: vi.fn().mockResolvedValue({ status: 'ok' }),
  fetchSnapshot: vi.fn().mockResolvedValue({}),
  fetchAnalysisStatus: vi.fn().mockResolvedValue({}),
}))

import App from '../App.jsx'

describe('App', () => {
  it('renders without throwing', () => {
    render(<App />)
  })

  it('renders ATLAS identity text', () => {
    render(<App />)
    expect(screen.getByText('ATLAS')).toBeDefined()
  })

  it('renders panel section roles', () => {
    render(<App />)
    // All four panels are <section> with aria-label
    expect(screen.getByRole('region', { name: /Telemetry/i })).toBeDefined()
    expect(screen.getByRole('region', { name: /Intelligence/i })).toBeDefined()
    expect(screen.getByRole('region', { name: /Decision Center/i })).toBeDefined()
    expect(screen.getByRole('region', { name: /Copilot/i })).toBeDefined()
  })

  it('renders the main panel grid', () => {
    render(<App />)
    expect(screen.getByRole('main', { name: /Mission control panels/i })).toBeDefined()
  })
})
