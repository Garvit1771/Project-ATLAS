/**
 * ATLAS — Panel wrapper component
 *
 * Consistent container for all four mission-control panels.
 * Provides surface background, border, header slot, and content slot.
 *
 * Props:
 *   title       — panel header text
 *   badge       — optional badge element (e.g. severity or status indicator)
 *   children    — panel content
 *   className   — additional outer classes
 *   contentClass — additional classes for the content area
 */

import React from 'react'

export default function Panel({ title, badge, children, className = '', contentClass = '' }) {
  return (
    <section
      className={`flex flex-col bg-slate-800 border border-slate-700 rounded ${className}`}
      aria-label={title}
    >
      {/* Panel header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-700 shrink-0">
        <h2 className="text-[11px] font-semibold tracking-widest uppercase text-slate-400 select-none">
          {title}
        </h2>
        {badge && <div className="ml-3">{badge}</div>}
      </div>
      {/* Panel content */}
      <div className={`flex-1 min-h-0 overflow-auto ${contentClass}`}>
        {children}
      </div>
    </section>
  )
}
