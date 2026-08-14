/**
 * ATLAS — Connection status banner
 *
 * Displayed as a full-width banner below the mission header when the
 * SSE connection is in a non-connected state (reconnecting, conflict, failed).
 *
 * When connected, this component renders nothing — it does not take space.
 */

import React from 'react'
import { useAtlas } from '../state/AtlasContext.jsx'

export default function ConnectionBanner() {
  const { state } = useAtlas()
  const { sseState, sseError } = state

  if (sseState === 'CONNECTED') return null

  const configs = {
    CONNECTING: {
      bg: 'bg-slate-800 border-slate-700',
      text: 'text-slate-400',
      message: 'Establishing telemetry stream connection…',
      showSpinner: true,
    },
    DISCONNECTED: {
      bg: 'bg-yellow-950 border-yellow-800',
      text: 'text-yellow-300',
      message: 'Connection lost. Attempting to reconnect…',
      showSpinner: true,
    },
    CONFLICT: {
      bg: 'bg-orange-950 border-orange-800',
      text: 'text-orange-300',
      message: 'Another operator session is already streaming. Close other ATLAS sessions to connect.',
      showSpinner: false,
    },
    FAILED: {
      bg: 'bg-red-950 border-red-800',
      text: 'text-red-300',
      message: sseError || 'Connection failed. Refresh the page to retry.',
      showSpinner: false,
    },
  }

  const config = configs[sseState] ?? configs.CONNECTING

  return (
    <div
      className={`flex items-center gap-3 px-5 py-2.5 border-b text-xs ${config.bg} ${config.text}`}
      role="status"
      aria-live="polite"
    >
      {config.showSpinner && (
        <span
          className="inline-block w-3 h-3 border border-current border-t-transparent rounded-full animate-spin shrink-0"
          aria-hidden="true"
        />
      )}
      <span>{config.message}</span>
    </div>
  )
}
