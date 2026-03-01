import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  ArrowLeft, Play, XCircle, ChevronDown, ChevronRight,
  Zap, CheckCircle, XCircle as XIcon, RotateCcw, Brain,
} from 'lucide-react'
import StatusBadge from '../components/shared/StatusBadge'
import LoadingSpinner from '../components/shared/LoadingSpinner'
import ErrorBanner from '../components/shared/ErrorBanner'
import { getTask, cancelTask, streamTaskExecution } from '../api/tasks'
import { formatDate, formatDuration } from '../utils/formatters'
import type {
  TaskResponse, TaskDoneEvent, TaskStreamEvent,
  CapabilityClass, ContextTier,
} from '../api/types'

// ── Code renderer (reused from CoderPage) ──────────────────────────────────

const FENCE_RE = /^```(\w*)\n([\s\S]*?)```$/gm

function CodeRenderer({ text }: { text: string }) {
  const [copied, setCopied] = useState<string | null>(null)
  const parts: { type: 'prose' | 'code'; lang: string; content: string }[] = []
  let last = 0
  let m: RegExpExecArray | null
  FENCE_RE.lastIndex = 0
  while ((m = FENCE_RE.exec(text)) !== null) {
    if (m.index > last) parts.push({ type: 'prose', lang: '', content: text.slice(last, m.index) })
    parts.push({ type: 'code', lang: m[1] || 'text', content: m[2] })
    last = m.index + m[0].length
  }
  if (last < text.length) parts.push({ type: 'prose', lang: '', content: text.slice(last) })
  if (parts.length === 0) parts.push({ type: 'prose', lang: '', content: text })

  const copy = (idx: string, content: string) => {
    navigator.clipboard.writeText(content).then(() => {
      setCopied(idx)
      setTimeout(() => setCopied(null), 2000)
    })
  }

  return (
    <div className="space-y-2 text-sm">
      {parts.map((p, i) => {
        if (p.type === 'prose') {
          return p.content.trim()
            ? <p key={i} className="text-gray-300 leading-relaxed whitespace-pre-wrap">{p.content.trim()}</p>
            : null
        }
        const key = String(i)
        return (
          <div key={i} className="rounded-lg overflow-hidden border border-gray-700">
            <div className="flex items-center justify-between bg-gray-900 px-3 py-1.5">
              <span className="text-xs text-green-400 font-mono">{p.lang}</span>
              <button
                onClick={() => copy(key, p.content)}
                className="text-xs text-gray-400 hover:text-white transition-colors"
              >
                {copied === key ? 'copied!' : 'copy'}
              </button>
            </div>
            <pre className="bg-gray-950 px-3 py-3 overflow-x-auto text-xs text-gray-200 leading-relaxed">
              {p.content}
            </pre>
          </div>
        )
      })}
    </div>
  )
}

// ── Validator badge ─────────────────────────────────────────────────────────

function ValidatorBadge({ label, passed }: { label: string; passed: boolean | null }) {
  if (passed === null) return null
  return (
    <div className={`flex items-center gap-1.5 text-xs px-2 py-1 rounded-full ${
      passed ? 'bg-green-900/40 text-green-400' : 'bg-red-900/40 text-red-400'
    }`}>
      {passed ? <CheckCircle className="w-3 h-3" /> : <XIcon className="w-3 h-3" />}
      {label}
    </div>
  )
}

// ── Event timeline item ─────────────────────────────────────────────────────

function EventItem({ event }: { event: TaskStreamEvent }) {
  if (event.event_type === 'loop_start') {
    return (
      <div className="flex items-center gap-2 text-xs text-gray-400 py-1">
        <RotateCcw className="w-3 h-3 text-blue-400 flex-shrink-0" />
        <span>Loop {event.loop} started{event.retry_count ? ` (retry ${event.retry_count})` : ''}</span>
      </div>
    )
  }
  if (event.event_type === 'model_response') {
    return (
      <div className="flex items-center gap-2 text-xs text-gray-300 py-1">
        <CheckCircle className="w-3 h-3 text-green-400 flex-shrink-0" />
        <span>
          <span className="text-white font-mono">{event.model}</span>
          {' '}responded
          {event.tokens_per_second != null && (
            <span className="ml-2 text-yellow-400 font-semibold">
              <Zap className="w-3 h-3 inline mb-0.5" /> {Math.round(event.tokens_per_second)} tok/s
            </span>
          )}
          {event.tokens_generated != null && (
            <span className="ml-1 text-gray-500">({event.tokens_generated} tokens)</span>
          )}
        </span>
      </div>
    )
  }
  if (event.event_type === 'grading') {
    return (
      <div className="flex items-center gap-2 text-xs py-1">
        {event.passed
          ? <CheckCircle className="w-3 h-3 text-green-400 flex-shrink-0" />
          : <XIcon className="w-3 h-3 text-red-400 flex-shrink-0" />}
        <span className={event.passed ? 'text-green-400' : 'text-red-400'}>
          Score {event.score?.toFixed(0)}/100 — {event.passed ? 'passed' : 'failed'}
        </span>
      </div>
    )
  }
  return null
}

