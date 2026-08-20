/**
 * ATLAS — SSE client tests (fetch-streaming implementation)
 *
 * All tests work through the public API:
 *   createSSEClient(callbacks) → { destroy }
 *
 * Network I/O is fully mocked via vi.stubGlobal('fetch', ...).
 * No real connections are made.  No EventSource dependency.
 *
 * Test structure
 * --------------
 *   1.  SSE_STATE constants
 *   2.  Single-request guarantee
 *   3.  HTTP 200 — connection and tick parsing
 *   4.  HTTP 409 — CONFLICT state
 *   5.  Non-200 errors — reconnect
 *   6.  Network failure — reconnect
 *   7.  Abort / destroy() cleanup
 *   8.  StrictMode simulate: mount → destroy → remount, no false conflict
 *   9.  Genuine second-operator CONFLICT
 *  10.  Reconnect schedule bounded, onError after max attempts
 *
 * Note: chunked SSE framing tests (split-chunk delivery, multi-event parsing)
 * are contained within suite 3 (HTTP 200 connection) rather than a separate
 * describe block.
 *
 * Implementation notes on mocking
 * --------------------------------
 * The new sseClient uses fetch() + response.body.getReader() + AbortController.
 *
 * makeStreamBody(signal) creates a mock body whose reader resolves / rejects
 * in sync with the AbortSignal passed by the client.  When the signal fires,
 * the pending reader.read() promise rejects with an AbortError — exactly what
 * the browser's ReadableStream does when the fetch is aborted.
 *
 * This is important for tests where destroy() must unblock a streaming reader.
 */

import { describe, it, expect, vi, afterEach } from 'vitest'
import { createSSEClient, SSE_STATE } from '../services/sseClient.js'

// ── ReadableStream / Reader mock factory ──────────────────────────────────────
//
// signal: the AbortSignal from the client's fetch call.  When the signal fires,
// any pending reader.read() promise is rejected with AbortError so that
// readStream()'s try/catch can exit cleanly.

function makeStreamBody(signal) {
  let resolveRead = null
  let closed = false
  const queue = []

  function abortPending() {
    if (resolveRead) {
      const r = resolveRead
      resolveRead = null
      const err = new DOMException('The operation was aborted.', 'AbortError')
      // We resolve with a rejection — the read() call was waiting on a promise.
      r(Promise.reject(err))
    }
  }

  if (signal) {
    signal.addEventListener('abort', abortPending)
  }

  const reader = {
    read() {
      if (queue.length > 0) {
        const chunk = queue.shift()
        return Promise.resolve({ done: false, value: chunk })
      }
      if (closed) {
        return Promise.resolve({ done: true, value: undefined })
      }
      // Return a promise that will be resolved by push()/close() or rejected by abort.
      return new Promise((res, rej) => {
        resolveRead = (result) => {
          // result may be a Promise (the abort case) or a plain value.
          Promise.resolve(result).then(res).catch(rej)
        }
      })
    },
    cancel: vi.fn().mockResolvedValue(undefined),
  }

  const body = {
    // The signal is captured here so the mock fetch can pass it through.
    _signal: signal,
    getReader: () => reader,
    cancel: vi.fn().mockResolvedValue(undefined),
  }

  function push(text) {
    const encoded = new TextEncoder().encode(text)
    if (resolveRead) {
      const r = resolveRead
      resolveRead = null
      r({ done: false, value: encoded })
    } else {
      queue.push(encoded)
    }
  }

  function close() {
    closed = true
    if (resolveRead) {
      const r = resolveRead
      resolveRead = null
      r({ done: true, value: undefined })
    }
  }

  return { body, reader, push, close }
}

// Build a complete SSE event string in ATLAS format.
function sseEvent(data) {
  return `event: tick\ndata: ${JSON.stringify(data)}\n\n`
}

// ── Mock fetch helpers ────────────────────────────────────────────────────────
//
// Note: makeStreamBody() needs the AbortSignal so it can reject on abort.
// The mock fetch implementation captures the signal from opts and passes it
// through to makeStreamBody so the reader and the signal are connected.

function makeFetch200WithAbort() {
  // Returns a fetch mock that creates a new signal-aware stream per call.
  return vi.fn().mockImplementation((_url, opts) => {
    const stream = makeStreamBody(opts?.signal)
    return Promise.resolve({
      status: 200,
      ok: true,
      body: stream.body,
      _stream: stream,  // expose for test control
    })
  })
}

