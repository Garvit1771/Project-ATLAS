/**
 * ATLAS — Panel component tests
 *
 * Panel is a pure presentational wrapper — no context dependency.
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import Panel from '../components/Panel.jsx'

describe('Panel', () => {
  it('renders the title in the header', () => {
    render(<Panel title="Telemetry">content</Panel>)
    expect(screen.getByText('Telemetry')).toBeDefined()
  })

  it('renders children in the content area', () => {
    render(<Panel title="Test"><span>inner content</span></Panel>)
    expect(screen.getByText('inner content')).toBeDefined()
  })

  it('renders optional badge when provided', () => {
    render(
      <Panel title="Intelligence" badge={<span>CRITICAL</span>}>
        body
      </Panel>
    )
    expect(screen.getByText('CRITICAL')).toBeDefined()
  })

  it('omits badge slot when badge is not provided', () => {
    const { container } = render(<Panel title="No badge">body</Panel>)
    // The badge wrapper div is conditionally rendered; title should exist, badge should not
    expect(screen.getByText('No badge')).toBeDefined()
    expect(container.querySelectorAll('section').length).toBe(1)
  })

  it('sets aria-label on the section element', () => {
    render(<Panel title="Mission Header">body</Panel>)
    const section = screen.getByRole('region', { name: 'Mission Header' })
    expect(section).toBeDefined()
  })
})
