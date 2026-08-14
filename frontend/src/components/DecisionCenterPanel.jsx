/**
 * ATLAS — Decision Center Panel
 *
 * Deterministic decision support interface.
 *
 * Architecture:
 *   - Options are loaded from GET /api/decision/options on user request.
 *   - Each option card shows computed_risk_score_after [COMPUTED] and
 *     mission parameters [MISSION PARAMS].
 *   - What-if analysis uses POST /api/decision/whatif and shows the
 *     projected risk delta alongside the Granite narrative [AI EXPLANATION].
 *   - ACCEPT / REJECT / INVESTIGATE buttons are present as operational
 *     acknowledgement controls.  In Phase 8 they record operator intent
 *     in UI state only — backend state mutation is a Phase 9 decision.
 *   - The ranking is pre-computed by the backend (lowest projected risk first).
 *     ATLAS does not imply which option the operator should choose.
 *
 * Every numerical value carries its source tag.
 */

import React, { useState } from 'react'
import { useAtlas } from '../state/AtlasContext.jsx'
import Panel from './Panel.jsx'
import SourceTag from './SourceTag.jsx'
import {
  strengthBadgeClasses,
  severityBadgeClasses,
} from '../utils/severity.js'
import {
  formatRiskScore,
  formatRiskDelta,
} from '../utils/formatting.js'

// ── Option card ───────────────────────────────────────────────────────────────