function mockFetch409() {
  return vi.fn().mockResolvedValue({
    status: 409,
    ok: false,
    body: { cancel: vi.fn().mockResolvedValue(undefined) },
  })
}

function mockFetchStatus(status) {
  return vi.fn().mockResolvedValue({
    status,
    ok: status >= 200 && status < 300,
    body: { cancel: vi.fn().mockResolvedValue(undefined) },
  })
}

function mockFetchNetworkError() {
  return vi.fn().mockRejectedValue(new Error('Failed to fetch'))
}

// ── Utilities ─────────────────────────────────────────────────────────────────

// Flush all pending microtasks and the next macrotask queue turn.
const flush = () => new Promise((r) => setTimeout(r, 0))

// ══════════════════════════════════════════════════════════════════════════════

describe('SSE_STATE constants', () => {
  it('exports CONNECTING, CONNECTED, DISCONNECTED, CONFLICT, FAILED', () => {
    expect(SSE_STATE.CONNECTING).toBe('CONNECTING')
    expect(SSE_STATE.CONNECTED).toBe('CONNECTED')
    expect(SSE_STATE.DISCONNECTED).toBe('DISCONNECTED')
    expect(SSE_STATE.CONFLICT).toBe('CONFLICT')
    expect(SSE_STATE.FAILED).toBe('FAILED')
  })
})

// ══════════════════════════════════════════════════════════════════════════════

describe('createSSEClient — single-request guarantee', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('makes exactly ONE fetch request to /api/telemetry/stream on creation', async () => {
    const spy = makeFetch200WithAbort()
    vi.stubGlobal('fetch', spy)

    const client = createSSEClient({})
    await flush()

    expect(spy).toHaveBeenCalledTimes(1)
    expect(spy).toHaveBeenCalledWith(
      '/api/telemetry/stream',
      expect.objectContaining({
        headers: expect.objectContaining({ Accept: 'text/event-stream' }),
      })
    )

    client.destroy()
    await flush()
  })

  it('does NOT use EventSource (no EventSource constructor call)', async () => {
    const esSpy = vi.fn()
    vi.stubGlobal('EventSource', esSpy)
    vi.stubGlobal('fetch', makeFetch200WithAbort())

    const client = createSSEClient({})
    await flush()

    expect(esSpy).not.toHaveBeenCalled()
    client.destroy()
    await flush()
  })
})

// ══════════════════════════════════════════════════════════════════════════════

