/**
 * ATLAS — SourceTag component
 *
 * Displays one of the four source tags defined in methodology.md Section 8.
 *
 * Tags are visually distinct but restrained — they communicate provenance
 * without competing with the primary data.
 *
 * Props:
 *   tag — 'COMPUTED' | 'MISSION_PARAMS' | 'AI_EXPLANATION' | 'OPERATOR'
 *   className — optional additional classes
 */

import React from 'react'

const TAG_STYLES = {
  COMPUTED: {
    label: 'COMPUTED',
    classes: 'bg-slate-700 text-slate-300 border-slate-600',
  },
  MISSION_PARAMS: {
    label: 'MISSION PARAMS',
    classes: 'bg-blue-950 text-blue-300 border-blue-800',
  },
  AI_EXPLANATION: {
    label: 'AI EXPLANATION',
    classes: 'bg-violet-950 text-violet-300 border-violet-800',
  },
  OPERATOR: {
    label: 'OPERATOR',
    classes: 'bg-emerald-950 text-emerald-300 border-emerald-800',
  },
}

export default function SourceTag({ tag, className = '' }) {
  const config = TAG_STYLES[tag]
  if (!config) return null
  return (
    <span
      className={`inline-flex items-center border font-mono text-[10px] tracking-wider px-1.5 py-0.5 rounded-sm leading-none ${config.classes} ${className}`}
      aria-label={`Source: ${config.label}`}
    >
      {config.label}
    </span>
  )
}
