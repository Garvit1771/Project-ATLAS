/**
 * ATLAS — Telemetry Panel
 *
 * Live Recharts time-series visualization of spacecraft telemetry.
 *
 * Features:
 *   - 1 Hz live updates from the SSE stream
 *   - Rolling MAX_HISTORY-tick client-side buffer
 *   - Subsystem filter (propulsion, power, computing, attitude, comms, environment)
 *   - 2–3 key variables displayed per subsystem with distinct colours
 *   - Readable axes with units
 *   - Hover tooltip with values
 *   - Current-value readout alongside chart
 *   - Minimal, restrained styling — an engineering visualization, not a toy
 */

import React, { useState, useMemo } from 'react'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts'
import { useAtlas } from '../state/AtlasContext.jsx'
import Panel from './Panel.jsx'
import {
  SUBSYSTEM_VARIABLES,
  SUBSYSTEM_LABELS,
  TELEMETRY_META,
  formatTelemetryValue,
} from '../utils/formatting.js'

const SUBSYSTEMS = Object.keys(SUBSYSTEM_VARIABLES)

// ── Custom tooltip ────────────────────────────────────────────────────────────

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-slate-900 border border-slate-600 rounded px-3 py-2 text-xs">
      <div className="text-slate-500 mb-1 font-mono">Tick {label}</div>
      {payload.map((entry) => (
        <div key={entry.dataKey} className="flex items-center gap-2 leading-relaxed">
          <span className="w-2 h-2 rounded-full shrink-0" style={{ background: entry.color }} />
          <span className="text-slate-300">{TELEMETRY_META[entry.dataKey]?.label ?? entry.dataKey}:</span>
          <span className="font-mono text-slate-100">
            {entry.value?.toFixed(TELEMETRY_META[entry.dataKey]?.fmt ?? 2)}{' '}
            {TELEMETRY_META[entry.dataKey]?.unit ?? ''}
          </span>
        </div>
      ))}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function TelemetryPanel() {
  const { state } = useAtlas()
  const { telemetryHistory, latestTick, sseState } = state
  const [selectedSubsystem, setSelectedSubsystem] = useState('propulsion')

  const variables = SUBSYSTEM_VARIABLES[selectedSubsystem] ?? []

  // Latest values for the current-value readout
  const latestTelemetry = latestTick?.telemetry ?? null

  // Chart data: only use every Nth point when buffer is large to avoid
  // rendering thousands of SVG elements.  At 300 points this is fine.
  const chartData = useMemo(() => {
    return telemetryHistory.map((r) => ({ tick: r.tick, ...r }))
  }, [telemetryHistory])

  const hasData = chartData.length > 0

  // Compute Y-axis domain with slight padding
  const yDomain = useMemo(() => {
    if (!hasData || !variables.length) return ['auto', 'auto']
    const keys = variables.map(([k]) => k)
    let min = Infinity
    let max = -Infinity
    for (const row of chartData) {
      for (const key of keys) {
        const v = row[key]
        if (v != null) {
          if (v < min) min = v
          if (v > max) max = v
        }
      }
    }
    if (!isFinite(min)) return ['auto', 'auto']
    const pad = (max - min) * 0.08 || 1
    return [+(min - pad).toFixed(2), +(max + pad).toFixed(2)]
  }, [chartData, variables])

  // ── Status badge ──────────────────────────────────────────────────────────

  const statusBadge = hasData ? (
    <span className="text-[10px] font-mono text-emerald-400">
      {telemetryHistory.length} ticks
    </span>
  ) : (
    <span className="text-[10px] font-mono text-slate-500">
      {sseState === 'CONNECTED' ? 'Awaiting data…' : 'Stream offline'}
    </span>
  )

  return (
    <Panel title="Telemetry" badge={statusBadge} contentClass="p-0">
      {/* Subsystem filter */}
      <div className="flex items-center gap-1 px-4 pt-3 pb-2 flex-wrap">
        {SUBSYSTEMS.map((sub) => (
          <button
            key={sub}
            onClick={() => setSelectedSubsystem(sub)}
            className={`px-2.5 py-1 text-[10px] font-medium tracking-wide rounded transition-colors ${
              selectedSubsystem === sub
                ? 'bg-slate-600 text-slate-100'
                : 'text-slate-500 hover:text-slate-300 hover:bg-slate-750'
            }`}
            aria-pressed={selectedSubsystem === sub}
            aria-label={`Show ${SUBSYSTEM_LABELS[sub]} telemetry`}
          >
            {SUBSYSTEM_LABELS[sub]}
          </button>
        ))}
      </div>

      {/* Chart area */}
      {!hasData ? (
        <div className="flex items-center justify-center h-40 text-slate-600 text-sm">
          {sseState === 'CONFLICT'
            ? 'Another operator is streaming. Cannot display telemetry.'
            : sseState === 'FAILED'
            ? 'Connection failed. Refresh to retry.'
            : 'Waiting for telemetry stream…'}
        </div>
      ) : (
        <div className="px-2 pb-3">
          <ResponsiveContainer width="100%" height={200}>
            <LineChart
              data={chartData}
              margin={{ top: 4, right: 16, bottom: 0, left: 4 }}
            >
              <CartesianGrid
                strokeDasharray="2 4"
                stroke="#1e293b"
                vertical={false}
              />
              <XAxis
                dataKey="tick"
                tick={{ fontSize: 9, fill: '#475569', fontFamily: 'monospace' }}
                tickLine={false}
                axisLine={{ stroke: '#334155' }}
                label={{
                  value: 'Tick',
                  position: 'insideBottomRight',
                  offset: -4,
                  fontSize: 9,
                  fill: '#475569',
                }}
              />
              <YAxis
                domain={yDomain}
                tick={{ fontSize: 9, fill: '#475569', fontFamily: 'monospace' }}
                tickLine={false}
                axisLine={false}
                width={44}
              />
              <Tooltip content={<ChartTooltip />} />
              {variables.map(([key, color]) => (
                <Line
                  key={key}
                  type="monotone"
                  dataKey={key}
                  stroke={color}
                  strokeWidth={1.5}
                  dot={false}
                  activeDot={{ r: 3, fill: color }}
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Current values readout */}
      {hasData && latestTelemetry && (
        <div className="px-4 pb-3 border-t border-slate-700 pt-2">
          <div className="text-[9px] tracking-widest uppercase text-slate-600 mb-1.5">Current values</div>
          <div className="flex flex-wrap gap-x-5 gap-y-1">
            {variables.map(([key, color]) => {
              const val = latestTelemetry[key]
              const meta = TELEMETRY_META[key]
              return (
                <div key={key} className="flex items-center gap-1.5">
                  <span className="w-2 h-px shrink-0 inline-block" style={{ background: color }} />
                  <span className="text-[10px] text-slate-500">{meta?.label ?? key}:</span>
                  <span className="text-[11px] font-mono text-slate-200 tabular-nums">
                    {val != null ? `${val.toFixed(meta?.fmt ?? 2)} ${meta?.unit ?? ''}` : '—'}
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </Panel>
  )
}
