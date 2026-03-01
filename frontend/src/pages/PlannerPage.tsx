/**
 * Mission Control — Planner Page
 *
 * Interactive streaming planner with two modes:
 *  - Claude: uses `claude -p --verbose` subprocess
 *  - Local:  uses a local reasoning model with <think> block streaming
 *
 * Live events stream via SSE. Cancel via button or ESC key.
 */

import { useEffect, useRef, useState } from 'react'
import { Brain, ChevronDown, ChevronRight, Loader2, Square, Wrench } from 'lucide-react'
import { streamPlan } from '../api/planner'
import type { PlanEvent, PlanDoneEvent } from '../api/types'

type PlanMode = 'claude' | 'local'

// ── Diff line renderer ───────────────────────────────────────────────────────

function DiffLine({ line }: { line: string }) {
  // Header lines: +++ / ---
  if (line.startsWith('+++') || line.startsWith('---')) {
    return (
      <pre className="px-4 leading-5 text-gray-400 bg-gray-800/60 whitespace-pre-wrap">
        {line}
      </pre>
    )
  }
  // Hunk header: @@ -N,N +N,N @@
  if (line.startsWith('@@')) {
    return (
      <pre className="px-4 leading-5 text-blue-400 bg-blue-950/30 whitespace-pre-wrap">
        {line}
      </pre>
    )
  }
  // Added line
  if (line.startsWith('+')) {
    return (
      <pre className="px-4 leading-5 text-green-300 bg-green-950/40 whitespace-pre-wrap">
        {line}
      </pre>
    )
  }
  // Removed line
  if (line.startsWith('-')) {
    return (
      <pre className="px-4 leading-5 text-red-300 bg-red-950/40 whitespace-pre-wrap">
        {line}
      </pre>
    )
  }
  // Context line (unchanged)
  return (
    <pre className="px-4 leading-5 text-gray-500 whitespace-pre-wrap">
      {line}
    </pre>
  )
}

// ── Main page ────────────────────────────────────────────────────────────────

const MODEL_CLASS_OPTIONS = [
  { value: 'reasoning_model', label: 'Reasoning Model' },
  { value: 'planner_model',   label: 'Planner Model' },
  { value: 'coder_model',     label: 'Coder Model' },
  { value: 'heavy_model',     label: 'Heavy Model' },
]