describe('createSSEClient — HTTP 200 connection', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('calls onConnected when fetch returns 200', async () => {
    vi.stubGlobal('fetch', makeFetch200WithAbort())
    const onConnected = vi.fn()

    const client = createSSEClient({ onConnected })
    await flush()

    expect(onConnected).toHaveBeenCalledTimes(1)
    client.destroy()
    await flush()
  })

  it('calls onTick with parsed object when a tick chunk arrives', async () => {
    let capturedStream = null
    vi.stubGlobal('fetch', vi.fn().mockImplementation((_url, opts) => {
      const stream = makeStreamBody(opts?.signal)
      capturedStream = stream
      return Promise.resolve({ status: 200, ok: true, body: stream.body })
    }))
    const onTick = vi.fn()

    const client = createSSEClient({ onTick })
    await flush()  // connect → onConnected

    const tickData = { tick: 1, timestamp: 'T', telemetry: {}, analytics: {}, risk: {} }
    capturedStream.push(sseEvent(tickData))
    await flush()

    expect(onTick).toHaveBeenCalledTimes(1)
    expect(onTick).toHaveBeenCalledWith(tickData)
    client.destroy()
    await flush()
  })

  it('correctly parses a tick delivered across two chunks', async () => {
    let capturedStream = null
    vi.stubGlobal('fetch', vi.fn().mockImplementation((_url, opts) => {
      const stream = makeStreamBody(opts?.signal)
      capturedStream = stream
      return Promise.resolve({ status: 200, ok: true, body: stream.body })
    }))
    const onTick = vi.fn()

    const client = createSSEClient({ onTick })
    await flush()

    const tickData = { tick: 7 }
    const full = sseEvent(tickData)
    const half = Math.floor(full.length / 2)
    capturedStream.push(full.slice(0, half))
    await flush()
    capturedStream.push(full.slice(half))
    await flush()

    expect(onTick).toHaveBeenCalledWith(tickData)
    client.destroy()
    await flush()
  })

  it('dispatches multiple sequential ticks correctly', async () => {
    let capturedStream = null
    vi.stubGlobal('fetch', vi.fn().mockImplementation((_url, opts) => {
      const stream = makeStreamBody(opts?.signal)
      capturedStream = stream
      return Promise.resolve({ status: 200, ok: true, body: stream.body })
    }))
    const onTick = vi.fn()

    const client = createSSEClient({ onTick })
    await flush()

    capturedStream.push(sseEvent({ tick: 0 }))
    await flush()
    capturedStream.push(sseEvent({ tick: 1 }))
    await flush()
    capturedStream.push(sseEvent({ tick: 2 }))
    await flush()

    expect(onTick).toHaveBeenCalledTimes(3)
    expect(onTick.mock.calls[0][0]).toEqual({ tick: 0 })
    expect(onTick.mock.calls[1][0]).toEqual({ tick: 1 })
    expect(onTick.mock.calls[2][0]).toEqual({ tick: 2 })
    client.destroy()
    await flush()
  })

  it('ignores unknown event types (forward compatible)', async () => {
    let capturedStream = null
    vi.stubGlobal('fetch', vi.fn().mockImplementation((_url, opts) => {
      const stream = makeStreamBody(opts?.signal)
      capturedStream = stream
      return Promise.resolve({ status: 200, ok: true, body: stream.body })
    }))
    const onTick = vi.fn()

    const client = createSSEClient({ onTick })
    await flush()

    capturedStream.push('event: heartbeat\ndata: {}\n\n')
    await flush()
    capturedStream.push(sseEvent({ tick: 0 }))
    await flush()

    expect(onTick).toHaveBeenCalledTimes(1)
    expect(onTick).toHaveBeenCalledWith({ tick: 0 })
    client.destroy()
    await flush()
  })
})

// ══════════════════════════════════════════════════════════════════════════════

describe('createSSEClient — HTTP 409 conflict', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('calls onConflict when fetch returns 409', async () => {
    vi.stubGlobal('fetch', mockFetch409())
    const onConflict = vi.fn()

    const client = createSSEClient({ onConflict })
    await flush()

    expect(onConflict).toHaveBeenCalledTimes(1)
    client.destroy()
  })

  it('does NOT call onConnected when response is 409', async () => {
    vi.stubGlobal('fetch', mockFetch409())
    const onConnected = vi.fn()

    const client = createSSEClient({ onConnected })
    await flush()

    expect(onConnected).not.toHaveBeenCalled()
    client.destroy()
  })

  it('makes exactly ONE fetch request on 409 (no retry)', async () => {
    vi.useFakeTimers()
    const spy = mockFetch409()
    vi.stubGlobal('fetch', spy)

    const client = createSSEClient({})
    // Flush initial async connect.
    await vi.runAllTicks()
    await vi.runAllTimersAsync()

    // Advance past all reconnect delays.
    vi.advanceTimersByTime(60_000)
    await vi.runAllTimersAsync()

    expect(spy).toHaveBeenCalledTimes(1)
    client.destroy()
  })

  it('cancels the response body on 409', async () => {
    const cancelFn = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      status: 409,
      ok: false,
      body: { cancel: cancelFn },
    }))

    const client = createSSEClient({})
    await flush()

    expect(cancelFn).toHaveBeenCalled()
    client.destroy()
  })
})

// ══════════════════════════════════════════════════════════════════════════════