function OptionCard({ option, rank, isSelected, onSelect, onAction, actionState }) {
  const delta = option.computed_risk_score_after - (actionState?.currentRisk ?? option.computed_risk_score_after)
  const { text: deltaText, isReduction } = formatRiskDelta(
    option.computed_risk_score_after - (actionState?.currentRisk ?? option.computed_risk_score_after)
  )

  return (
    <div
      className={`border rounded p-3.5 space-y-3 transition-colors cursor-pointer ${
        isSelected
          ? 'border-slate-500 bg-slate-750'
          : 'border-slate-700 hover:border-slate-600 bg-slate-800'
      }`}
      onClick={() => onSelect(option.option_id)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') onSelect(option.option_id) }}
      aria-pressed={isSelected}
      aria-label={`Option ${rank}: ${option.label}`}
    >
      {/* Header row */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-[9px] font-mono text-slate-600 shrink-0">#{rank}</span>
          <span className="text-[12px] font-semibold text-slate-100 leading-tight">{option.label}</span>
        </div>
        <span className={`text-[10px] font-semibold px-2 py-0.5 rounded shrink-0 ${strengthBadgeClasses(option.recommendation_strength)}`}>
          {option.recommendation_strength}
        </span>
      </div>

      {/* Description */}
      <p className="text-[11px] text-slate-400 leading-relaxed">{option.description}</p>

      {/* Metrics grid */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-[11px]">
        <div className="flex items-center gap-1.5">
          <span className="text-slate-500">Projected risk:</span>
          <span className="font-mono text-slate-200">{formatRiskScore(option.computed_risk_score_after)}</span>
          <SourceTag tag="COMPUTED" />
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-slate-500">Fuel cost:</span>
          <span className="font-mono text-slate-200">+{option.fuel_cost_pct}%</span>
          <SourceTag tag="MISSION_PARAMS" />
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-slate-500">Time delay:</span>
          <span className="font-mono text-slate-200">
            {option.time_delay_min === 0 ? 'None' : `${option.time_delay_min} min`}
          </span>
          <SourceTag tag="MISSION_PARAMS" />
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-slate-500">Constraints:</span>
          <span className={option.mission_constraint_satisfied ? 'text-emerald-400' : 'text-red-400'}>
            {option.mission_constraint_satisfied ? 'Satisfied' : 'Violated'}
          </span>
          <SourceTag tag="MISSION_PARAMS" />
        </div>
      </div>

      {/* Subsystem stress */}
      {option.subsystem_stress?.length > 0 && (
        <div className="flex items-center gap-1.5 flex-wrap text-[10px] text-slate-500">
          <span>Stress:</span>
          {option.subsystem_stress.map((s) => (
            <span key={s} className="font-mono bg-slate-700 text-slate-400 px-1.5 py-0.5 rounded">{s}</span>
          ))}
        </div>
      )}

      {/* Action buttons — shown when this card is selected */}
      {isSelected && (
        <div
          className="flex items-center gap-2 pt-2 border-t border-slate-700"
          onClick={(e) => e.stopPropagation()}
        >
          <button
            onClick={() => onAction(option.option_id, 'ACCEPT')}
            className={`flex-1 px-3 py-1.5 text-xs font-semibold rounded transition-colors ${
              actionState?.action === 'ACCEPT'
                ? 'bg-emerald-700 text-emerald-100'
                : 'bg-slate-700 text-slate-300 hover:bg-emerald-900 hover:text-emerald-300'
            }`}
            aria-label={`Accept option: ${option.label}`}
          >
            ACCEPT
          </button>
          <button
            onClick={() => onAction(option.option_id, 'INVESTIGATE')}
            className={`flex-1 px-3 py-1.5 text-xs font-semibold rounded transition-colors ${
              actionState?.action === 'INVESTIGATE'
                ? 'bg-blue-700 text-blue-100'
                : 'bg-slate-700 text-slate-300 hover:bg-blue-900 hover:text-blue-300'
            }`}
            aria-label={`Investigate option: ${option.label}`}
          >
            INVESTIGATE
          </button>
          <button
            onClick={() => onAction(option.option_id, 'REJECT')}
            className={`flex-1 px-3 py-1.5 text-xs font-semibold rounded transition-colors ${
              actionState?.action === 'REJECT'
                ? 'bg-red-800 text-red-100'
                : 'bg-slate-700 text-slate-300 hover:bg-red-950 hover:text-red-400'
            }`}
            aria-label={`Reject option: ${option.label}`}
          >
            REJECT
          </button>
        </div>
      )}
    </div>
  )
}

// ── What-if result block ──────────────────────────────────────────────────────

function WhatIfBlock({ result, loading, error, optionId }) {
  if (loading) {
    return (
      <div className="flex items-center gap-2 text-[11px] text-slate-400 p-3 border border-slate-700 rounded bg-slate-800">
        <span className="inline-block w-3 h-3 border border-slate-500 border-t-transparent rounded-full animate-spin" aria-hidden="true" />
        Computing what-if projection…
      </div>
    )
  }
  if (error) {
    return (
      <div className="p-3 border border-slate-700 rounded bg-slate-800 text-[11px] text-slate-400">
        {error}
      </div>
    )
  }
  if (!result) return null

  const wi = result.what_if
  const { text: deltaText, isReduction } = formatRiskDelta(wi.delta)
  const narrative = result.ai_narrative

  return (
    <div className="border border-slate-700 rounded bg-slate-800 overflow-hidden">
      {/* Numeric result */}
      <div className="px-4 py-3 space-y-1.5 border-b border-slate-700">
        <div className="text-[9px] tracking-widest uppercase text-slate-600">What-if projection</div>
        <div className="flex items-center gap-4 flex-wrap text-[11px]">
          <span className="text-slate-400">
            Current: <span className="font-mono text-slate-200">{formatRiskScore(wi.current_risk)}</span>
          </span>
          <span className="text-slate-600">→</span>
          <span className="text-slate-400">
            Projected: <span className="font-mono text-slate-200">{formatRiskScore(wi.projected_risk)}</span>
          </span>
          <span className={`font-mono font-semibold text-sm ${isReduction ? 'text-emerald-400' : 'text-red-400'}`}>
            {deltaText}
          </span>
          <SourceTag tag="COMPUTED" />
        </div>
      </div>
      {/* Granite narrative */}
      {narrative && (
        <div className="px-4 py-3 space-y-1.5">
          <SourceTag tag="AI_EXPLANATION" />
          <p className="text-[11px] text-slate-300 leading-relaxed">{narrative}</p>
        </div>
      )}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function DecisionCenterPanel() {
  const { state, loadDecisionOptions, runWhatIf, clearWhatIf } = useAtlas()
  const {
    latestRisk,
    latestTick,
    decisionResult,
    decisionLoading,
    decisionError,
    whatIfResult,
    whatIfLoading,
    whatIfError,
    whatIfOptionId,
    sseState,
  } = state

  const hasData       = latestRisk !== null
  const [selectedId, setSelectedId] = useState(null)
  // Operator action log: { [option_id]: { action: 'ACCEPT'|'REJECT'|'INVESTIGATE' } }
  const [actionLog, setActionLog] = useState({})

  function handleSelect(optionId) {
    setSelectedId((prev) => {
      if (prev === optionId) return null
      // Run what-if automatically on selection
      runWhatIf(optionId)
      return optionId
    })
  }

  function handleAction(optionId, action) {
    setActionLog((prev) => ({ ...prev, [optionId]: { action } }))
  }

  const badge = hasData ? (
    <span className="text-[11px] font-mono text-slate-400">
      Risk {formatRiskScore(latestRisk.risk_score)}{' '}
      <SourceTag tag="COMPUTED" />
    </span>
  ) : null

  return (
    <Panel title="Decision Center" badge={badge}>
      {/* ── Not ready ─────────────────────────────────────────────────── */}
      {!hasData && (
        <div className="flex items-center justify-center min-h-[12rem] text-slate-600 text-sm p-4">
          {sseState === 'CONFLICT'
            ? 'Another operator is streaming.'
            : 'Waiting for telemetry stream…'}
        </div>
      )}

      {/* ── Ready ─────────────────────────────────────────────────────── */}
      {hasData && (
        <div className="p-4 space-y-4">
          {/* Current risk summary */}
          <div className="flex items-center gap-3 text-[11px] text-slate-400">
            <span>
              Current risk:{' '}
              <span className="font-mono text-slate-200 font-semibold">
                {formatRiskScore(latestRisk.risk_score)}
              </span>
            </span>
            <SourceTag tag="COMPUTED" />
            {latestRisk.dominant_variable && (
              <span className="text-slate-600">
                ↑ {latestRisk.dominant_variable.replace(/_/g, ' ')}
              </span>
            )}
          </div>

          {/* Load options button */}
          {!decisionResult && !decisionLoading && !decisionError && (
            <button
              onClick={loadDecisionOptions}
              className="w-full text-xs font-medium bg-slate-700 hover:bg-slate-600 text-slate-200 rounded py-2 transition-colors"
            >
              Load decision options
            </button>
          )}

          {/* Loading */}
          {decisionLoading && (
            <div className="flex items-center gap-2 text-[11px] text-slate-400">
              <span className="inline-block w-3 h-3 border border-slate-500 border-t-transparent rounded-full animate-spin" aria-hidden="true" />
              Loading options…
            </div>
          )}

          {/* Error */}
          {decisionError && !decisionLoading && (
            <div className="text-[11px] text-slate-400 p-3 border border-slate-700 rounded">
              {decisionError}
              <button
                onClick={loadDecisionOptions}
                className="ml-3 text-slate-300 underline underline-offset-2"
              >
                Retry
              </button>
            </div>
          )}

          {/* Options — already ranked ascending by backend */}
          {decisionResult && !decisionLoading && (
            <>
              <div className="text-[9px] tracking-widest uppercase text-slate-600">
                Options — ranked by projected risk
              </div>
              <div className="space-y-2.5">
                {decisionResult.options.map((opt, idx) => (
                  <OptionCard
                    key={opt.option_id}
                    option={opt}
                    rank={idx + 1}
                    isSelected={selectedId === opt.option_id}
                    onSelect={handleSelect}
                    onAction={handleAction}
                    actionState={actionLog[opt.option_id]
                      ? { ...actionLog[opt.option_id], currentRisk: decisionResult.current_risk_score }
                      : { currentRisk: decisionResult.current_risk_score }
                    }
                  />
                ))}
              </div>

              {/* Refresh options */}
              <button
                onClick={() => { loadDecisionOptions(); clearWhatIf(); setSelectedId(null) }}
                className="text-[10px] text-slate-500 hover:text-slate-300 transition-colors"
              >
                Refresh options
              </button>

              {/* What-if result */}
              {(whatIfResult || whatIfLoading || whatIfError) && (
                <WhatIfBlock
                  result={whatIfResult}
                  loading={whatIfLoading}
                  error={whatIfError}
                  optionId={whatIfOptionId}
                />
              )}
            </>
          )}
        </div>
      )}
    </Panel>
  )
}
