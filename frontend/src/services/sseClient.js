/**
 * ATLAS — SSE client (fetch-streaming implementation)
 *
 * Consumes the live telemetry stream at GET /api/telemetry/stream using the
 * Fetch API rather than the browser's native EventSource.
 *
 * WHY fetch() INSTEAD OF EventSource
 * ------------------------------------
 * EventSource does not expose HTTP status codes to JavaScript.  Its onerror
 * fires identically for HTTP 200 (transient network drop), HTTP 409 (genuine
 * conflict), and HTTP 500 (server error).  ATLAS specifically needs to
 * distinguish HTTP 409 (another operator is streaming) from every other error
 * so the ConnectionBanner can show the correct message.
 *
 * With fetch(), response.status is available before any stream body is read,
 * which means:
 *   - A single request reaches /api/telemetry/stream.
 *   - 409 is detected from response.status, not from a separate probe.
 *   - No second connection is ever opened to the streaming endpoint.
 *   - AbortController provides synchronous, deterministic cancellation that
 *     propagates an immediate TCP disconnect to the backend, allowing
 *     _stream_active to clear before React remounts (StrictMode-safe).
 *
 * PUBLIC API (unchanged from EventSource implementation)
 * -------------------------------------------------------
 *   const client = createSSEClient({ onTick, onConnected, onDisconnected,
 *                                    onConflict, onError })
 *   client.destroy()
 *
 * SSE FRAMING
 * -----------
 * ATLAS uses standard SSE framing.  The backend emits:
 *
 *   event: tick\n
 *   data: {"tick":0, "timestamp":"...", "telemetry":{...}, ...}\n
 *   \n
 *
 * The parser accumulates decoded text chunks, splits on newlines, and
 * dispatches named events when a blank line terminates an event block.
 * Only "tick" events are forwarded to onTick; unknown event types are
 * silently ignored (forward-compatible).
 */

const SSE_URL = '/api/telemetry/stream'

// Reconnect delay schedule (ms).  After the last value we stop retrying.
const RECONNECT_DELAYS = [1_000, 2_000, 5_000, 10_000, 30_000]

export const SSE_STATE = {
  CONNECTING:   'CONNECTING',
  CONNECTED:    'CONNECTED',
  DISCONNECTED: 'DISCONNECTED',
  CONFLICT:     'CONFLICT',  // HTTP 409 — another operator is streaming
  FAILED:       'FAILED',    // exceeded max reconnect attempts
}

/**
 * Create a fetch-streaming SSE client for the ATLAS telemetry endpoint.
 *
 * @param {object} callbacks
 * @param {(data: object) => void}  callbacks.onTick          — per-tick event
 * @param {() => void}              callbacks.onConnected     — stream opened (HTTP 200)
 * @param {() => void}              callbacks.onDisconnected  — stream closed, will retry
 * @param {() => void}              callbacks.onConflict      — HTTP 409: another operator
 * @param {(msg: string) => void}   callbacks.onError         — fatal / max retries exceeded
 * @returns {{ destroy: () => void }}
 */
