/**
 * ATLAS — Intelligence Panel
 *
 * Answers the operational question:
 *   "What is the system detecting, why does it matter, and
 *    what evidence supports the determination?"
 *
 * Architecture:
 *   - Deterministic outputs (severity, confidence, evidence, correlated signals)
 *     come from the SSE stream via context state.  They are always present first.
 *   - AI explanation (IBM Granite) is fetched automatically when composite_anomaly
 *     first becomes True, and is clearly labelled [AI EXPLANATION].
 *   - The operator can manually refresh the explanation via a button.
 *   - Granite is never implied to be the source of severity or risk scores.
 *
 * Detection method labels, evidence statements, and correlated-signal names
 * are all from the deterministic AnalyticsResult — not fabricated.
 */

import React from 'react'
import { useAtlas } from '../state/AtlasContext.jsx'
import Panel from './Panel.jsx'
import SourceTag from './SourceTag.jsx'
import {
  severityBadgeClasses,
  severityLabel,
  confidenceBandTextColor,
  detectionMethodLabel,
  isElevatedSeverity,
} from '../utils/severity.js'
import { formatRiskScore, formatBreachMinutes } from '../utils/formatting.js'

// ── Sub-components ────────────────────────────────────────────────────────────

function DetectionCard({ detection }) {
  return (
    <div className="border border-slate-700 rounded p-3 bg-slate-850 space-y-1.5">
      {/* Variable name + subsystem */}
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-mono text-slate-200">
          {detection.variable.replace(/_/g, '_\u200b')}
        </span>
        <span className="text-[9px] text-slate-500 uppercase tracking-wide">
          {detection.subsystem}
        </span>
      </div>
      {/* Detection method */}
      <div className="text-[10px] text-slate-500">
        {detectionMethodLabel(detection.detection_method)}
      </div>
      {/* Evidence statements */}
      {detection.evidence?.length > 0 && (
        <ul className="space-y-0.5" aria-label="Evidence">
          {detection.evidence.map((stmt, i) => (
            <li key={i} className="flex items-start gap-1.5 text-[10px] text-slate-400">
              <span className="text-slate-600 mt-0.5 shrink-0" aria-hidden="true">›</span>
              <span>{stmt}</span>
            </li>
          ))}
        </ul>
      )}
      {/* Trend */}
      {detection.trend_direction && detection.trend_direction !== 'flat' && (
        <div className="text-[10px] text-slate-500">
          Trend:{' '}
          <span className={detection.trend_direction === 'rising' ? 'text-orange-400' : 'text-blue-400'}>
            {detection.trend_direction}
          </span>
        </div>
      )}
    </div>
  )
}

