/**
 * ATLAS — DecisionCenterPanel component tests
 *
 * Verifies:
 *   1. Waiting state (no telemetry)
 *   2. Ready state — load options button present
 *   3. Options rendered with computed values
 *   4. Operator action buttons (ACCEPT / REJECT / INVESTIGATE) on selected card
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import DecisionCenterPanel from '../components/DecisionCenterPanel.jsx'

vi.mock('../state/AtlasContext.jsx', () => ({
  useAtlas: vi.fn(),
}))

import { useAtlas } from '../state/AtlasContext.jsx'

const noop = vi.fn()

function makeState(overrides = {}) {
  return {
    sseState: 'CONNECTED',
    latestRisk: null,
    latestTick: null,
    decisionResult: null,
    decisionLoading: false,
    decisionError: null,
    whatIfResult: null,
    whatIfLoading: false,
    whatIfError: null,
    whatIfOptionId: null,
    ...overrides,
  }
}

const sampleOptions = [
  {
    option_id: 'SWITCH_REDUNDANT',
    label: 'Switch to Redundant Thruster',
    description: 'Activate the backup thruster assembly.',
    recommendation_strength: 'STRONG',
    computed_risk_score_after: 0.31,
    fuel_cost_pct: 2,
    time_delay_min: 5,
    mission_constraint_satisfied: true,
    subsystem_stress: ['propulsion'],
  },
  {
    option_id: 'REDUCE_THRUST',
    label: 'Reduce Thrust 20%',
    description: 'Throttle back to reduce chamber pressure.',
    recommendation_strength: 'MODERATE',
    computed_risk_score_after: 0.45,
    fuel_cost_pct: 0,
    time_delay_min: 0,
    mission_constraint_satisfied: true,
    subsystem_stress: [],
  },
]

const sampleDecisionResult = {
  tick: 42,
  current_risk_score: 0.74,
  options: sampleOptions,
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('DecisionCenterPanel — waiting state', () => {
  it('shows waiting message before stream connects', () => {
    useAtlas.mockReturnValue({
      state: makeState(),
      loadDecisionOptions: noop,
      runWhatIf: noop,
      clearWhatIf: noop,
    })
    render(<DecisionCenterPanel />)
    expect(screen.getByText(/Waiting for telemetry stream/i)).toBeDefined()
  })

  it('shows conflict message when SSE is CONFLICT', () => {
    useAtlas.mockReturnValue({
      state: makeState({ sseState: 'CONFLICT' }),
      loadDecisionOptions: noop,
      runWhatIf: noop,
      clearWhatIf: noop,
    })
    render(<DecisionCenterPanel />)
    expect(screen.getByText(/Another operator is streaming/i)).toBeDefined()
  })
})

describe('DecisionCenterPanel — ready, no options loaded', () => {
  beforeEach(() => {
    useAtlas.mockReturnValue({
      state: makeState({
        latestRisk: { risk_score: 0.74, severity: 'HIGH', dominant_variable: 'chamber_pressure_bar' },
      }),
      loadDecisionOptions: noop,
      runWhatIf: noop,
      clearWhatIf: noop,
    })
  })

  it('renders current risk score', () => {
    render(<DecisionCenterPanel />)
    // formatRiskScore(0.74) = '74.0%'
    expect(screen.getAllByText(/74\.0%/).length).toBeGreaterThan(0)
  })

  it('renders load options button', () => {
    render(<DecisionCenterPanel />)
    expect(screen.getByText(/Load decision options/i)).toBeDefined()
  })

  it('calls loadDecisionOptions when button is clicked', () => {
    const mockLoad = vi.fn()
    useAtlas.mockReturnValue({
      state: makeState({
        latestRisk: { risk_score: 0.74, severity: 'HIGH', dominant_variable: null },
      }),
      loadDecisionOptions: mockLoad,
      runWhatIf: noop,
      clearWhatIf: noop,
    })
    render(<DecisionCenterPanel />)
    fireEvent.click(screen.getByText(/Load decision options/i))
    expect(mockLoad).toHaveBeenCalledTimes(1)
  })

  it('shows loading spinner when decisionLoading is true', () => {
    useAtlas.mockReturnValue({
      state: makeState({
        latestRisk: { risk_score: 0.74, severity: 'HIGH', dominant_variable: null },
        decisionLoading: true,
      }),
      loadDecisionOptions: noop,
      runWhatIf: noop,
      clearWhatIf: noop,
    })
    render(<DecisionCenterPanel />)
    expect(screen.getByText(/Loading options/i)).toBeDefined()
  })

  it('shows error message when decisionError is set', () => {
    useAtlas.mockReturnValue({
      state: makeState({
        latestRisk: { risk_score: 0.74, severity: 'HIGH', dominant_variable: null },
        decisionError: 'Backend unavailable',
      }),
      loadDecisionOptions: noop,
      runWhatIf: noop,
      clearWhatIf: noop,
    })
    render(<DecisionCenterPanel />)
    expect(screen.getByText(/Backend unavailable/i)).toBeDefined()
  })
})

describe('DecisionCenterPanel — options loaded', () => {
  beforeEach(() => {
    useAtlas.mockReturnValue({
      state: makeState({
        latestRisk: { risk_score: 0.74, severity: 'HIGH', dominant_variable: null },
        decisionResult: sampleDecisionResult,
      }),
      loadDecisionOptions: noop,
      runWhatIf: noop,
      clearWhatIf: noop,
    })
  })

  it('renders ranked option labels', () => {
    render(<DecisionCenterPanel />)
    expect(screen.getByText('Switch to Redundant Thruster')).toBeDefined()
    expect(screen.getByText('Reduce Thrust 20%')).toBeDefined()
  })

  it('renders recommendation strength badge', () => {
    render(<DecisionCenterPanel />)
    expect(screen.getByText('STRONG')).toBeDefined()
  })

  it('renders projected risk scores', () => {
    render(<DecisionCenterPanel />)
    // formatRiskScore(0.31) = '31.0%', formatRiskScore(0.45) = '45.0%'
    expect(screen.getByText(/31\.0%/)).toBeDefined()
    expect(screen.getByText(/45\.0%/)).toBeDefined()
  })

  it('renders ACCEPT/REJECT/INVESTIGATE buttons when option card is clicked', () => {
    const mockRunWhatIf = vi.fn()
    useAtlas.mockReturnValue({
      state: makeState({
        latestRisk: { risk_score: 0.74, severity: 'HIGH', dominant_variable: null },
        decisionResult: sampleDecisionResult,
      }),
      loadDecisionOptions: noop,
      runWhatIf: mockRunWhatIf,
      clearWhatIf: noop,
    })
    render(<DecisionCenterPanel />)
    // Click option 1 card
    fireEvent.click(screen.getByRole('button', { name: /Option 1: Switch to Redundant Thruster/i }))
    expect(screen.getByRole('button', { name: /Accept option/i })).toBeDefined()
    expect(screen.getByRole('button', { name: /Reject option/i })).toBeDefined()
    expect(screen.getByRole('button', { name: /Investigate option/i })).toBeDefined()
  })

  it('calls runWhatIf when option is selected', () => {
    const mockRunWhatIf = vi.fn()
    useAtlas.mockReturnValue({
      state: makeState({
        latestRisk: { risk_score: 0.74, severity: 'HIGH', dominant_variable: null },
        decisionResult: sampleDecisionResult,
      }),
      loadDecisionOptions: noop,
      runWhatIf: mockRunWhatIf,
      clearWhatIf: noop,
    })
    render(<DecisionCenterPanel />)
    fireEvent.click(screen.getByRole('button', { name: /Option 1: Switch to Redundant Thruster/i }))
    expect(mockRunWhatIf).toHaveBeenCalledWith('SWITCH_REDUNDANT')
  })
})

describe('DecisionCenterPanel — what-if block', () => {
  it('renders what-if projection when result is available', () => {
    useAtlas.mockReturnValue({
      state: makeState({
        latestRisk: { risk_score: 0.74, severity: 'HIGH', dominant_variable: null },
        decisionResult: sampleDecisionResult,
        whatIfResult: {
          what_if: { current_risk: 0.74, projected_risk: 0.31, delta: -0.43 },
          ai_narrative: 'Switching reduces chamber pressure risk significantly.',
        },
        whatIfOptionId: 'SWITCH_REDUNDANT',
      }),
      loadDecisionOptions: noop,
      runWhatIf: noop,
      clearWhatIf: noop,
    })
    render(<DecisionCenterPanel />)
    expect(screen.getByText(/What-if projection/i)).toBeDefined()
    expect(screen.getByText(/Switching reduces chamber pressure risk significantly/i)).toBeDefined()
  })
})
