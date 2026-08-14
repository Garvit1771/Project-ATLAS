/**
 * ATLAS — CopilotPanel component tests
 *
 * Verifies:
 *   1. Waiting state (no telemetry data)
 *   2. Prompt renders when data is available
 *   3. Send button is disabled while loading
 *   4. User message appears immediately on submit
 *   5. Error fallback message when sendCopilotQuestion throws
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import CopilotPanel from '../components/CopilotPanel.jsx'

vi.mock('../state/AtlasContext.jsx', () => ({
  useAtlas: vi.fn(),
}))

import { useAtlas } from '../state/AtlasContext.jsx'

function makeState(overrides = {}) {
  return {
    sseState: 'CONNECTED',
    latestAnalytics: null,
    latestRisk: null,
    copilotLoading: false,
    copilotError: null,
    ...overrides,
  }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('CopilotPanel — no data', () => {
  it('shows prompt to start telemetry stream', () => {
    useAtlas.mockReturnValue({
      state: makeState(),
      sendCopilotQuestion: vi.fn(),
    })
    render(<CopilotPanel />)
    expect(screen.getByText(/Start the telemetry stream to activate the Copilot/i)).toBeDefined()
  })

  it('shows conflict message when SSE is CONFLICT', () => {
    useAtlas.mockReturnValue({
      state: makeState({ sseState: 'CONFLICT' }),
      sendCopilotQuestion: vi.fn(),
    })
    render(<CopilotPanel />)
    expect(screen.getByText(/Another operator is streaming/i)).toBeDefined()
  })
})

describe('CopilotPanel — active state', () => {
  beforeEach(() => {
    useAtlas.mockReturnValue({
      state: makeState({
        latestAnalytics: { composite_anomaly: false, detections: [] },
      }),
      sendCopilotQuestion: vi.fn().mockResolvedValue('All systems nominal.'),
    })
  })

  it('renders input placeholder', () => {
    render(<CopilotPanel />)
    expect(screen.getByPlaceholderText(/Ask the Copilot/i)).toBeDefined()
  })

  it('renders Send button', () => {
    render(<CopilotPanel />)
    expect(screen.getByRole('button', { name: /Send question/i })).toBeDefined()
  })

  it('Send button is disabled when input is empty', () => {
    render(<CopilotPanel />)
    const btn = screen.getByRole('button', { name: /Send question/i })
    expect(btn.disabled).toBe(true)
  })

  it('Send button is enabled when input has non-whitespace text', () => {
    render(<CopilotPanel />)
    const textarea = screen.getByLabelText(/Your question/i)
    fireEvent.change(textarea, { target: { value: 'What is the anomaly?' } })
    const btn = screen.getByRole('button', { name: /Send question/i })
    expect(btn.disabled).toBe(false)
  })

  it('appends user message to chat on submit', async () => {
    render(<CopilotPanel />)
    const textarea = screen.getByLabelText(/Your question/i)
    fireEvent.change(textarea, { target: { value: 'What subsystem is failing?' } })
    fireEvent.click(screen.getByRole('button', { name: /Send question/i }))
    // User message should appear immediately (optimistic UI)
    await waitFor(() => {
      expect(screen.getByText('What subsystem is failing?')).toBeDefined()
    })
  })

  it('appends assistant response after sendCopilotQuestion resolves', async () => {
    render(<CopilotPanel />)
    const textarea = screen.getByLabelText(/Your question/i)
    fireEvent.change(textarea, { target: { value: 'Status?' } })
    fireEvent.click(screen.getByRole('button', { name: /Send question/i }))
    await waitFor(() => {
      expect(screen.getByText('All systems nominal.')).toBeDefined()
    })
  })

  it('shows fallback error message when sendCopilotQuestion throws', async () => {
    useAtlas.mockReturnValue({
      state: makeState({
        latestAnalytics: { composite_anomaly: false, detections: [] },
      }),
      sendCopilotQuestion: vi.fn().mockRejectedValue(new Error('Network error')),
    })
    render(<CopilotPanel />)
    const textarea = screen.getByLabelText(/Your question/i)
    fireEvent.change(textarea, { target: { value: 'Hello?' } })
    fireEvent.click(screen.getByRole('button', { name: /Send question/i }))
    await waitFor(() => {
      expect(screen.getByText(/Unable to reach the Copilot/i)).toBeDefined()
    })
  })
})

describe('CopilotPanel — loading state', () => {
  it('disables input and send button while copilotLoading is true', () => {
    useAtlas.mockReturnValue({
      state: makeState({
        latestAnalytics: { composite_anomaly: false, detections: [] },
        copilotLoading: true,
      }),
      sendCopilotQuestion: vi.fn(),
    })
    render(<CopilotPanel />)
    const textarea = screen.getByLabelText(/Your question/i)
    expect(textarea.disabled).toBe(true)
    const btn = screen.getByRole('button', { name: /Send question/i })
    expect(btn.disabled).toBe(true)
  })
})
