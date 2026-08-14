/**
 * ATLAS — Application state management
 *
 * Context + useReducer pattern.  Single source of truth for all live
 * telemetry, analytics, risk, decision, AI, and connection state.
 *
 * Design rules:
 *   - State is immutable — each action returns a new state object.
 *   - SSE ticks write latestTick, latestAnalytics, latestRisk, and
 *     append to telemetryHistory (bounded to MAX_HISTORY entries).
 *   - REST fetch results (decision, whatIf, explanation, copilot) are
 *     stored separately because they are triggered on demand.
 *   - loadingStates and errors are per-feature so each panel can show
 *     its own loading/error state independently.
 *   - The context is consumed by all panels — no prop drilling.
 */

import React, {
  createContext,
  useContext,
  useReducer,
  useEffect,
  useRef,
  useCallback,
} from 'react'
import { createSSEClient, SSE_STATE } from '../services/sseClient.js'
import {
  fetchDecisionOptions,
  fetchWhatIf,
  fetchAnomalyExplanation,
  askCopilot,
} from '../services/apiClient.js'

// Maximum number of telemetry ticks to keep in client-side history.
// Matches the backend's rolling buffer (300 ticks = 5 minutes at 1 Hz).
export const MAX_HISTORY = 300

// ── Action types ──────────────────────────────────────────────────────────────

const A = {
  SSE_CONNECTING:           'SSE_CONNECTING',
  SSE_CONNECTED:            'SSE_CONNECTED',
  SSE_DISCONNECTED:         'SSE_DISCONNECTED',
  SSE_CONFLICT:             'SSE_CONFLICT',
  SSE_FAILED:               'SSE_FAILED',
  TICK_RECEIVED:            'TICK_RECEIVED',
  // Decision
  DECISION_LOADING:         'DECISION_LOADING',
  DECISION_LOADED:          'DECISION_LOADED',
  DECISION_ERROR:           'DECISION_ERROR',
  // What-if
  WHATIF_LOADING:           'WHATIF_LOADING',
  WHATIF_LOADED:            'WHATIF_LOADED',
  WHATIF_ERROR:             'WHATIF_ERROR',
  WHATIF_CLEAR:             'WHATIF_CLEAR',
  // AI explanation
  EXPLAIN_LOADING:          'EXPLAIN_LOADING',
  EXPLAIN_LOADED:           'EXPLAIN_LOADED',
  EXPLAIN_ERROR:            'EXPLAIN_ERROR',
  // Copilot
  COPILOT_LOADING:          'COPILOT_LOADING',
  COPILOT_RESPONSE:         'COPILOT_RESPONSE',
  COPILOT_ERROR:            'COPILOT_ERROR',
}

// ── Initial state ─────────────────────────────────────────────────────────────

const initialState = {
  sseState: SSE_STATE.CONNECTING,
  sseError: null,

  // Latest processed tick (from SSE)
  latestTick: null,         // { tick, timestamp, telemetry, analytics, risk }
  latestAnalytics: null,    // analytics sub-object
  latestRisk: null,         // risk sub-object

  // Rolling history for charts (array of telemetry objects, max MAX_HISTORY)
  telemetryHistory: [],

  // Decision panel
  decisionResult: null,     // { tick, options, current_risk_score, ... }
  decisionLoading: false,
  decisionError: null,

  // What-if
  whatIfResult: null,       // { what_if: {…}, ai_narrative: string }
  whatIfLoading: false,
  whatIfError: null,
  whatIfOptionId: null,     // which option was last evaluated

  // AI anomaly explanation
  explanation: null,        // { explanation: string, subsystem: string }
  explanationLoading: false,
  explanationError: null,

  // Copilot — CopilotPanel manages its own local message history;
  // context only tracks loading/error state.
  copilotLoading: false,
  copilotError: null,
}

// ── Reducer ───────────────────────────────────────────────────────────────────

function reducer(state, action) {
  switch (action.type) {

    case A.SSE_CONNECTING:
      return { ...state, sseState: SSE_STATE.CONNECTING, sseError: null }

    case A.SSE_CONNECTED:
      return { ...state, sseState: SSE_STATE.CONNECTED, sseError: null }

    case A.SSE_DISCONNECTED:
      return { ...state, sseState: SSE_STATE.DISCONNECTED }

    case A.SSE_CONFLICT:
      return { ...state, sseState: SSE_STATE.CONFLICT }

    case A.SSE_FAILED:
      return { ...state, sseState: SSE_STATE.FAILED, sseError: action.message }

    case A.TICK_RECEIVED: {
      const { data } = action
      const newHistory = [
        ...state.telemetryHistory,
        { tick: data.tick, timestamp: data.timestamp, ...data.telemetry },
      ].slice(-MAX_HISTORY)
      return {
        ...state,
        latestTick: data,
        latestAnalytics: data.analytics,
        latestRisk: data.risk,
        telemetryHistory: newHistory,
      }
    }

    case A.DECISION_LOADING:
      return { ...state, decisionLoading: true, decisionError: null }
    case A.DECISION_LOADED:
      return { ...state, decisionLoading: false, decisionResult: action.data, decisionError: null }
    case A.DECISION_ERROR:
      return { ...state, decisionLoading: false, decisionError: action.message }

    case A.WHATIF_LOADING:
      return { ...state, whatIfLoading: true, whatIfError: null, whatIfOptionId: action.optionId }
    case A.WHATIF_LOADED:
      return { ...state, whatIfLoading: false, whatIfResult: action.data, whatIfError: null }
    case A.WHATIF_ERROR:
      return { ...state, whatIfLoading: false, whatIfError: action.message }
    case A.WHATIF_CLEAR:
      return { ...state, whatIfResult: null, whatIfError: null, whatIfOptionId: null }

    case A.EXPLAIN_LOADING:
      return { ...state, explanationLoading: true, explanationError: null }
    case A.EXPLAIN_LOADED:
      return { ...state, explanationLoading: false, explanation: action.data, explanationError: null }
    case A.EXPLAIN_ERROR:
      return { ...state, explanationLoading: false, explanationError: action.message }

    case A.COPILOT_LOADING:
      return { ...state, copilotLoading: true, copilotError: null }
    case A.COPILOT_RESPONSE:
      // CopilotPanel stores message history locally; context only clears the
      // loading flag so all panels can react to the ready state.
      return { ...state, copilotLoading: false, copilotError: null }
    case A.COPILOT_ERROR:
      return { ...state, copilotLoading: false, copilotError: action.message }

    default:
      return state
  }
}

