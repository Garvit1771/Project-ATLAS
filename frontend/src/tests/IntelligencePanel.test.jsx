/**
 * ATLAS — IntelligencePanel component tests
 *
 * Verifies the three display states:
 *   1. No data (waiting for stream)
 *   2. Nominal — no anomaly detected
 *   3. Anomaly active — detections + AI explanation block
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import IntelligencePanel from '../components/IntelligencePanel.jsx'

vi.mock('../state/AtlasContext.jsx', () => ({
  useAtlas: vi.fn(),
}))

import { useAtlas } from '../state/AtlasContext.jsx'

const noOpRefresh = vi.fn()

function makeState(overrides = {}) {
  return {
    sseState: 'CONNECTED',
    latestAnalytics: null,
    latestRisk: null,
    explanation: null,
    explanationLoading: false,
    explanationError: null,
    ...overrides,
  }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('IntelligencePanel — no data', () => {
  it('shows waiting message before stream connects', () => {
    useAtlas.mockReturnValue({ state: makeState(), refreshExplanation: noOpRefresh })
    render(<IntelligencePanel />)
    expect(screen.getByText(/Waiting for telemetry stream/i)).toBeDefined()
  })

  it('shows conflict message when SSE state is CONFLICT', () => {
    useAtlas.mockReturnValue({
      state: makeState({ sseState: 'CONFLICT' }),
      refreshExplanation: noOpRefresh,
    })
    render(<IntelligencePanel />)
    expect(screen.getByText(/Another operator is streaming/i)).toBeDefined()
  })
})

describe('IntelligencePanel — nominal state', () => {
  beforeEach(() => {
    useAtlas.mockReturnValue({
      state: makeState({
        latestAnalytics: { composite_anomaly: false, detections: [], correlated_signals: [] },
        latestRisk: { risk_score: 0.12, severity: 'NONE', dominant_variable: null, redundancy_available: true },
      }),
      refreshExplanation: noOpRefresh,
    })
  })

  it('shows nominal status when no anomalies', () => {
    render(<IntelligencePanel />)
    expect(screen.getByText(/No anomalies detected/i)).toBeDefined()
  })

  it('does not render detection cards when detections array is empty', () => {
    render(<IntelligencePanel />)
    expect(screen.queryByText(/Detected signals/i)).toBeNull()
  })
})

describe('IntelligencePanel — anomaly state', () => {
  const anomalyAnalytics = {
    composite_anomaly: true,
    composite_severity: 'HIGH',
    composite_subsystem: 'propulsion',
    composite_confidence_band: 'HIGH',
    correlated_signals: ['chamber_pressure_bar', 'thrust_n', 'fuel_flow_kg_s'],
    detections: [
      {
        variable: 'chamber_pressure_bar',
        subsystem: 'propulsion',
        detection_method: 'threshold',
        evidence: ['Value 38.2 exceeds upper threshold 35.0'],
        trend_direction: 'rising',
      },
    ],
  }
  const anomalyRisk = {
    risk_score: 0.83,
    severity: 'HIGH',
    dominant_variable: 'chamber_pressure_bar',
    redundancy_available: false,
    estimated_threshold_breach_minutes: 2.4,
  }

  beforeEach(() => {
    useAtlas.mockReturnValue({
      state: makeState({ latestAnalytics: anomalyAnalytics, latestRisk: anomalyRisk }),
      refreshExplanation: noOpRefresh,
    })
  })

  it('renders cross-signal correlation header', () => {
    render(<IntelligencePanel />)
    expect(screen.getByText(/Cross-signal correlation/i)).toBeDefined()
  })

  it('renders correlated signal chips', () => {
    render(<IntelligencePanel />)
    expect(screen.getByText('chamber_pressure_bar')).toBeDefined()
    expect(screen.getByText('thrust_n')).toBeDefined()
  })

  it('renders the detection card for the flagged variable', () => {
    render(<IntelligencePanel />)
    expect(screen.getByText(/Detected signals/i)).toBeDefined()
  })

  it('renders evidence statement from detection', () => {
    render(<IntelligencePanel />)
    expect(screen.getByText(/Value 38.2 exceeds upper threshold 35.0/i)).toBeDefined()
  })

  it('renders risk score from latestRisk', () => {
    render(<IntelligencePanel />)
    // formatRiskScore(0.83) = '83.0%'
    expect(screen.getByText(/83\.0%/)).toBeDefined()
  })

  it('renders estimated breach time', () => {
    render(<IntelligencePanel />)
    // formatBreachMinutes(2.4): 2 min + round(0.4*60)=24s → '2m 24s'
    expect(screen.getByText(/2m 24s/i)).toBeDefined()
  })

  it('renders "Generate AI explanation" button when no explanation yet', () => {
    render(<IntelligencePanel />)
    expect(screen.getByText(/Generate AI explanation/i)).toBeDefined()
  })

  it('calls refreshExplanation when generate button is clicked', () => {
    const mockRefresh = vi.fn()
    useAtlas.mockReturnValue({
      state: makeState({ latestAnalytics: anomalyAnalytics, latestRisk: anomalyRisk }),
      refreshExplanation: mockRefresh,
    })
    render(<IntelligencePanel />)
    fireEvent.click(screen.getByText(/Generate AI explanation/i))
    expect(mockRefresh).toHaveBeenCalledTimes(1)
  })
})

describe('IntelligencePanel — AI explanation block', () => {
  const minAnalytics = {
    composite_anomaly: true,
    composite_severity: 'HIGH',
    composite_subsystem: 'propulsion',
    correlated_signals: [],
    detections: [],
  }

  it('renders AI explanation text when explanation is loaded', () => {
    useAtlas.mockReturnValue({
      state: makeState({
        latestAnalytics: minAnalytics,
        latestRisk: { risk_score: 0.8, severity: 'HIGH', dominant_variable: null, redundancy_available: false },
        explanation: {
          explanation: 'Propulsion chamber pressure has exceeded nominal range.',
          subsystem: 'propulsion',
        },
      }),
      refreshExplanation: noOpRefresh,
    })
    render(<IntelligencePanel />)
    expect(screen.getByText(/Propulsion chamber pressure has exceeded nominal range/i)).toBeDefined()
  })

  it('renders loading spinner while explanation is fetching', () => {
    useAtlas.mockReturnValue({
      state: makeState({
        latestAnalytics: minAnalytics,
        latestRisk: { risk_score: 0.8, severity: 'HIGH', dominant_variable: null, redundancy_available: false },
        explanationLoading: true,
      }),
      refreshExplanation: noOpRefresh,
    })
    render(<IntelligencePanel />)
    expect(screen.getByText(/Generating explanation/i)).toBeDefined()
  })

  it('renders error message when explanation fetch fails', () => {
    useAtlas.mockReturnValue({
      state: makeState({
        latestAnalytics: minAnalytics,
        latestRisk: { risk_score: 0.8, severity: 'HIGH', dominant_variable: null, redundancy_available: false },
        explanationError: 'Granite unavailable',
      }),
      refreshExplanation: noOpRefresh,
    })
    render(<IntelligencePanel />)
    expect(screen.getByText(/Granite unavailable/i)).toBeDefined()
  })
})