export default function PlannerPage() {
  const [mode, setMode] = useState<PlanMode>('claude')
  const [prompt, setPrompt] = useState('')
  const [modelClass, setModelClass] = useState('reasoning_model')
  const [planning, setPlanning] = useState(false)
  const [events, setEvents] = useState<PlanEvent[]>([])
  const [result, setResult] = useState<PlanDoneEvent | null>(null)
  const [thinkingExpanded, setThinkingExpanded] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const abortControllerRef = useRef<AbortController | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  // ESC key → cancel
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && planning) {
        handleCancel()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [planning])

  // Auto-scroll to bottom when new events arrive
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [events])

  const handleStart = async () => {
    if (!prompt.trim() || planning) return

    setPlanning(true)
    setEvents([])
    setResult(null)
    setError(null)

    const ac = new AbortController()
    abortControllerRef.current = ac

    await streamPlan({
      mode,
      prompt: prompt.trim(),
      modelClass: mode === 'local' ? modelClass : undefined,
      onEvent: (ev) => setEvents(prev => [...prev, ev]),
      onDone: (res) => {
        setResult(res)
        setPlanning(false)
      },
      onError: (msg) => {
        setError(msg)
        setPlanning(false)
      },
      signal: ac.signal,
    })

    // If stream ends without onDone (e.g. abort), clean up
    setPlanning(false)
  }

  const handleCancel = () => {
    abortControllerRef.current?.abort()
    abortControllerRef.current = null
    setPlanning(false)
  }

  // Derived event lists
  const thinkingEvents = events.filter(e => e.event_type === 'thinking')
  const outputEvents = events.filter(e => e.event_type === 'output')
  const toolEvents = events.filter(e => e.event_type === 'tool_use')
  const diffEvents = events.filter(e => e.event_type === 'file_diff')
  const errorEvents = events.filter(e => e.event_type === 'error')

  return (
    <div className="flex flex-col h-full max-w-5xl mx-auto px-4 py-6 gap-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Brain className="w-6 h-6 text-purple-400 shrink-0" />
        <h1 className="text-2xl font-semibold">Planner</h1>
      </div>

      {/* Mode selector + prompt */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 flex flex-col gap-4">
        {/* Mode tabs */}
        <div className="flex gap-2">
          {(['claude', 'local'] as PlanMode[]).map(m => (
            <button
              key={m}
              onClick={() => !planning && setMode(m)}
              disabled={planning}
              className={`px-4 py-1.5 rounded text-sm font-medium transition-colors ${
                mode === m
                  ? 'bg-purple-600 text-white'
                  : 'bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-200'
              } disabled:opacity-50`}
            >
              {m === 'claude' ? 'Claude Code' : 'Local Reasoning'}
            </button>
          ))}
        </div>

        {/* Local model class picker */}
        {mode === 'local' && (
          <div className="flex items-center gap-3">
            <label className="text-sm text-gray-400 shrink-0">Model class:</label>
            <select
              value={modelClass}
              onChange={e => setModelClass(e.target.value)}
              disabled={planning}
              className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-purple-500 disabled:opacity-50"
            >
              {MODEL_CLASS_OPTIONS.map(o => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>
        )}

        {/* Prompt input */}
        <textarea
          value={prompt}
          onChange={e => setPrompt(e.target.value)}
          disabled={planning}
          placeholder={
            mode === 'claude'
              ? 'Describe what you want Claude to plan...'
              : 'Describe what you want the reasoning model to plan...'
          }
          rows={4}
          className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-purple-500 resize-y disabled:opacity-50"
          onKeyDown={e => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleStart()
          }}
        />

        {/* Action buttons */}
        <div className="flex items-center gap-3">
          <button
            onClick={handleStart}
            disabled={planning || !prompt.trim()}
            className="px-5 py-2 bg-purple-600 hover:bg-purple-500 disabled:bg-gray-700 disabled:text-gray-500 text-white rounded text-sm font-medium transition-colors flex items-center gap-2"
          >
            {planning ? <Loader2 className="w-4 h-4 animate-spin" /> : <Brain className="w-4 h-4" />}
            {planning ? 'Planning…' : 'Start Planning'}
          </button>

          {planning && (
            <button
              onClick={handleCancel}
              className="px-4 py-2 bg-red-700 hover:bg-red-600 text-white rounded text-sm font-medium transition-colors flex items-center gap-2"
            >
              <Square className="w-4 h-4" />
              Cancel (ESC)
            </button>
          )}

          {!planning && result && (
            <span className="text-xs text-gray-500">
              Done in {result.duration_ms}ms · {result.model_used}
              {result.cancelled && ' · cancelled'}
            </span>
          )}
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div className="bg-red-950 border border-red-800 text-red-300 text-sm rounded px-4 py-2">
          {error}
        </div>
      )}

      {/* Event stream display */}
      {(events.length > 0 || result) && (
        <div className="flex flex-col gap-3 flex-1 overflow-hidden">

          {/* Tool use badges */}
          {toolEvents.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {toolEvents.map((ev, i) => (
                <span
                  key={i}
                  className="inline-flex items-center gap-1 bg-blue-950 border border-blue-800 text-blue-300 rounded px-2 py-0.5 text-xs"
                >
                  <Wrench className="w-3 h-3" />
                  {ev.content}
                </span>
              ))}
            </div>
          )}

          {/* Thinking section */}
          {thinkingEvents.length > 0 && (
            <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
              <button
                onClick={() => setThinkingExpanded(v => !v)}
                className="w-full flex items-center gap-2 px-4 py-2.5 text-sm text-gray-400 hover:text-gray-200 hover:bg-gray-800/50 transition-colors"
              >
                {thinkingExpanded ? (
                  <ChevronDown className="w-4 h-4 shrink-0" />
                ) : (
                  <ChevronRight className="w-4 h-4 shrink-0" />
                )}
                <span className="font-medium">Thinking</span>
                {planning && thinkingExpanded && (
                  <Loader2 className="w-3.5 h-3.5 animate-spin ml-1 text-purple-400" />
                )}
                <span className="ml-auto text-xs text-gray-600">
                  {thinkingEvents.length} chunk{thinkingEvents.length !== 1 ? 's' : ''}
                </span>
              </button>
              {thinkingExpanded && (
                <div className="border-t border-gray-800 px-4 py-3 font-mono text-xs text-gray-400 whitespace-pre-wrap max-h-64 overflow-y-auto">
                  {thinkingEvents.map(e => e.content).join('')}
                </div>
              )}
            </div>
          )}

          {/* Output section — mix output + diff inline in arrival order */}
          {(outputEvents.length > 0 || diffEvents.length > 0) && (
            <div className="bg-gray-900 border border-gray-800 rounded-lg flex-1 overflow-hidden flex flex-col">
              <div className="px-4 py-2.5 border-b border-gray-800 text-sm text-gray-400 font-medium">
                Output
              </div>
              <div className="py-1 font-mono text-sm overflow-y-auto flex-1">
                {events
                  .filter(e => e.event_type === 'output' || e.event_type === 'file_diff')
                  .map((e, i) => {
                    if (e.event_type === 'file_diff') {
                      return <DiffLine key={i} line={e.content} />
                    }
                    return (
                      <pre key={i} className="px-4 text-gray-200 whitespace-pre-wrap leading-5">
                        {e.content}
                      </pre>
                    )
                  })}
                <div ref={bottomRef} />
              </div>
            </div>
          )}

          {/* Error events */}
          {errorEvents.length > 0 && (
            <div className="bg-red-950 border border-red-800 rounded-lg px-4 py-3 text-xs text-red-300 font-mono whitespace-pre-wrap">
              {errorEvents.map(e => e.content).join('\n')}
            </div>
          )}
        </div>
      )}

      {/* Empty state */}
      {events.length === 0 && !planning && !result && (
        <div className="flex-1 flex flex-col items-center justify-center text-gray-600 gap-2">
          <Brain className="w-12 h-12 opacity-20" />
          <p className="text-sm">Enter a prompt and click Start Planning.</p>
          <p className="text-xs">Use Ctrl+Enter to submit. Press ESC to cancel.</p>
        </div>
      )}
    </div>
  )
}