// ── Context ───────────────────────────────────────────────────────────────────

const AtlasContext = createContext(null)

export function AtlasProvider({ children }) {
  const [state, dispatch] = useReducer(reducer, initialState)
  const sseClientRef = useRef(null)

  // Track the previous composite_anomaly value so we know when to fetch
  // a fresh AI explanation (only when the anomaly state changes, not every tick).
  const prevCompositeAnomalyRef = useRef(null)

  // ── SSE lifecycle ──────────────────────────────────────────────────────────

  useEffect(() => {
    dispatch({ type: A.SSE_CONNECTING })

    sseClientRef.current = createSSEClient({
      onConnected: () => dispatch({ type: A.SSE_CONNECTED }),
      onDisconnected: () => dispatch({ type: A.SSE_DISCONNECTED }),
      onConflict: () => dispatch({ type: A.SSE_CONFLICT }),
      onError: (msg) => dispatch({ type: A.SSE_FAILED, message: msg }),
      onTick: (data) => dispatch({ type: A.TICK_RECEIVED, data }),
    })

    return () => {
      sseClientRef.current?.destroy()
      sseClientRef.current = null
    }
  }, []) // mount/unmount only

  // ── Auto-fetch AI explanation on composite anomaly change ──────────────────
  // We only fetch a new explanation when composite_anomaly transitions from
  // false → true (or on first detection) to avoid calling Granite every second.

  useEffect(() => {
    const current = state.latestAnalytics?.composite_anomaly ?? false
    const prev = prevCompositeAnomalyRef.current

    if (current === true && prev !== true) {
      // New composite anomaly detected — fetch explanation
      dispatch({ type: A.EXPLAIN_LOADING })
      fetchAnomalyExplanation()
        .then((data) => dispatch({ type: A.EXPLAIN_LOADED, data }))
        .catch((err) => dispatch({ type: A.EXPLAIN_ERROR, message: err.message }))
    }

    prevCompositeAnomalyRef.current = current
  }, [state.latestAnalytics?.composite_anomaly])

  // ── Action creators exposed to consumers ───────────────────────────────────

  const loadDecisionOptions = useCallback(() => {
    dispatch({ type: A.DECISION_LOADING })
    fetchDecisionOptions()
      .then((data) => dispatch({ type: A.DECISION_LOADED, data }))
      .catch((err) => dispatch({ type: A.DECISION_ERROR, message: err.message }))
  }, [])

  const runWhatIf = useCallback((optionId) => {
    dispatch({ type: A.WHATIF_LOADING, optionId })
    fetchWhatIf(optionId)
      .then((data) => dispatch({ type: A.WHATIF_LOADED, data }))
      .catch((err) => dispatch({ type: A.WHATIF_ERROR, message: err.message }))
  }, [])

  const clearWhatIf = useCallback(() => {
    dispatch({ type: A.WHATIF_CLEAR })
  }, [])

  const refreshExplanation = useCallback(() => {
    dispatch({ type: A.EXPLAIN_LOADING })
    fetchAnomalyExplanation()
      .then((data) => dispatch({ type: A.EXPLAIN_LOADED, data }))
      .catch((err) => dispatch({ type: A.EXPLAIN_ERROR, message: err.message }))
  }, [])

  // CopilotPanel manages its own message history display.
  // AtlasContext tracks loading flag, error, and returns the answer.
  const sendCopilotQuestion = useCallback(async (question) => {
    dispatch({ type: A.COPILOT_LOADING })
    try {
      const data = await askCopilot(question)
      dispatch({ type: A.COPILOT_RESPONSE, answer: data.answer })
      return data.answer
    } catch (err) {
      dispatch({ type: A.COPILOT_ERROR, message: err.message })
      throw err
    }
  }, [])

  const value = {
    state,
    loadDecisionOptions,
    runWhatIf,
    clearWhatIf,
    refreshExplanation,
    sendCopilotQuestion,
  }

  return (
    <AtlasContext.Provider value={value}>
      {children}
    </AtlasContext.Provider>
  )
}

/**
 * Hook to consume the Atlas context.
 * Must be used inside AtlasProvider.
 */
export function useAtlas() {
  const ctx = useContext(AtlasContext)
  if (!ctx) {
    throw new Error('useAtlas must be used inside <AtlasProvider>')
  }
  return ctx
}
