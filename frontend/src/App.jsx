/**
 * ATLAS — Application root
 *
 * Four-panel mission-control layout:
 *
 *   ┌─────────────────────────────────────────┐
 *   │  MissionHeader (full width)             │
 *   │  ConnectionBanner (conditional)         │
 *   ├───────────────────┬─────────────────────┤
 *   │  TelemetryPanel   │  IntelligencePanel  │
 *   ├───────────────────┼─────────────────────┤
 *   │  DecisionCenter   │  CopilotPanel       │
 *   └───────────────────┴─────────────────────┘
 *
 * Desktop: 2×2 panel grid
 * Tablet/mobile: vertically stacked (single column)
 *
 * AtlasProvider wraps the entire tree, providing the Context+useReducer
 * state management and SSE lifecycle to all child components.
 */

import React from 'react'
import { AtlasProvider } from './state/AtlasContext.jsx'
import MissionHeader from './components/MissionHeader.jsx'
import ConnectionBanner from './components/ConnectionBanner.jsx'
import TelemetryPanel from './components/TelemetryPanel.jsx'
import IntelligencePanel from './components/IntelligencePanel.jsx'
import DecisionCenterPanel from './components/DecisionCenterPanel.jsx'
import CopilotPanel from './components/CopilotPanel.jsx'

function AppLayout() {
  return (
    <div className="min-h-screen bg-slate-900 flex flex-col font-sans">
      {/* ── Top bar ─────────────────────────────────────────────────────── */}
      <MissionHeader />
      <ConnectionBanner />

      {/* ── Panel grid ──────────────────────────────────────────────────── */}
      <main
        className="flex-1 grid grid-cols-1 lg:grid-cols-2 gap-3 p-3 min-h-0"
        style={{ gridTemplateRows: 'minmax(0, 1fr) minmax(0, 1fr)' }}
        aria-label="Mission control panels"
      >
        <TelemetryPanel />
        <IntelligencePanel />
        <DecisionCenterPanel />
        <CopilotPanel />
      </main>
    </div>
  )
}

export default function App() {
  return (
    <AtlasProvider>
      <AppLayout />
    </AtlasProvider>
  )
}