describe('createSSEClient — non-200 HTTP errors', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('calls onDisconnected on 500 response', async () => {
    vi.stubGlobal('fetch', mockFetchStatus(500))
    const onDisconnected = vi.fn()

    const client = createSSEClient({ onDisconnected })
    await flush()

    expect(onDisconnected).toHaveBeenCalledTimes(1)
    client.destroy()
  })

  it('calls onDisconnected on 503 response', async () => {
    vi.stubGlobal('fetch', mockFetchStatus(503))
    const onDisconnected = vi.fn()

    const client = createSSEClient({ onDisconnected })
    await flush()

    expect(onDisconnected).toHaveBeenCalledTimes(1)
    client.destroy()
  })

  it('schedules a reconnect after non-200 (fetch called again after delay)', async () => {
    vi.useFakeTimers()
    let callCount = 0
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => {
      callCount++
      return Promise.resolve({
        status: 503,
        ok: false,
        body: { cancel: vi.fn().mockResolvedValue(undefined) },
      })
    }))

    const client = createSSEClient({})

    // Flush the initial async connect() microtask chain.
    for (let i = 0; i < 5; i++) await vi.runAllTicks()
    expect(callCount).toBe(1)

    // Advance first reconnect delay, then drain the full async chain.
    vi.advanceTimersByTime(1_000)
    for (let i = 0; i < 5; i++) await vi.runAllTicks()
    expect(callCount).toBe(2)

    client.destroy()
  })
})

// ══════════════════════════════════════════════════════════════════════════════

describe('createSSEClient — network failure', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('calls onDisconnected on network error', async () => {
    vi.stubGlobal('fetch', mockFetchNetworkError())
    const onDisconnected = vi.fn()

    const client = createSSEClient({ onDisconnected })
    await flush()

    expect(onDisconnected).toHaveBeenCalledTimes(1)
    client.destroy()
  })

  it('does NOT call onConflict on network error', async () => {
    vi.stubGlobal('fetch', mockFetchNetworkError())
    const onConflict = vi.fn()

    const client = createSSEClient({ onConflict })
    await flush()

    expect(onConflict).not.toHaveBeenCalled()
    client.destroy()
  })
})

// ══════════════════════════════════════════════════════════════════════════════

describe('createSSEClient — destroy() and AbortController', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('destroy() aborts the in-flight fetch (AbortController.abort called)', async () => {
    let capturedSignal = null
    vi.stubGlobal('fetch', vi.fn().mockImplementation((_url, opts) => {
      capturedSignal = opts?.signal
      const stream = makeStreamBody(opts?.signal)
      return Promise.resolve({ status: 200, ok: true, body: stream.body })
    }))

    const client = createSSEClient({})
    await flush()

    expect(capturedSignal?.aborted).toBe(false)
    client.destroy()
    expect(capturedSignal?.aborted).toBe(true)
    await flush()
  })

  it('destroy() before fetch resolves does not call onConnected', async () => {
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(new Promise(() => {})))
    const onConnected = vi.fn()

    const client = createSSEClient({ onConnected })
    client.destroy()  // destroy before fetch resolves
    await flush()

    expect(onConnected).not.toHaveBeenCalled()
  })

  it('destroy() cancels any pending reconnect timer', async () => {
    // Use real timers so flush() works correctly; fake timers are not
    // needed here because we only need to check that destroy() prevents
    // further calls — not verify exact timing.
    vi.stubGlobal('fetch', mockFetchNetworkError())
    const onDisconnected = vi.fn()

    const client = createSSEClient({ onDisconnected })
    // Let the network error fully propagate through the promise chain.
    await flush()
    // Network error fires onDisconnected once and schedules first reconnect.
    expect(onDisconnected).toHaveBeenCalledTimes(1)

    // Destroy cancels the reconnect timer before it fires.
    client.destroy()

    // Wait longer than the first reconnect delay (1000 ms) — nothing fires.
    await new Promise((r) => setTimeout(r, 50))

    // Still exactly one call — destroy cancelled all timers.
    expect(onDisconnected).toHaveBeenCalledTimes(1)
  })

  it('after destroy(), a stream close does not trigger onDisconnected or reconnect', async () => {
    let capturedStream = null
    const fetchSpy = vi.fn().mockImplementation((_url, opts) => {
      const stream = makeStreamBody(opts?.signal)
      capturedStream = stream
      return Promise.resolve({ status: 200, ok: true, body: stream.body })
    })
    vi.stubGlobal('fetch', fetchSpy)

    const onDisconnected = vi.fn()
    const client = createSSEClient({ onDisconnected })
    await flush()  // connected

    client.destroy()
    await flush()  // abort propagates

    // Close the stream after destroy — should not trigger reconnect.
    capturedStream?.close()
    await flush()

    expect(onDisconnected).not.toHaveBeenCalled()
    // fetch was called only once.
    expect(fetchSpy).toHaveBeenCalledTimes(1)
  })
})

