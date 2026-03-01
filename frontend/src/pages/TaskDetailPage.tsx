import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { ArrowLeft, Play, XCircle } from 'lucide-react'
import StatusBadge from '../components/shared/StatusBadge'
import LoadingSpinner from '../components/shared/LoadingSpinner'
import ErrorBanner from '../components/shared/ErrorBanner'
import { getTask, executeTask, cancelTask } from '../api/tasks'
import { formatDate, formatScore, formatDuration } from '../utils/formatters'
import type {
  TaskResponse, TaskExecuteResponse,
  CapabilityClass, ContextTier,
} from '../api/types'

const CAP_CLASSES: CapabilityClass[] = [
  'fast_model', 'coder_model', 'reasoning_model', 'heavy_model', 'planner_model',
]
const CTX_TIERS: ContextTier[] = ['execution', 'hybrid', 'planning']

export default function TaskDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [task, setTask] = useState<TaskResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Execute form
  const [prompt, setPrompt] = useState('')
  const [forceModel, setForceModel] = useState<CapabilityClass | ''>('')
  const [forceTier, setForceTier] = useState<ContextTier | ''>('')
  const [executing, setExecuting] = useState(false)
  const [execResult, setExecResult] = useState<TaskExecuteResponse | null>(null)
  const [execError, setExecError] = useState<string | null>(null)
  const [cancelling, setCancelling] = useState(false)

  useEffect(() => {
    if (!id) return
    getTask(id)
      .then(setTask)
      .catch(e => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false))
  }, [id])

  const handleExecute = async () => {
    if (!id || !prompt.trim()) return
    setExecuting(true)
    setExecError(null)
    setExecResult(null)
    try {
      const res = await executeTask(id, {
        prompt,
        force_model_class: forceModel || undefined,
        force_context_tier: forceTier || undefined,
      })
      setExecResult(res)
      // Refresh task status
      const updated = await getTask(id)
      setTask(updated)
    } catch (e) {
      setExecError(e instanceof Error ? e.message : String(e))
    } finally {
      setExecuting(false)
    }
  }

  const handleCancel = async () => {
    if (!id) return
    setCancelling(true)
    try {
      await cancelTask(id)
      const updated = await getTask(id)
      setTask(updated)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setCancelling(false)
    }
  }

  if (loading) return <LoadingSpinner message="Loading task..." />
  if (error) return <ErrorBanner message={error} />
  if (!task) return <ErrorBanner message="Task not found" />

  return (
    <div className="space-y-6 max-w-4xl">
      <div className="flex items-center gap-3">
        <Link to="/tasks" className="text-gray-400 hover:text-white">
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <h1 className="text-xl font-semibold font-mono">{task.id}</h1>
        <StatusBadge status={task.task_status} />
      </div>

      {/* Task info */}
      <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-4 grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
        <div><p className="text-gray-500 text-xs">Type</p><p className="text-white mt-0.5">{task.task_type}</p></div>
        <div><p className="text-gray-500 text-xs">Project</p><p className="text-white mt-0.5">{task.project_id}</p></div>
        <div><p className="text-gray-500 text-xs">Created</p><p className="text-white mt-0.5">{formatDate(task.created_at)}</p></div>
        <div><p className="text-gray-500 text-xs">Updated</p><p className="text-white mt-0.5">{formatDate(task.updated_at)}</p></div>
        {task.plan_id && <div><p className="text-gray-500 text-xs">Plan</p><p className="text-white mt-0.5 font-mono text-xs">{task.plan_id}</p></div>}
        <div><p className="text-gray-500 text-xs">Signature</p><p className="text-white mt-0.5 font-mono text-xs truncate">{task.signature}</p></div>
      </div>

      {/* Execute form */}
      <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-4 space-y-3">
        <p className="text-sm font-medium text-gray-300">Execute Task</p>
        <textarea
          value={prompt}
          onChange={e => setPrompt(e.target.value)}
          rows={4}
          placeholder="Enter prompt..."
          className="w-full bg-gray-900 border border-gray-600 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500 resize-none"
        />
        <div className="flex flex-wrap gap-3">
          <select
            value={forceModel}
            onChange={e => setForceModel(e.target.value as CapabilityClass | '')}
            className="bg-gray-900 border border-gray-600 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500"
          >
            <option value="">Auto model</option>
            {CAP_CLASSES.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
          <select
            value={forceTier}
            onChange={e => setForceTier(e.target.value as ContextTier | '')}
            className="bg-gray-900 border border-gray-600 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500"
          >
            <option value="">Auto tier</option>
            {CTX_TIERS.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
          <button
            onClick={handleExecute}
            disabled={executing || !prompt.trim()}
            className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 px-3 py-2 rounded-lg text-sm transition-colors"
          >
            <Play className="w-4 h-4" />
            {executing ? 'Running…' : 'Execute'}
          </button>
          {task.task_status === 'running' && (
            <button
              onClick={handleCancel}
              disabled={cancelling}
              className="flex items-center gap-2 bg-red-700 hover:bg-red-600 disabled:opacity-40 px-3 py-2 rounded-lg text-sm transition-colors"
            >
              <XCircle className="w-4 h-4" />
              {cancelling ? 'Cancelling…' : 'Cancel'}
            </button>
          )}
        </div>
        {execError && <ErrorBanner message={execError} />}
      </div>

      {/* Execution result */}
      {execResult && (
        <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-4 space-y-3">
          <p className="text-sm font-medium text-gray-300">Result</p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
            <div>
              <p className="text-gray-500 text-xs">Score</p>
              <p className="text-white mt-0.5 text-lg font-semibold">{formatScore(execResult.score)}</p>
            </div>
            <div>
              <p className="text-gray-500 text-xs">Passed</p>
              <StatusBadge status={String(execResult.passed)} />
            </div>
            <div>
              <p className="text-gray-500 text-xs">Duration</p>
              <p className="text-white mt-0.5">{formatDuration(execResult.duration_ms)}</p>
            </div>
            <div>
              <p className="text-gray-500 text-xs">Retries</p>
              <p className="text-white mt-0.5">{execResult.retry_count}</p>
            </div>
          </div>
          <div>
            <p className="text-gray-500 text-xs mb-1">Routing</p>
            <p className="text-sm text-gray-300">
              {execResult.routing_decision.selected_model} / {execResult.routing_decision.context_tier} ({execResult.routing_decision.context_size.toLocaleString()} tokens)
            </p>
            <p className="text-xs text-gray-500 mt-0.5">{execResult.routing_decision.routing_reason}</p>
          </div>
          <div>
            <p className="text-gray-500 text-xs mb-1">Response</p>
            <pre className="text-xs text-gray-300 bg-gray-900 rounded-lg p-3 overflow-auto max-h-48 whitespace-pre-wrap">
              {execResult.response_text}
            </pre>
          </div>
        </div>
      )}
    </div>
  )
}