function ExplanationBlock({ explanation, subsystem, loading, error, onRefresh }) {
  return (
    <div className="border border-violet-900 rounded p-3 bg-violet-950/30 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <SourceTag tag="AI_EXPLANATION" />
        <button
          onClick={onRefresh}
          disabled={loading}
          className="text-[10px] text-violet-500 hover:text-violet-300 disabled:opacity-40 transition-colors"
          aria-label="Refresh AI explanation"
        >
          {loading ? 'Generating…' : 'Refresh'}
        </button>
      </div>
      {loading && (
        <div className="flex items-center gap-2 text-[11px] text-violet-400">
          <span className="inline-block w-3 h-3 border border-violet-500 border-t-transparent rounded-full animate-spin" aria-hidden="true" />
          Generating explanation…
        </div>
      )}
      {error && !loading && (
        <p className="text-[11px] text-slate-400 italic">{error}</p>
      )}
      {explanation && !loading && (
        <>
          {subsystem && (
            <div className="text-[9px] tracking-widest uppercase text-violet-600">
              {subsystem}
            </div>
          )}
          <p className="text-[12px] text-slate-300 leading-relaxed whitespace-pre-wrap">
            {explanation}
          </p>
        </>
      )}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function IntelligencePanel() {
  const { state, refreshExplanation } = useAtlas()
  const {
    latestAnalytics,
    latestRisk,
    explanation,
    explanationLoading,
    explanationError,
    sseState,
  } = state

  const hasData = latestAnalytics !== null
  const anomalyActive = hasData && (
    latestAnalytics.composite_anomaly ||
    latestAnalytics.detections?.length > 0
  )
  const severity = latestRisk?.severity ?? 'NONE'

  // ── Status badge ────────────────────────────────────────────────────────────

  const badge = hasData && isElevatedSeverity(severity) ? (
    <span className={`text-[10px] font-semibold px-2 py-0.5 rounded ${severityBadgeClasses(severity)}`}>
      {severityLabel(severity)}
    </span>
  ) : hasData ? (
    <span className="text-[10px] text-emerald-500">Nominal</span>
  ) : null

  return (
    <Panel title="Intelligence" badge={badge}>
      {/* ── Not connected ──────────────────────────────────────────────── */}
      {!hasData && (
        <div className="flex items-center justify-center h-full min-h-[12rem] text-slate-600 text-sm p-4">
          {sseState === 'CONFLICT'
            ? 'Another operator is streaming.'
            : 'Waiting for telemetry stream…'}
        </div>
      )}

      {/* ── Nominal: no anomaly ─────────────────────────────────────────── */}
      {hasData && !anomalyActive && (
        <div className="flex flex-col items-center justify-center gap-2 p-6 min-h-[12rem]">
          <div className="w-2 h-2 rounded-full bg-emerald-500" aria-hidden="true" />
          <p className="text-sm text-slate-400">No anomalies detected</p>
          <p className="text-[11px] text-slate-600">All subsystems nominal</p>
        </div>
      )}

      {/* ── Anomaly detected ────────────────────────────────────────────── */}
      {hasData && anomalyActive && (
        <div className="p-4 space-y-4">

          {/* ── Composite anomaly header ───────────────────────────────── */}
          {latestAnalytics.composite_anomaly && (
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-3 flex-wrap">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className={`text-xs font-semibold px-2 py-0.5 rounded ${severityBadgeClasses(latestAnalytics.composite_severity ?? severity)}`}>
                    {severityLabel(latestAnalytics.composite_severity ?? severity)}
                  </span>
                  <span className="text-xs text-slate-300">
                    Cross-signal correlation — {latestAnalytics.composite_subsystem ?? ''}
                  </span>
                </div>
                {latestAnalytics.composite_confidence_band && (
                  <span className={`text-[10px] font-medium ${confidenceBandTextColor(latestAnalytics.composite_confidence_band)}`}>
                    Confidence: {latestAnalytics.composite_confidence_band}
                  </span>
                )}
              </div>

              {/* Correlated signals list */}
              {latestAnalytics.correlated_signals?.length > 0 && (
                <div className="flex items-center gap-1.5 flex-wrap">
                  <span className="text-[10px] text-slate-500 uppercase tracking-wide">Correlated:</span>
                  {latestAnalytics.correlated_signals.map((sig) => (
                    <span key={sig} className="text-[10px] font-mono bg-slate-700 text-slate-300 px-1.5 py-0.5 rounded">
                      {sig}
                    </span>
                  ))}
                </div>
              )}

              <SourceTag tag="COMPUTED" />
            </div>
          )}

          {/* ── Risk context ────────────────────────────────────────────── */}
          {latestRisk && (
            <div className="flex items-center gap-4 text-[11px] text-slate-400 border-t border-slate-700 pt-3">
              <div>
                Risk score:{' '}
                <span className="font-mono text-slate-200">
                  {formatRiskScore(latestRisk.risk_score)}
                </span>{' '}
                <SourceTag tag="COMPUTED" className="ml-1" />
              </div>
              {latestRisk.estimated_threshold_breach_minutes != null && (
                <div>
                  Est. breach:{' '}
                  <span className="font-mono text-orange-300">
                    {formatBreachMinutes(latestRisk.estimated_threshold_breach_minutes)}
                  </span>
                </div>
              )}
              <div>
                Redundancy:{' '}
                <span className={latestRisk.redundancy_available ? 'text-emerald-400' : 'text-red-400'}>
                  {latestRisk.redundancy_available ? 'Available' : 'None'}
                </span>
              </div>
            </div>
          )}

          {/* ── Individual detections ───────────────────────────────────── */}
          {latestAnalytics.detections?.length > 0 && (
            <div className="space-y-2">
              <div className="text-[9px] tracking-widest uppercase text-slate-600">
                Detected signals
              </div>
              {latestAnalytics.detections.map((det) => (
                <DetectionCard key={det.variable} detection={det} />
              ))}
            </div>
          )}

          {/* ── AI Explanation ──────────────────────────────────────────── */}
          {(explanation || explanationLoading || explanationError) && (
            <ExplanationBlock
              explanation={explanation?.explanation}
              subsystem={explanation?.subsystem}
              loading={explanationLoading}
              error={explanationError}
              onRefresh={refreshExplanation}
            />
          )}
          {/* If no explanation yet but anomaly is active, show refresh trigger */}
          {!explanation && !explanationLoading && !explanationError && latestAnalytics.composite_anomaly && (
            <button
              onClick={refreshExplanation}
              className="text-[11px] text-violet-500 hover:text-violet-300 transition-colors flex items-center gap-1.5"
            >
              <span className="text-violet-700">✦</span>
              Generate AI explanation
            </button>
          )}

        </div>
      )}
    </Panel>
  )
}
