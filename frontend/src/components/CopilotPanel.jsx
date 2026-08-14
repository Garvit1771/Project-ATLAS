/**
 * ATLAS — Copilot Panel
 *
 * Conversational AI interface integrated into the mission console.
 *
 * Architecture:
 *   - Each question is stateless on the backend (no conversation history
 *     is maintained server-side — by design per methodology.md Section 7).
 *   - The frontend maintains its own visible conversation history for UX.
 *   - Questions are grounded in the current simulation state (the backend
 *     reads latest analytics/risk when processing the question).
 *   - Responses are clearly labeled [AI EXPLANATION].
 *   - Granite unavailability results in the fallback message — the panel
 *     remains usable.
 *   - Keyboard submission (Enter key) is supported.
 *   - The input remains disabled while a response is loading to prevent
 *     duplicate submissions.
 */

import React, { useState, useRef, useEffect } from 'react'
import { useAtlas } from '../state/AtlasContext.jsx'
import Panel from './Panel.jsx'
import SourceTag from './SourceTag.jsx'

// ── Message bubble ────────────────────────────────────────────────────────────

function MessageBubble({ role, content }) {
  const isUser = role === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} gap-2`}>
      {!isUser && (
        <div className="w-5 h-5 rounded-full bg-violet-900 border border-violet-700 flex items-center justify-center shrink-0 mt-0.5">
          <span className="text-[7px] text-violet-300 font-bold">AI</span>
        </div>
      )}
      <div
        className={`max-w-[84%] rounded px-3 py-2 text-[12px] leading-relaxed ${
          isUser
            ? 'bg-slate-700 text-slate-200'
            : 'bg-slate-800 border border-slate-700 text-slate-300'
        }`}
      >
        {!isUser && (
          <div className="mb-1">
            <SourceTag tag="AI_EXPLANATION" />
          </div>
        )}
        <p className="whitespace-pre-wrap">{content}</p>
      </div>
      {isUser && (
        <div className="w-5 h-5 rounded-full bg-slate-600 border border-slate-500 flex items-center justify-center shrink-0 mt-0.5">
          <span className="text-[7px] text-slate-300 font-bold">OP</span>
          <span className="sr-only">Operator</span>
        </div>
      )}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function CopilotPanel() {
  const { state, sendCopilotQuestion } = useAtlas()
  const { latestAnalytics, latestRisk, copilotLoading, copilotError, sseState } = state

  const hasData = latestAnalytics !== null

  // Local message history (user + assistant pairs)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const bottomRef = useRef(null)

  // Auto-scroll to bottom on new message
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, copilotLoading])

  async function handleSubmit(e) {
    e?.preventDefault()
    const question = input.trim()
    if (!question || copilotLoading || !hasData) return

    setInput('')
    // Append user message optimistically
    setMessages((prev) => [...prev, { role: 'user', content: question }])

    try {
      const answer = await sendCopilotQuestion(question)
      setMessages((prev) => [...prev, { role: 'assistant', content: answer }])
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: 'Unable to reach the Copilot at this time. Please try again.',
        },
      ])
    }
  }

  // Badge: shows loading indicator while waiting
  const badge = copilotLoading ? (
    <span className="flex items-center gap-1.5 text-[10px] text-violet-400">
      <span className="inline-block w-2 h-2 border border-violet-500 border-t-transparent rounded-full animate-spin" aria-hidden="true" />
      Thinking…
    </span>
  ) : null

  return (
    <Panel title="Copilot" badge={badge} className="flex flex-col" contentClass="flex flex-col">
      {/* ── Not connected ─────────────────────────────────────────────── */}
      {!hasData && (
        <div className="flex items-center justify-center flex-1 text-slate-600 text-sm p-4">
          {sseState === 'CONFLICT'
            ? 'Another operator is streaming.'
            : 'Start the telemetry stream to activate the Copilot.'}
        </div>
      )}

      {/* ── Conversation area ─────────────────────────────────────────── */}
      {hasData && (
        <>
          {/* Message list */}
          <div
            className="flex-1 overflow-y-auto px-4 py-3 space-y-3 min-h-[8rem]"
            aria-live="polite"
            aria-label="Copilot conversation"
          >
            {messages.length === 0 && (
              <div className="flex flex-col items-center justify-center h-full gap-2 text-center py-8">
                <p className="text-sm text-slate-500">Ask a question about the current mission state.</p>
                <p className="text-[11px] text-slate-600">
                  e.g. "What subsystem is showing anomalies?"
                </p>
                <p className="text-[11px] text-slate-600">
                  "What does the risk level mean for orbital insertion?"
                </p>
              </div>
            )}
            {messages.map((msg, i) => (
              <MessageBubble key={i} role={msg.role} content={msg.content} />
            ))}
            {/* Loading indicator */}
            {copilotLoading && (
              <div className="flex items-center gap-2 text-[11px] text-violet-400">
                <span className="w-4 h-4 rounded-full bg-violet-900 border border-violet-700 flex items-center justify-center shrink-0">
                  <span className="text-[7px] text-violet-300 font-bold">AI</span>
                </span>
                <span className="flex gap-1">
                  <span className="w-1 h-1 rounded-full bg-violet-500 animate-bounce" style={{ animationDelay: '0ms' }} />
                  <span className="w-1 h-1 rounded-full bg-violet-500 animate-bounce" style={{ animationDelay: '150ms' }} />
                  <span className="w-1 h-1 rounded-full bg-violet-500 animate-bounce" style={{ animationDelay: '300ms' }} />
                </span>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* Input area */}
          <div className="border-t border-slate-700 p-3 shrink-0">
            <form
              onSubmit={handleSubmit}
              className="flex items-end gap-2"
              aria-label="Copilot question form"
            >
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    handleSubmit()
                  }
                }}
                placeholder="Ask the Copilot…"
                disabled={copilotLoading || !hasData}
                rows={2}
                className="flex-1 resize-none bg-slate-700 border border-slate-600 rounded px-3 py-2 text-[12px] text-slate-200 placeholder-slate-500 focus:outline-none focus:border-violet-600 disabled:opacity-50 transition-colors leading-relaxed"
                aria-label="Your question"
              />
              <button
                type="submit"
                disabled={copilotLoading || !input.trim() || !hasData}
                className="shrink-0 px-4 py-2 text-[11px] font-semibold bg-violet-800 hover:bg-violet-700 disabled:opacity-40 text-violet-100 rounded transition-colors"
                aria-label="Send question"
              >
                Send
              </button>
            </form>
            <p className="text-[9px] text-slate-600 mt-1.5">
              Responses grounded in current telemetry state · Enter to send, Shift+Enter for newline
            </p>
          </div>
        </>
      )}
    </Panel>
  )
}
