/**
 * ATLAS — SSE client
 *
 * Wraps the browser EventSource API to consume the live telemetry stream at
 * GET /api/telemetry/stream.  Provides:
 *
 *  - Automatic connection on creation
 *  - Bounded exponential backoff on disconnect
 *  - 409 conflict detection (another operator is already streaming)
 *  - Clean disconnect on destroy()
 *  - Callbacks for every state transition
 *
 * This is a plain JavaScript module with no React dependency so it can be
 * tested in isolation and instantiated once at the application level.
 *
 * Usage:
 *   const client = createSSEClient({ onTick, onConnected, onDisconnected,
 *                                    onConflict, onError });
 *   // later:
 *   client.destroy();
 */

const SSE_URL = '/api/telemetry/stream'

// Reconnect delay schedule (ms).  After the last value we stop retrying.
const RECONNECT_DELAYS = [1_000, 2_000, 5_000, 10_000, 30_000]

export const SSE_STATE = {
  CONNECTING:    'CONNECTING',
  CONNECTED:     'CONNECTED',
  DISCONNECTED:  'DISCONNECTED',
  CONFLICT:      'CONFLICT',   // HTTP 409 — another operator is streaming
  FAILED:        'FAILED',     // exceeded max reconnect attempts
}

/**
 * Create an SSE client that drives the ATLAS telemetry stream.
 *
 * @param {object} callbacks
 * @param {(data: object) => void}  callbacks.onTick          — called for each tick event
 * @param {() => void}              callbacks.onConnected     — stream opened
 * @param {() => void}              callbacks.onDisconnected  — stream closed, will retry
 * @param {() => void}              callbacks.onConflict      — 409: another operator active
 * @param {(msg: string) => void}   callbacks.onError         — fatal error / max retries
 * @returns {{ destroy: () => void }}
 */
export function createSSEClient({ onTick, onConnected, onDisconnected, onConflict, onError }) {
  let es = null
  let reconnectTimer = null
  let attemptIndex = 0
  let destroyed = false

  function connect() {
    if (destroyed) return

    // Before opening SSE we probe for a 409 via a plain fetch because
    // EventSource does not expose HTTP status codes.  The probe HEAD/GET is
    // cheap and resolves the ambiguity between "server down" and "conflict".
    // We use a short timeout so the probe does not block perceptibly.
    probeConflict().then((isConflict) => {
      if (destroyed) return

      if (isConflict) {
        if (onConflict) onConflict()
        return
      }

      openEventSource()
    })
  }

  async function probeConflict() {
    try {
      const ctrl = new AbortController()
      const id = setTimeout(() => ctrl.abort(), 3_000)
      // We need a small request to /api/telemetry/snapshot — if the server is
      // running and the SSE stream is active it returns 503 (no ticks yet) or
      // 200. We cannot detect 409 via EventSource so instead we attempt to
      // open the stream URL ourselves with fetch in streaming mode briefly.
      const res = await fetch('/api/telemetry/stream', {
        signal: ctrl.signal,
        headers: { Accept: 'text/event-stream' },
      })
      clearTimeout(id)
      if (res.status === 409) {
        // Close the body stream immediately
        await res.body?.cancel()
        return true
      }
      // Any other status — not a conflict. Cancel body.
      await res.body?.cancel()
      return false
    } catch {
      // Network error or abort — not a 409
      return false
    }
  }

  function openEventSource() {
    if (destroyed) return
    es = new EventSource(SSE_URL)

    es.onopen = () => {
      attemptIndex = 0
      if (onConnected) onConnected()
    }

    es.addEventListener('tick', (event) => {
      if (destroyed) return
      try {
        const data = JSON.parse(event.data)
        if (onTick) onTick(data)
      } catch (err) {
        console.error('[ATLAS SSE] Failed to parse tick event:', err)
      }
    })

    es.onerror = () => {
      es.close()
      es = null
      if (destroyed) return
      if (onDisconnected) onDisconnected()
      scheduleReconnect()
    }
  }

  function scheduleReconnect() {
    if (destroyed) return
    if (attemptIndex >= RECONNECT_DELAYS.length) {
      if (onError) onError('Connection failed after multiple attempts. Refresh to retry.')
      return
    }
    const delay = RECONNECT_DELAYS[attemptIndex]
    attemptIndex++
    reconnectTimer = setTimeout(connect, delay)
  }

  function destroy() {
    destroyed = true
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (es) {
      es.close()
      es = null
    }
  }

  // Start immediately
  connect()

  return { destroy }
}
