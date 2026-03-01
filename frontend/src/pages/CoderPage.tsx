import { useState, useEffect } from 'react'
import {
  Code, Play, Loader2, ChevronDown, ChevronRight, Copy, Check, Zap,
} from 'lucide-react'
import { runModel } from '../api/models'
import type { ModelRunResponse } from '../api/types'

// ── Types ────────────────────────────────────────────────────────────────────

type TaskType =
  | 'bug_fix' | 'file_edit' | 'test_write' | 'refactor_small'
  | 'refactor_large' | 'architecture_design' | 'docs' | 'generic'

type CapabilityClass =
  | 'fast_model' | 'coder_model' | 'reasoning_model' | 'planner_model' | 'heavy_model'

interface TaskConfig {
  capabilityClass: CapabilityClass
  temperature: number
  label: string
}

// ── Static config ─────────────────────────────────────────────────────────────

const TASK_CONFIG: Record<TaskType, TaskConfig> = {
  bug_fix:             { capabilityClass: 'coder_model',     temperature: 0.1, label: 'Bug Fix' },
  file_edit:           { capabilityClass: 'coder_model',     temperature: 0.1, label: 'File Edit' },
  test_write:          { capabilityClass: 'coder_model',     temperature: 0.1, label: 'Test Write' },
  refactor_small:      { capabilityClass: 'coder_model',     temperature: 0.2, label: 'Refactor (Small)' },
  refactor_large:      { capabilityClass: 'reasoning_model', temperature: 0.3, label: 'Refactor (Large)' },
  architecture_design: { capabilityClass: 'reasoning_model', temperature: 0.4, label: 'Architecture Design' },
  docs:                { capabilityClass: 'fast_model',      temperature: 0.4, label: 'Docs' },
  generic:             { capabilityClass: 'coder_model',     temperature: 0.2, label: 'Generic' },
}

const CAPABILITY_LABELS: Record<CapabilityClass, string> = {
  fast_model:      'Fast',
  coder_model:     'Coder',
  reasoning_model: 'Reasoning',
  planner_model:   'Planner (cloud)',
  heavy_model:     'Heavy (70B+)',
}

// ── Code renderer ─────────────────────────────────────────────────────────────

type Segment =
  | { type: 'prose'; content: string }
  | { type: 'code';  lang: string; content: string }

function parseSegments(text: string): Segment[] {
  const segments: Segment[] = []
  const fenceRe = /^```(\w*)\n([\s\S]*?)^```/gm
  let lastIndex = 0
  let match: RegExpExecArray | null

  while ((match = fenceRe.exec(text)) !== null) {
    if (match.index > lastIndex) {
      const prose = text.slice(lastIndex, match.index).trim()
      if (prose) segments.push({ type: 'prose', content: prose })
    }
    segments.push({ type: 'code', lang: match[1] || '', content: match[2] })
    lastIndex = match.index + match[0].length
  }

  const tail = text.slice(lastIndex).trim()
  if (tail) segments.push({ type: 'prose', content: tail })

  return segments
}