export function createSSEClient({
  onTick,
  onConnected,
  onDisconnected,
  onConflict,
  onError,
} = {}) {
  let destroyed = false
  let reconnectTimer = null
  let attemptIndex = 0

  // The AbortController for the currently active fetch.  Replaced on every
  // connection attempt; abort() on the previous controller has no effect on
  // the new one.
  let currentAbort = null

  // ── Connection ──────────────────────────────────────────────────────────────

  async function connect() {
    if (destroyed) return

    // Fresh AbortController for this attempt.
    const ctrl = new AbortController()
    currentAbort = ctrl

    let response
    try {
      response = await fetch(SSE_URL, {
        headers: { Accept: 'text/event-stream', 'Cache-Control': 'no-cache' },
        signal: ctrl.signal,
      })
    } catch (err) {
      if (destroyed) return
      // AbortError means destroy() was called — not a real failure.
      if (err.name === 'AbortError') return
      // Network failure (server down, DNS, etc.) — schedule reconnect.
      if (onDisconnected) onDisconnected()
      scheduleReconnect()
      return
    }

    // ── HTTP status handling ────────────────────────────────────────────────
    // NOTE: do NOT add an early `if (destroyed) return` here.
    //
    // If destroy() was called before this fetch resolved, the sequence is:
    //
    //   destroy() called synchronously
    //     → destroyed = true
    //     → ctrl.abort()       ← THIS is what aborts the fetch transport.
    //                            AbortController.abort() signals the browser
    //                            to cancel the underlying HTTP request at the
    //                            network level (RST / stream cancellation).
    //
    // We still enter readStream() so that the already-aborted ctrl.signal
    // causes reader.read() to reject immediately with AbortError.  This is
    // intentional defensive cleanup: it ensures the response reader is
    // properly released and that the stale client does not attempt to process
    // any response body.  It does NOT replace ctrl.abort() as the transport-
    // close mechanism — ctrl.abort() already closed the transport when
    // destroy() was called.

    if (response.status === 409) {
      // Genuine conflict — another operator is streaming.
      // Do NOT schedule a reconnect; the CONFLICT state is terminal until the
      // operator explicitly retries or the other session closes.
      response.body?.cancel()
      if (onConflict) onConflict()
      return
    }

    if (response.status !== 200) {
      // Any other non-200 (500, 503, etc.) — treat as transient, reconnect.
      response.body?.cancel()
      if (onDisconnected) onDisconnected()
      scheduleReconnect()
      return
    }

    // ── HTTP 200: stream is open ────────────────────────────────────────────

    // Reset backoff — successful connection.
    attemptIndex = 0

    // Only fire onConnected if the client is still live.  In the StrictMode
    // race (Case 2) destroy() may have been called before fetch() resolved,
    // meaning this is a stale client that should not announce itself as
    // connected.  We still enter readStream() with the already-aborted signal
    // so that reader.read() rejects immediately with AbortError, releasing
    // the reader and ensuring no response body is consumed.  The transport
    // was already cancelled by ctrl.abort() inside destroy().
    if (!destroyed && onConnected) onConnected()

    // Read the response body as a stream of text.
    await readStream(response.body, ctrl.signal)
  }

  // ── SSE stream reader ───────────────────────────────────────────────────────
  //
  // Accumulates decoded chunks, splits on line boundaries, and dispatches
  // complete SSE events when a blank line terminates an event block.
  //
  // SSE event fields tracked:
  //   event — event type name (default "message"; ATLAS uses "tick")
  //   data  — event payload (one or more data: lines concatenated with \n)
  //
  // A blank line commits the current event.
  //
  // Spec reference: https://html.spec.whatwg.org/multipage/server-sent-events.html

  async function readStream(body, signal) {
    const reader = body.getReader()
    const decoder = new TextDecoder()
    // Remainder from a previous chunk that didn't end on a newline.
    let remainder = ''
    // Current event accumulation.
    let eventType = 'message'
    let dataLines = []

    function dispatchEvent() {
      if (dataLines.length === 0) return
      const payload = dataLines.join('\n')
      if (eventType === 'tick' && onTick && !destroyed) {
        try {
          onTick(JSON.parse(payload))
        } catch (err) {
          console.error('[ATLAS SSE] Failed to parse tick payload:', err)
        }
      }
      // Reset for next event.
      eventType = 'message'
      dataLines = []
    }

    try {
      while (true) {
        const { done, value } = await reader.read()

        if (done || destroyed) break

        // Decode and prepend any unfinished line from previous chunk.
        const text = remainder + decoder.decode(value, { stream: true })
        const lines = text.split('\n')

        // The last element may be an incomplete line — carry it forward.
        remainder = lines.pop()

        for (const line of lines) {
          if (line === '') {
            // Blank line → end of event block.
            dispatchEvent()
          } else if (line.startsWith('event:')) {
            eventType = line.slice(6).trim()
          } else if (line.startsWith('data:')) {
            dataLines.push(line.slice(5).trim())
          }
          // Ignore id:, retry:, and comment lines (:).
        }
      }
    } catch (err) {
      if (err.name === 'AbortError') return  // destroy() was called
      // Unexpected read error — fall through to reconnect logic below.
    } finally {
      try { reader.cancel() } catch { /* ignore */ }
    }

    // Stream ended cleanly or errored.  If destroy() was called we are done.
    if (destroyed) return

    if (onDisconnected) onDisconnected()
    scheduleReconnect()
  }

  // ── Reconnect ───────────────────────────────────────────────────────────────

  function scheduleReconnect() {
    if (destroyed) return
    if (attemptIndex >= RECONNECT_DELAYS.length) {
      if (onError) onError(
        'Connection failed after multiple attempts. Refresh to retry.'
      )
      return
    }
    const delay = RECONNECT_DELAYS[attemptIndex]
    attemptIndex++
    reconnectTimer = setTimeout(connect, delay)
  }

  // ── Destroy ─────────────────────────────────────────────────────────────────
  //
  // Synchronously marks the client as destroyed and aborts any in-flight fetch.
  // AbortController.abort() causes the backend to receive an ASGI http.disconnect
  // immediately (no tick-interval wait), clearing _stream_active before React
  // can remount in StrictMode.

  function destroy() {
    destroyed = true
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (currentAbort !== null) {
      currentAbort.abort()
      currentAbort = null
    }
  }

  // Start immediately.
  connect()

  return { destroy }
}
