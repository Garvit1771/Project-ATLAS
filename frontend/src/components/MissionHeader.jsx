/**
 * ATLAS — Mission Header
 *
 * Full-width header communicating:
 *   - ATLAS identity and scenario
 *   - Mission phase
 *   - SSE connection state
 *   - Current simulation tick
 *   - System health / risk severity
 *   - Active alert banner (when severity >= HIGH)
 *
 * Transitions calmly: the interface reads quiet during nominal operations
 * and escalates with measured urgency as fault severity rises.
 */

import React from 'react'
import { useAtlas } from '../state/AtlasContext.jsx'
import {
  severityDotColor,
  severityLabel,
  isCriticalSeverity,
  isElevatedSeverity,
  connectionLabel,
  connectionDotColor,
} from '../utils/severity.js'
import { formatRiskScore, formatTimestamp } from '../utils/formatting.js'

export default function MissionHeader() {
  const { state } = useAtlas()
  const { sseState, latestRisk, latestTick, latestAnalytics } = state

  const severity  = latestRisk?.severity ?? 'NONE'
  const riskScore = latestRisk?.risk_score ?? null
  const tick      = latestTick?.tick ?? null
  const timestamp = latestTick?.timestamp ?? null
  const phase     = 'Orbital Insertion'   // from scenario config — mission_context
  const scenario  = 'ALPHA-1-FAULT-01'

  const showAlert = isCriticalSeverity(severity)
  const showWarn  = isElevatedSeverity(severity) && !showAlert

  // Dominant variable for alert text
  const dominantVar = latestRisk?.dominant_variable
  const correlated  = latestAnalytics?.correlated_signals ?? []

  return (
    <header className="flex flex-col border-b border-slate-700 bg-slate-900 shrink-0">
      {/* ── Alert banner ────────────────────────────────────────────────── */}
      {(showAlert || showWarn) && (
        <div
          className={`flex items-center gap-2 px-5 py-2 text-xs font-medium tracking-wide ${
            showAlert
              ? 'bg-red-950 border-b border-red-800 text-red-300'
              : 'bg-yellow-950 border-b border-yellow-800 text-yellow-300'
          }`}
          role="alert"
          aria-live="assertive"
        >
          {/* Pulsing indicator */}
          <span
            className={`inline-block w-1.5 h-1.5 rounded-full shrink-0 ${
              showAlert ? 'bg-red-400 animate-pulse' : 'bg-yellow-400 animate-pulse'
            }`}
            aria-hidden="true"
          />
          <span className="font-semibold uppercase tracking-widest mr-1">
            {showAlert ? 'Alert' : 'Caution'}
          </span>
          {dominantVar
            ? `Anomaly detected — ${dominantVar.replace(/_/g, ' ')}${
                correlated.length >= 2
                  ? ` · Cross-signal correlation across ${correlated.length} propulsion signals`
                  : ''
              }`
            : 'System anomaly detected. Review Intelligence panel.'}
        </div>
      )}

      {/* ── Main header row ─────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-5 py-3 gap-6">

        {/* Left — identity */}
        <div className="flex items-center gap-4 min-w-0">
          <div className="shrink-0">
            <div className="text-[11px] font-mono font-bold tracking-[0.2em] text-slate-100 leading-none">
              ATLAS
            </div>
            <div className="text-[9px] tracking-widest uppercase text-slate-500 mt-0.5 leading-none">
              Mission Control
            </div>
          </div>
          {/* Divider */}
          <div className="h-7 w-px bg-slate-700 shrink-0" aria-hidden="true" />
          {/* Scenario / phase */}
          <div className="min-w-0">
            <div className="text-[10px] font-mono text-slate-400 truncate">{scenario}</div>
            <div className="text-[11px] font-medium text-slate-200 mt-0.5 leading-tight">
              {phase}
            </div>
          </div>
        </div>

        {/* Center — health indicator */}
        <div className="flex items-center gap-3 flex-1 justify-center">
          {/* System health pill */}
          <div className="flex items-center gap-2 bg-slate-800 border border-slate-700 rounded px-3 py-1.5">
            <span
              className={`w-2 h-2 rounded-full shrink-0 ${severityDotColor(severity)}`}
              aria-hidden="true"
            />
            <span className="text-xs font-medium text-slate-200">
              {severityLabel(severity)}
            </span>
            {riskScore !== null && (
              <>
                <span className="text-slate-600 text-xs" aria-hidden="true">·</span>
                <span className="text-xs font-mono text-slate-400">
                  Risk {formatRiskScore(riskScore)}
                </span>
              </>
            )}
          </div>
        </div>

        {/* Right — connection + tick */}
        <div className="flex items-center gap-5 shrink-0">
          {/* Tick counter */}
          {tick !== null ? (
            <div className="text-right">
              <div className="text-[9px] tracking-widest uppercase text-slate-500 leading-none">Tick</div>
              <div className="text-sm font-mono font-semibold text-slate-200 mt-0.5 leading-none tabular-nums">
                {tick.toString().padStart(5, '0')}
              </div>
            </div>
          ) : (
            <div className="text-right">
              <div className="text-[9px] tracking-widest uppercase text-slate-500 leading-none">Tick</div>
              <div className="text-sm font-mono text-slate-600 mt-0.5 leading-none">—</div>
            </div>
          )}

          {/* Timestamp */}
          {timestamp && (
            <div className="text-right hidden sm:block">
              <div className="text-[9px] tracking-widest uppercase text-slate-500 leading-none">Time</div>
              <div className="text-[11px] font-mono text-slate-400 mt-0.5 leading-none tabular-nums">
                {formatTimestamp(timestamp)}
              </div>
            </div>
          )}

          {/* Connection state */}
          <div className="flex items-center gap-1.5">
            <span
              className={`w-1.5 h-1.5 rounded-full shrink-0 ${connectionDotColor(sseState)}`}
              aria-hidden="true"
            />
            <span className="text-[11px] text-slate-400">
              {connectionLabel(sseState)}
            </span>
          </div>
        </div>
      </div>
    </header>
  )
}