// ── Constants ───────────────────────────────────────────────────────────────

const CAP_CLASSES: CapabilityClass[] = [
  'fast_model', 'coder_model', 'reasoning_model', 'heavy_model', 'planner_model',
]
const CTX_TIERS: ContextTier[] = ['execution', 'hybrid', 'planning']

// ── Main page ───────────────────────────────────────────────────────────────

export default function TaskDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [task, setTask] = useState<TaskResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Execute form
  const [prompt, setPrompt] = useState('')
  const [forceModel, setForceModel] = useState<CapabilityClass | ''>('')
  const [forceTier, setForceTier] = useState<ContextTier | ''>('')

  // Streaming state
  const [executing, setExecuting] = useState(false)
  const [events, setEvents] = useState<TaskStreamEvent[]>([])
  const [doneResult, setDoneResult] = useState<TaskDoneEvent | null>(null)
  const [execError, setExecError] = useState<string | null>(null)
  const [thinkingOpen, setThinkingOpen] = useState(false)

  const abortRef = useRef<AbortController | null>(null)
  const timelineRef = useRef<HTMLDivElement>(null)

  // Cancel on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && abortRef.current) abortRef.current.abort()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  // Auto-scroll timeline
  useEffect(() => {
    if (timelineRef.current) {
      timelineRef.current.scrollTop = timelineRef.current.scrollHeight
    }
  }, [events])

  useEffect(() => {
    if (!id) return
    getTask(id)
      .then(setTask)
      .catch(e => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false))
  }, [id])

  const handleExecute = useCallback(async () => {
    if (!id || !prompt.trim() || executing) return
    setExecuting(true)
    setEvents([])
    setDoneResult(null)
    setExecError(null)
    setThinkingOpen(false)

    const ac = new AbortController()
    abortRef.current = ac

    await streamTaskExecution(id, {
      prompt,
      force_model_class: forceModel || undefined,
      force_context_tier: forceTier || undefined,
      onEvent: (ev) => setEvents(prev => [...prev, ev]),
      onDone: (result) => {
        setDoneResult(result)
        // Refresh task status
        if (id) getTask(id).then(setTask).catch(() => null)
      },
      onError: (msg) => setExecError(msg),
      signal: ac.signal,
    })

    setExecuting(false)
    abortRef.current = null
  }, [id, prompt, forceModel, forceTier, executing])

  const handleCancel = async () => {
    abortRef.current?.abort()
    if (id) {
      try {
        await cancelTask(id)
        const updated = await getTask(id)
        setTask(updated)
      } catch { /* ignore */ }
    }
    setExecuting(false)
  }

  if (loading) return <LoadingSpinner message="Loading task..." />
  if (error) return <ErrorBanner message={error} />
  if (!task) return <ErrorBanner message="Task not found" />

  return (
    <div className="space-y-5 max-w-4xl">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link to="/tasks" className="text-gray-400 hover:text-white">
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <h1 className="text-xl font-semibold font-mono truncate">{task.id}</h1>
        <StatusBadge status={task.task_status} />
      </div>

      {/* Task info */}
      <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-4 grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
        <div><p className="text-gray-500 text-xs">Type</p><p className="text-white mt-0.5">{task.task_type}</p></div>
        <div><p className="text-gray-500 text-xs">Project</p><p className="text-white mt-0.5">{task.project_id}</p></div>
        <div><p className="text-gray-500 text-xs">Created</p><p className="text-white mt-0.5">{formatDate(task.created_at)}</p></div>
        <div><p className="text-gray-500 text-xs">Updated</p><p className="text-white mt-0.5">{formatDate(task.updated_at)}</p></div>
        <div className="col-span-2 md:col-span-1">
          <p className="text-gray-500 text-xs">Signature</p>
          <p className="text-white mt-0.5 font-mono text-xs truncate">{task.signature}</p>
        </div>
      </div>

      {/* Execute form */}
      <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-4 space-y-3">
        <p className="text-sm font-medium text-gray-300">Execute Task</p>
        <textarea
          value={prompt}
          onChange={e => setPrompt(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && e.ctrlKey) handleExecute() }}
          rows={4}
          placeholder="Enter prompt... (Ctrl+Enter to run)"
          disabled={executing}
          className="w-full bg-gray-900 border border-gray-600 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500 resize-none disabled:opacity-50"
        />
        <div className="flex flex-wrap gap-3 items-center">
          <select
            value={forceModel}
            onChange={e => setForceModel(e.target.value as CapabilityClass | '')}
            disabled={executing}
            className="bg-gray-900 border border-gray-600 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500 disabled:opacity-50"
          >
            <option value="">Auto model</option>
            {CAP_CLASSES.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
          <select
            value={forceTier}
            onChange={e => setForceTier(e.target.value as ContextTier | '')}
            disabled={executing}
            className="bg-gray-900 border border-gray-600 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500 disabled:opacity-50"
          >
            <option value="">Auto tier</option>
            {CTX_TIERS.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
          <button
            onClick={handleExecute}
            disabled={executing || !prompt.trim()}
            className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 px-4 py-2 rounded-lg text-sm transition-colors"
          >
            <Play className="w-4 h-4" />
            {executing ? 'Running…' : 'Execute'}
          </button>
          {executing && (
            <button
              onClick={handleCancel}
              className="flex items-center gap-2 bg-red-700 hover:bg-red-600 px-3 py-2 rounded-lg text-sm transition-colors"
            >
              <XCircle className="w-4 h-4" />
              Cancel
            </button>
          )}
          {executing && (
            <span className="text-xs text-gray-400 ml-1">ESC to cancel</span>
          )}
        </div>
        {execError && <ErrorBanner message={execError} />}
      </div>

      {/* Live event timeline */}
      {(executing || events.length > 0) && (
        <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-4 space-y-2">
          <div className="flex items-center gap-2">
            <p className="text-sm font-medium text-gray-300">Execution Progress</p>
            {executing && (
              <span className="inline-flex items-center gap-1.5 text-xs text-blue-400">
                <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-pulse" />
                Running
              </span>
            )}
          </div>
          <div
            ref={timelineRef}
            className="space-y-0.5 max-h-40 overflow-y-auto pr-1"
          >
            {events.map((ev, i) => <EventItem key={i} event={ev} />)}
            {executing && events.length === 0 && (
              <p className="text-xs text-gray-500 animate-pulse">Preparing execution…</p>
            )}
          </div>
        </div>
      )}

      {/* Result */}
      {doneResult && (
        <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-4 space-y-4">
          <p className="text-sm font-medium text-gray-300">Result</p>

          {/* Score + stats row */}
          <div className="flex flex-wrap items-center gap-4">
            <div className="text-center">
              <p className="text-3xl font-bold text-white">{doneResult.score?.toFixed(0) ?? '—'}</p>
              <p className="text-xs text-gray-500 mt-0.5">/ 100</p>
            </div>
            <div className="flex-1 grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
              <div>
                <p className="text-gray-500 text-xs">Status</p>
                <StatusBadge status={String(doneResult.passed ? 'passed' : 'failed')} />
              </div>
              <div>
                <p className="text-gray-500 text-xs">Duration</p>
                <p className="text-white mt-0.5">{formatDuration(doneResult.duration_ms)}</p>
              </div>
              <div>
                <p className="text-gray-500 text-xs">Loops</p>
                <p className="text-white mt-0.5">{doneResult.loop_count}</p>
              </div>
              {doneResult.tokens_per_second != null && (
                <div>
                  <p className="text-gray-500 text-xs">Speed</p>
                  <p className="text-yellow-400 font-semibold mt-0.5 flex items-center gap-1">
                    <Zap className="w-3.5 h-3.5" />
                    {Math.round(doneResult.tokens_per_second)} tok/s
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* Validator breakdown */}
          <div>
            <p className="text-gray-500 text-xs mb-2">Validators</p>
            <div className="flex flex-wrap gap-2">
              <ValidatorBadge label="Compile" passed={doneResult.compile_success} />
              <ValidatorBadge label="Tests" passed={doneResult.tests_passed} />
              <ValidatorBadge label="Lint" passed={doneResult.lint_passed} />
              <ValidatorBadge label="Runtime" passed={doneResult.runtime_success} />
            </div>
          </div>

          {/* Routing info */}
          <div>
            <p className="text-gray-500 text-xs mb-1">Routing</p>
            <p className="text-sm text-gray-300 font-mono">{doneResult.model}</p>
            <p className="text-xs text-gray-500 mt-0.5">
              {doneResult.tier} tier · {doneResult.context_size?.toLocaleString()} ctx tokens · {doneResult.routing_reason}
            </p>
          </div>

          {/* Thinking */}
          {doneResult.thinking_text && (
            <div>
              <button
                onClick={() => setThinkingOpen(o => !o)}
                className="flex items-center gap-2 text-xs text-purple-400 hover:text-purple-300 transition-colors"
              >
                <Brain className="w-3.5 h-3.5" />
                Chain of thought
                {thinkingOpen
                  ? <ChevronDown className="w-3.5 h-3.5" />
                  : <ChevronRight className="w-3.5 h-3.5" />}
              </button>
              {thinkingOpen && (
                <pre className="mt-2 text-xs text-purple-300 bg-gray-900 rounded-lg p-3 overflow-auto max-h-48 whitespace-pre-wrap">
                  {doneResult.thinking_text}
                </pre>
              )}
            </div>
          )}

          {/* Response */}
          <div>
            <p className="text-gray-500 text-xs mb-2">Response</p>
            <div className="bg-gray-900 rounded-lg p-4">
              <CodeRenderer text={doneResult.response_text} />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
