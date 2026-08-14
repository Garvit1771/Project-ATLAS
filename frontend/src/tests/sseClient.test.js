/**
 * ATLAS — SSE client tests
 *
 * Tests the createSSEClient wrapper without establishing real network
 * connections.  EventSource and fetch are mocked via vi.stubGlobal.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createSSEClient, SSE_STATE } from '../services/sseClient.js'

// ── EventSource mock ──────────────────────────────────────────────────────────

class MockEventSource {
  constructor(url) {
    this.url = url
    this.listeners = {}
    this.onerror = null
    this.onopen = null
    MockEventSource.instance = this
  }

  addEventListener(type, handler) {
    this.listeners[type] = handler
  }

  close() {
    this.closed = true
  }

  // Test helpers
  simulateOpen() {
    this.onopen?.()
  }

  simulateTick(data) {
    this.listeners.tick?.({ data: JSON.stringify(data) })
  }

  simulateError() {
    this.onerror?.()
  }
}
MockEventSource.instance = null

// ── Helpers ───────────────────────────────────────────────────────────────────

function mockFetchNonConflict() {
  return vi.fn().mockResolvedValue({
    status: 200,
    body: { cancel: vi.fn() },
  })
}

function mockFetch409() {
  return vi.fn().mockResolvedValue({
    status: 409,
    body: { cancel: vi.fn() },
  })
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('SSE_STATE constants', () => {
  it('has CONNECTING, CONNECTED, DISCONNECTED, CONFLICT, FAILED', () => {
    expect(SSE_STATE.CONNECTING).toBeDefined()
    expect(SSE_STATE.CONNECTED).toBeDefined()
    expect(SSE_STATE.DISCONNECTED).toBeDefined()
    expect(SSE_STATE.CONFLICT).toBeDefined()
    expect(SSE_STATE.FAILED).toBeDefined()
  })
})

describe('createSSEClient', () => {
  beforeEach(() => {
    vi.stubGlobal('EventSource', MockEventSource)
    vi.stubGlobal('fetch', mockFetchNonConflict())
    MockEventSource.instance = null
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.clearAllTimers()
  })

  it('calls onConnected after EventSource opens', async () => {
    const onConnected = vi.fn()
    const client = createSSEClient({ onConnected })

    // Wait for the probe fetch to resolve
    await new Promise((r) => setTimeout(r, 10))
    MockEventSource.instance?.simulateOpen()

    expect(onConnected).toHaveBeenCalledOnce()
    client.destroy()
  })

  it('calls onTick with parsed data', async () => {
    const onTick = vi.fn()
    const client = createSSEClient({ onTick })

    await new Promise((r) => setTimeout(r, 10))
    MockEventSource.instance?.simulateOpen()

    const tickData = { tick: 5, timestamp: 'T', telemetry: {}, analytics: {}, risk: {} }
    MockEventSource.instance?.simulateTick(tickData)

    expect(onTick).toHaveBeenCalledWith(tickData)
    client.destroy()
  })

  it('calls onDisconnected after EventSource error', async () => {
    const onDisconnected = vi.fn()
    vi.useFakeTimers()
    const client = createSSEClient({ onDisconnected })

    await vi.runAllTicks()
    await vi.runAllTimersAsync()
    MockEventSource.instance?.simulateError()

    expect(onDisconnected).toHaveBeenCalled()
    client.destroy()
    vi.useRealTimers()
  })

  it('calls onConflict when probe returns 409', async () => {
    vi.stubGlobal('fetch', mockFetch409())
    const onConflict = vi.fn()
    const client = createSSEClient({ onConflict })

    await new Promise((r) => setTimeout(r, 20))

    expect(onConflict).toHaveBeenCalledOnce()
    client.destroy()
  })

  it('destroy() closes EventSource', async () => {
    const client = createSSEClient({})
    await new Promise((r) => setTimeout(r, 10))
    client.destroy()
    // After destroy, the EventSource should be closed
    expect(MockEventSource.instance?.closed).toBe(true)
  })

  it('destroy() prevents reconnection after disconnect', async () => {
    vi.useFakeTimers()
    const onDisconnected = vi.fn()
    const client = createSSEClient({ onDisconnected })
    await vi.runAllTicks()

    client.destroy()
    MockEventSource.instance?.simulateError()
    await vi.runAllTimersAsync()

    // onDisconnected should not have been called because client was destroyed
    expect(onDisconnected).not.toHaveBeenCalled()
    vi.useRealTimers()
  })
})