function CodeRenderer({ text }: { text: string }) {
  const segments = parseSegments(text)
  if (!segments.length) return null

  return (
    <div className="space-y-3 text-sm text-gray-200">
      {segments.map((seg, i) => {
        if (seg.type === 'prose') {
          return (
            <p key={i} className="whitespace-pre-wrap leading-relaxed text-gray-300">
              {seg.content}
            </p>
          )
        }
        return (
          <div key={i} className="rounded-md overflow-hidden border border-gray-700">
            {seg.lang && (
              <div className="px-3 py-1 bg-gray-800 border-b border-gray-700 text-xs text-blue-400 font-mono">
                {seg.lang}
              </div>
            )}
            <pre className="px-4 py-3 bg-gray-950 overflow-x-auto font-mono text-xs leading-5 text-green-300 whitespace-pre">
              {seg.content}
            </pre>
          </div>
        )
      })}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function CoderPage() {
  // Inputs
  const [taskType, setTaskType]               = useState<TaskType>('bug_fix')
  const [modelOverride, setModelOverride]     = useState<CapabilityClass | ''>('')
  const [temperature, setTemperature]         = useState(0.1)
  const [contextText, setContextText]         = useState('')
  const [prompt, setPrompt]                   = useState('')

  // Request state
  const [loading, setLoading]                 = useState(false)
  const [error, setError]                     = useState<string | null>(null)

  // Result state
  const [result, setResult]                   = useState<ModelRunResponse | null>(null)
  const [thinkingExpanded, setThinkingExpanded] = useState(true)
  const [hasCopied, setHasCopied]             = useState(false)

  // Sync temperature when task type changes
  useEffect(() => {
    setTemperature(TASK_CONFIG[taskType].temperature)
  }, [taskType])

  const effectiveClass: CapabilityClass =
    modelOverride || TASK_CONFIG[taskType].capabilityClass

  // Tokens/sec derived from result
  const tokensPerSec =
    result?.tokens_generated && result?.duration_ms
      ? Math.round((result.tokens_generated / result.duration_ms) * 1000)
      : null

  // ── Handlers ──────────────────────────────────────────────────────────────

  const handleRun = async () => {
    if (!prompt.trim() || loading) return
    setLoading(true)
    setError(null)
    setResult(null)
    setHasCopied(false)

    const userContent = contextText.trim()
      ? `Here is the relevant context:\n\n${contextText.trim()}\n\n---\n\n${prompt.trim()}`
      : prompt.trim()

    try {
      const res = await runModel({
        model_id: effectiveClass,
        messages: [{ role: 'user', content: userContent }],
        temperature,
        max_tokens: 4096,
      })
      setResult(res)
      setThinkingExpanded(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  const handleClear = () => {
    setPrompt('')
    setContextText('')
    setResult(null)
    setError(null)
    setHasCopied(false)
  }

  const handleCopy = async () => {
    if (!result) return
    await navigator.clipboard.writeText(result.response_text)
    setHasCopied(true)
    setTimeout(() => setHasCopied(false), 2000)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault()
      handleRun()
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="flex h-full gap-4 px-4 py-6 max-w-7xl mx-auto overflow-hidden">

      {/* ── LEFT: Input panel ── */}
      <div className="w-80 shrink-0 flex flex-col gap-4">

        <div className="flex items-center gap-3">
          <Code className="w-6 h-6 text-blue-400 shrink-0" />
          <h1 className="text-2xl font-semibold">Coder</h1>
        </div>

        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 flex flex-col gap-4 flex-1 overflow-y-auto">

          {/* Task type */}
          <div>
            <label className="block text-xs text-gray-400 uppercase tracking-wide mb-1">
              Task Type
            </label>
            <select
              value={taskType}
              onChange={e => setTaskType(e.target.value as TaskType)}
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-blue-500"
            >
              {(Object.entries(TASK_CONFIG) as [TaskType, TaskConfig][]).map(([k, v]) => (
                <option key={k} value={k}>{v.label}</option>
              ))}
            </select>
          </div>

          {/* Model class */}
          <div>
            <label className="block text-xs text-gray-400 uppercase tracking-wide mb-1">
              Model Class
            </label>
            <select
              value={modelOverride || effectiveClass}
              onChange={e => setModelOverride(e.target.value as CapabilityClass)}
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-blue-500"
            >
              {(Object.entries(CAPABILITY_LABELS) as [CapabilityClass, string][]).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}{!modelOverride && k === effectiveClass ? ' (auto)' : ''}
                </option>
              ))}
            </select>
          </div>

          {/* Temperature */}
          <div>
            <label className="block text-xs text-gray-400 uppercase tracking-wide mb-1">
              Temperature: <span className="text-gray-200 font-mono">{temperature.toFixed(2)}</span>
            </label>
            <input
              type="range"
              min={0} max={1} step={0.05}
              value={temperature}
              onChange={e => setTemperature(parseFloat(e.target.value))}
              className="w-full accent-blue-500"
            />
            <div className="flex justify-between text-xs text-gray-600 mt-0.5">
              <span>precise</span>
              <span>creative</span>
            </div>
          </div>

          {/* Context */}
          <div>
            <label className="block text-xs text-gray-400 uppercase tracking-wide mb-1">
              Context <span className="text-gray-600 normal-case">(optional)</span>
            </label>
            <textarea
              value={contextText}
              onChange={e => setContextText(e.target.value)}
              rows={4}
              placeholder="Paste relevant code, errors, or context..."
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 placeholder-gray-600 resize-none focus:outline-none focus:border-blue-500 font-mono"
            />
          </div>

          {/* Prompt */}
          <div className="flex flex-col flex-1 min-h-0">
            <label className="block text-xs text-gray-400 uppercase tracking-wide mb-1">
              Prompt <span className="text-gray-600 normal-case">(Ctrl+Enter to run)</span>
            </label>
            <textarea
              value={prompt}
              onChange={e => setPrompt(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={7}
              placeholder="Describe what you want..."
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 placeholder-gray-600 resize-none focus:outline-none focus:border-blue-500 flex-1"
            />
          </div>

          {/* Buttons */}
          <div className="flex gap-2">
            <button
              onClick={handleRun}
              disabled={loading || !prompt.trim()}
              className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed rounded text-sm font-medium transition-colors"
            >
              {loading
                ? <><Loader2 className="w-4 h-4 animate-spin" /> Running…</>
                : <><Play className="w-4 h-4" /> Run</>
              }
            </button>
            <button
              onClick={handleClear}
              disabled={loading}
              className="px-3 py-2 bg-gray-800 hover:bg-gray-700 disabled:opacity-40 rounded text-sm text-gray-400 transition-colors"
            >
              Clear
            </button>
          </div>

        </div>
      </div>

      {/* ── RIGHT: Output panel ── */}
      <div className="flex-1 flex flex-col gap-3 overflow-hidden min-w-0">

        {/* Empty state */}
        {!loading && !result && !error && (
          <div className="flex-1 flex flex-col items-center justify-center text-gray-600 gap-3">
            <Code className="w-12 h-12 opacity-30" />
            <p className="text-sm">Enter a prompt and hit Run</p>
            <p className="text-xs">Ctrl+Enter to submit</p>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="bg-red-950/50 border border-red-800 rounded-lg px-4 py-3 text-sm text-red-300">
            {error}
          </div>
        )}

        {/* Loading */}
        {loading && (
          <div className="flex-1 flex items-center justify-center gap-3 text-gray-500">
            <Loader2 className="w-5 h-5 animate-spin" />
            <span className="text-sm">Waiting for {CAPABILITY_LABELS[effectiveClass]} response…</span>
          </div>
        )}

        {/* Results */}
        {result && !loading && (
          <>
            {/* ── Stats bar ── */}
            <div className="flex items-center gap-4 px-1 text-xs text-gray-500 flex-wrap">
              <span className="font-mono text-gray-400">{result.model_id}</span>

              {/* Tokens/sec — prominent with icon */}
              {tokensPerSec !== null && (
                <span className="flex items-center gap-1 text-yellow-400 font-semibold">
                  <Zap className="w-3.5 h-3.5" />
                  {tokensPerSec} tok/s
                </span>
              )}

              {result.duration_ms != null && (
                <span>{(result.duration_ms / 1000).toFixed(1)}s</span>
              )}
              {result.tokens_in != null && (
                <span>{result.tokens_in.toLocaleString()} in</span>
              )}
              {result.tokens_generated != null && (
                <span>{result.tokens_generated.toLocaleString()} out</span>
              )}

              {/* Copy button */}
              <button
                onClick={handleCopy}
                className="ml-auto flex items-center gap-1.5 px-2 py-1 rounded bg-gray-800 hover:bg-gray-700 text-gray-400 hover:text-gray-200 transition-colors"
              >
                {hasCopied
                  ? <><Check className="w-3.5 h-3.5 text-green-400" /> Copied</>
                  : <><Copy className="w-3.5 h-3.5" /> Copy</>
                }
              </button>
            </div>

            {/* ── Thinking block ── */}
            {result.thinking_text && (
              <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden shrink-0">
                <button
                  onClick={() => setThinkingExpanded(v => !v)}
                  className="w-full flex items-center gap-2 px-4 py-2.5 text-sm text-gray-400 hover:text-gray-200 transition-colors"
                >
                  {thinkingExpanded
                    ? <ChevronDown className="w-4 h-4 shrink-0" />
                    : <ChevronRight className="w-4 h-4 shrink-0" />
                  }
                  <span className="font-medium">Thinking</span>
                  <span className="text-xs text-gray-600 ml-1">
                    ({result.thinking_text.length.toLocaleString()} chars)
                  </span>
                </button>
                {thinkingExpanded && (
                  <div className="border-t border-gray-800 px-4 py-3 font-mono text-xs text-gray-400 whitespace-pre-wrap max-h-48 overflow-y-auto">
                    {result.thinking_text}
                  </div>
                )}
              </div>
            )}

            {/* ── Response ── */}
            <div className="bg-gray-900 border border-gray-800 rounded-lg flex-1 overflow-hidden flex flex-col min-h-0">
              <div className="px-4 py-2.5 border-b border-gray-800 text-sm text-gray-400 font-medium shrink-0">
                Response
              </div>
              <div className="flex-1 overflow-y-auto p-4">
                <CodeRenderer text={result.response_text} />
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
