/**
 * ATLAS — SourceTag component tests
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import SourceTag from '../components/SourceTag.jsx'

describe('SourceTag', () => {
  it('renders COMPUTED tag', () => {
    render(<SourceTag tag="COMPUTED" />)
    expect(screen.getByText('COMPUTED')).toBeDefined()
  })

  it('renders MISSION_PARAMS tag', () => {
    render(<SourceTag tag="MISSION_PARAMS" />)
    expect(screen.getByText('MISSION PARAMS')).toBeDefined()
  })

  it('renders AI_EXPLANATION tag', () => {
    render(<SourceTag tag="AI_EXPLANATION" />)
    expect(screen.getByText('AI EXPLANATION')).toBeDefined()
  })

  it('renders OPERATOR tag', () => {
    render(<SourceTag tag="OPERATOR" />)
    expect(screen.getByText('OPERATOR')).toBeDefined()
  })

  it('renders null for unknown tag', () => {
    const { container } = render(<SourceTag tag="UNKNOWN" />)
    expect(container.firstChild).toBeNull()
  })

  it('has aria-label containing the source type', () => {
    render(<SourceTag tag="COMPUTED" />)
    const el = screen.getByLabelText(/Source: COMPUTED/i)
    expect(el).toBeDefined()
  })
})
