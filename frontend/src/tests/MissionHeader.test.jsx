/**
 * ATLAS — MissionHeader component tests
 *
 * MissionHeader reads from AtlasContext via useAtlas().
 * We mock the module so rendering is fully controlled by test fixtures.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import MissionHeader from '../components/MissionHeader.jsx'

// ── useAtlas mock factory ─────────────────────────────────────────────────────

function makeAtlasState(overrides = {}) {
  return {
    sseState: 'CONNECTED',
    latestTick: null,
    latestAnalytics: null,
    latestRisk: null,
    ...overrides,
  }
}

vi.mock('../state/AtlasContext.jsx', () => ({
  useAtlas: vi.fn(),
}))

import { useAtlas } from '../state/AtlasContext.jsx'

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('MissionHeader', () => {
  beforeEach(() => {
    useAtlas.mockReturnValue({ state: makeAtlasState() })
  })

  it('renders ATLAS identity', () => {
    render(<MissionHeader />)
    expect(screen.getByText('ATLAS')).toBeDefined()
  })

  it('renders scenario name ALPHA-1-FAULT-01', () => {
    render(<MissionHeader />)
    expect(screen.getByText('ALPHA-1-FAULT-01')).toBeDefined()
  })

  it('renders mission phase Orbital Insertion', () => {
    render(<MissionHeader />)
    expect(screen.getByText('Orbital Insertion')).toBeDefined()
  })

  it('renders dash for tick when no telemetry received', () => {
    render(<MissionHeader />)
    // tick column shows em-dash when null
    expect(screen.getByText('—')).toBeDefined()
  })

  it('renders padded tick number when telemetry is live', () => {
    useAtlas.mockReturnValue({
      state: makeAtlasState({
        latestTick: { tick: 42, timestamp: '2025-01-01T00:00:42Z' },
        latestRisk: { risk_score: 0.3, severity: 'LOW' },
      }),
    })
    render(<MissionHeader />)
    expect(screen.getByText('00042')).toBeDefined()
  })

  it('renders connection label for CONNECTED state', () => {
    useAtlas.mockReturnValue({ state: makeAtlasState({ sseState: 'CONNECTED' }) })
    render(<MissionHeader />)
    // connectionLabel('CONNECTED') returns 'Connected'
    expect(screen.getByText('Connected')).toBeDefined()
  })

  it('renders connection label for CONNECTING state', () => {
    useAtlas.mockReturnValue({ state: makeAtlasState({ sseState: 'CONNECTING' }) })
    render(<MissionHeader />)
    expect(screen.getByText('Connecting…')).toBeDefined()
  })

  it('does not show alert banner when severity is NONE', () => {
    useAtlas.mockReturnValue({
      state: makeAtlasState({
        latestRisk: { risk_score: 0.1, severity: 'NONE' },
      }),
    })
    render(<MissionHeader />)
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('shows alert banner with role=alert when severity is HIGH', () => {
    useAtlas.mockReturnValue({
      state: makeAtlasState({
        latestRisk: { risk_score: 0.82, severity: 'HIGH', dominant_variable: 'chamber_pressure_bar' },
        latestAnalytics: { correlated_signals: ['chamber_pressure_bar', 'thrust_n', 'fuel_flow_kg_s'] },
      }),
    })
    render(<MissionHeader />)
    const alert = screen.getByRole('alert')
    expect(alert).toBeDefined()
    expect(alert.textContent).toContain('Alert')
  })

  it('shows caution banner for MEDIUM severity', () => {
    useAtlas.mockReturnValue({
      state: makeAtlasState({
        latestRisk: { risk_score: 0.52, severity: 'MEDIUM', dominant_variable: null },
        latestAnalytics: { correlated_signals: [] },
      }),
    })
    render(<MissionHeader />)
    const alert = screen.getByRole('alert')
    expect(alert.textContent).toContain('Caution')
  })

  it('renders risk score when latestRisk is present', () => {
    useAtlas.mockReturnValue({
      state: makeAtlasState({
        latestRisk: { risk_score: 0.74, severity: 'HIGH' },
      }),
    })
    render(<MissionHeader />)
    // formatRiskScore(0.74) = '74.0%'
    expect(screen.getByText(/74\.0%/)).toBeDefined()
  })
})