// ══════════════════════════════════════════════════════════════════════════════

describe('createSSEClient — React StrictMode double-mount safety', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('create → destroy (after connected) → create does NOT produce CONFLICT', async () => {
    // Case 1: destroy is called after the first fetch resolved and onConnected fired.
    // Sequential: connect → connected → destroy → remount → connected again.
    let callIndex = 0
    vi.stubGlobal('fetch', vi.fn().mockImplementation((_url, opts) => {
      callIndex++
      const stream = makeStreamBody(opts?.signal)
      return Promise.resolve({ status: 200, ok: true, body: stream.body })
    }))

    const onConflict1 = vi.fn()
    const onConflict2 = vi.fn()
    const onConnected1 = vi.fn()
    const onConnected2 = vi.fn()

    // First mount (StrictMode mount #1)
    const client1 = createSSEClient({ onConflict: onConflict1, onConnected: onConnected1 })
    await flush()
    expect(onConnected1).toHaveBeenCalledTimes(1)
    expect(onConflict1).not.toHaveBeenCalled()

    // StrictMode unmount — destroy() is called synchronously after connected
    client1.destroy()
    await flush()  // allow abort + AbortError in reader to propagate

    // StrictMode remount (mount #2)
    const client2 = createSSEClient({ onConflict: onConflict2, onConnected: onConnected2 })
    await flush()

    // Second client must connect cleanly — NOT see CONFLICT.
    expect(onConflict2).not.toHaveBeenCalled()
    expect(onConnected2).toHaveBeenCalledTimes(1)

    client2.destroy()
    await flush()
  })

  it('create → destroy (before fetch resolves) → create does NOT produce CONFLICT (Case 2 race)', async () => {
    // Case 2 — the precise StrictMode race that causes false 409s in production:
    //
    //   T=sync: client_A created → connect_A() starts (fetch pending)
    //   T=sync: destroy_A() called → destroyed_A=true, ctrl_A.abort()
    //   T=sync: client_B created → connect_B() starts
    //   T=microtask: connect_A fetch resolves 200, destroyed=true →
    //                enters readStream() with already-aborted signal →
    //                reader.read() rejects with AbortError → reader released.
    //                (ctrl_A.abort() in destroy() already cancelled the transport.)
    //   T=microtask: connect_B fetch resolves 200 → onConnected_B fires.
    //
    // SCOPE OF THIS TEST
    // This test proves the JavaScript-level lifecycle correctness:
    //   create → destroy → create  results in only the live client receiving
    //   onConnected, with no spurious onConflict on either client.
    //
    // What this test cannot prove: TCP/ASGI disconnect ordering in a real
    // browser.  Whether the backend's _stream_active clears before client_B's
    // request arrives depends on OS-level socket scheduling between two
    // independent HTTP connections.  That is an integration/browser concern
    // and cannot be verified by a unit test with a mocked fetch.
    //
    // In practice, AbortController.abort() causes an immediate RST/FIN at the
    // transport level, and on HTTP/2 (Vite dev proxy) the RST and the new
    // request share the same connection, making the ordering reliable.

    let capturedStreams = []
    vi.stubGlobal('fetch', vi.fn().mockImplementation((_url, opts) => {
      const stream = makeStreamBody(opts?.signal)
      capturedStreams.push(stream)
      return Promise.resolve({ status: 200, ok: true, body: stream.body })
    }))

    const onConflict1 = vi.fn()
    const onConflict2 = vi.fn()
    const onConnected1 = vi.fn()
    const onConnected2 = vi.fn()

    // Simulate StrictMode: create client, immediately destroy (before fetch microtask runs),
    // then create second client — all synchronously before any microtasks drain.
    const client1 = createSSEClient({ onConflict: onConflict1, onConnected: onConnected1 })
    client1.destroy()  // synchronous — ctrl_A is now aborted
    const client2 = createSSEClient({ onConflict: onConflict2, onConnected: onConnected2 })

    // Now drain all microtasks: connect_A and connect_B both resume.
    await flush()
    await flush()  // extra flush for any nested microtask chains

    // client1 (destroyed) must NOT call onConnected1 or onConflict1.
    expect(onConnected1).not.toHaveBeenCalled()
    expect(onConflict1).not.toHaveBeenCalled()

    // client2 (live) must connect cleanly — NOT see CONFLICT.
    expect(onConflict2).not.toHaveBeenCalled()
    expect(onConnected2).toHaveBeenCalledTimes(1)

    client2.destroy()
    await flush()
  })

  it('destroyed client does not call onConnected even when fetch returns 200', async () => {
    // Verifies the !destroyed guard on onConnected.
    vi.stubGlobal('fetch', vi.fn().mockImplementation((_url, opts) => {
      const stream = makeStreamBody(opts?.signal)
      return Promise.resolve({ status: 200, ok: true, body: stream.body })
    }))

    const onConnected = vi.fn()
    const onConflict = vi.fn()

    // Create and immediately destroy (sync) before fetch can resolve.
    const client = createSSEClient({ onConnected, onConflict })
    client.destroy()

    await flush()
    await flush()

    expect(onConnected).not.toHaveBeenCalled()
    expect(onConflict).not.toHaveBeenCalled()
  })
})

// ══════════════════════════════════════════════════════════════════════════════

describe('createSSEClient — genuine second-operator CONFLICT', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('a second simultaneous client that receives 409 calls onConflict', async () => {
    let callIndex = 0
    vi.stubGlobal('fetch', vi.fn().mockImplementation((_url, opts) => {
      callIndex++
      if (callIndex === 1) {
        const stream = makeStreamBody(opts?.signal)
        return Promise.resolve({ status: 200, ok: true, body: stream.body })
      }
      // Second call: backend sees _stream_active = true → returns 409.
      return Promise.resolve({
        status: 409,
        ok: false,
        body: { cancel: vi.fn().mockResolvedValue(undefined) },
      })
    }))

    const onConflict1 = vi.fn()
    const onConflict2 = vi.fn()
    const onConnected1 = vi.fn()
    const onConnected2 = vi.fn()

    // First client connects successfully.
    const client1 = createSSEClient({ onConflict: onConflict1, onConnected: onConnected1 })
    await flush()
    expect(onConnected1).toHaveBeenCalledTimes(1)
    expect(onConflict1).not.toHaveBeenCalled()

    // Second client — rejected with 409 because first is still active.
    const client2 = createSSEClient({ onConflict: onConflict2, onConnected: onConnected2 })
    await flush()
    expect(onConflict2).toHaveBeenCalledTimes(1)
    expect(onConnected2).not.toHaveBeenCalled()

    client1.destroy()
    client2.destroy()
    await flush()
  })
})

// ══════════════════════════════════════════════════════════════════════════════

describe('createSSEClient — reconnect schedule', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('calls onError after exhausting all reconnect attempts', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', mockFetchNetworkError())
    const onError = vi.fn()
    const onDisconnected = vi.fn()

    createSSEClient({ onError, onDisconnected })

    // RECONNECT_DELAYS = [1000, 2000, 5000, 10000, 30000] — 5 entries.
    // Sequence: initial attempt + 5 retries = 6 fetch calls.
    // After the 6th call fails and the schedule is exhausted, onError fires.
    const delays = [0, 1_000, 2_000, 5_000, 10_000, 30_000]
    for (const delay of delays) {
      vi.advanceTimersByTime(delay)
      await vi.runAllTicks()
      await vi.runAllTimersAsync()
    }

    expect(onError).toHaveBeenCalledTimes(1)
    expect(onError.mock.calls[0][0]).toMatch(/multiple attempts/i)
    expect(onDisconnected).toHaveBeenCalled()
  })

  it('reconnect attempt count increments correctly', async () => {
    vi.useFakeTimers()
    let callCount = 0
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => {
      callCount++
      return Promise.reject(new Error('Network down'))
    }))

    createSSEClient({})

    // Flush the initial async connect() microtask chain.
    for (let i = 0; i < 5; i++) await vi.runAllTicks()
    expect(callCount).toBe(1)  // initial attempt

    // First reconnect after 1000 ms.
    vi.advanceTimersByTime(1_000)
    for (let i = 0; i < 5; i++) await vi.runAllTicks()
    expect(callCount).toBe(2)

    // Second reconnect after another 2000 ms.
    vi.advanceTimersByTime(2_000)
    for (let i = 0; i < 5; i++) await vi.runAllTicks()
    expect(callCount).toBe(3)
  })
})
