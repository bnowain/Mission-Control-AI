import { useState, useEffect } from 'react'
import { Play } from 'lucide-react'
import DataTable from '../components/shared/DataTable'
import StatusBadge from '../components/shared/StatusBadge'
import LoadingSpinner from '../components/shared/LoadingSpinner'
import ErrorBanner from '../components/shared/ErrorBanner'
import { getRouterStats, selectModel } from '../api/router'
import { formatPercent, formatScore } from '../utils/formatters'
import type { RouterStatsRow, RoutingDecision, TaskType } from '../api/types'

const TASK_TYPES: TaskType[] = [
  'bug_fix', 'refactor_small', 'refactor_large',
  'architecture_design', 'file_edit', 'test_write', 'docs', 'generic',
]

export default function RouterPage() {
  const [rows, setRows] = useState<RouterStatsRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Test form
  const [taskType, setTaskType] = useState<TaskType>('generic')
  const [retryCount, setRetryCount] = useState(0)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<RoutingDecision | null>(null)
  const [testError, setTestError] = useState<string | null>(null)

  useEffect(() => {
    getRouterStats()
      .then(res => setRows(res.rows))
      .catch(e => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false))
  }, [])

  const handleTest = async () => {
    setTesting(true)
    setTestError(null)
    setTestResult(null)
    try {
      const res = await selectModel({ task_type: taskType, retry_count: retryCount })
      setTestResult(res)
    } catch (e) {
      setTestError(e instanceof Error ? e.message : String(e))
    } finally {
      setTesting(false)
    }
  }

  const successRateColor = (rate: number | null) => {
    if (rate == null) return 'text-gray-400'
    if (rate >= 0.8) return 'text-green-400'
    if (rate >= 0.5) return 'text-yellow-400'
    return 'text-red-400'
  }

  const columns = [
    { key: 'model_id', label: 'Model' },
    { key: 'task_type', label: 'Task Type' },
    { key: 'average_score', label: 'Avg Score', render: (r: RouterStatsRow) => <span>{formatScore(r.average_score)}</span> },
    {
      key: 'success_rate', label: 'Success Rate',
      render: (r: RouterStatsRow) => (
        <span className={successRateColor(r.success_rate)}>{formatPercent(r.success_rate)}</span>
      ),
    },
    { key: 'average_retries', label: 'Avg Retries', render: (r: RouterStatsRow) => <span>{r.average_retries?.toFixed(1) ?? '—'}</span> },
    { key: 'sample_size', label: 'Samples' },
  ]

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Router Analytics</h1>

      {/* Stats table */}
      <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-2">
        <p className="text-sm font-medium text-gray-400 uppercase tracking-wide px-0 pt-3 pb-2">Model Performance</p>
        {error && <ErrorBanner message={error} />}
        {loading ? <LoadingSpinner /> : (
          <DataTable
            columns={columns}
            rows={rows as unknown as Record<string, unknown>[]}
            emptyMessage="No router stats yet"
          />
        )}
      </div>

      {/* Test Router */}
      <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-4 space-y-4">
        <p className="text-sm font-medium text-gray-300">Test Router</p>
        <div className="flex flex-wrap gap-3">
          <select
            value={taskType}
            onChange={e => setTaskType(e.target.value as TaskType)}
            className="bg-gray-900 border border-gray-600 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500"
          >
            {TASK_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
          <div className="flex items-center gap-2">
            <label className="text-xs text-gray-400">Retry count:</label>
            <input
              type="number"
              min={0}
              max={5}
              value={retryCount}
              onChange={e => setRetryCount(Number(e.target.value))}
              className="w-16 bg-gray-900 border border-gray-600 rounded-lg px-2 py-2 text-sm outline-none focus:border-blue-500"
            />
          </div>
          <button
            onClick={handleTest}
            disabled={testing}
            className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 px-3 py-2 rounded-lg text-sm transition-colors"
          >
            <Play className="w-4 h-4" />
            {testing ? 'Testing…' : 'Test Router'}
          </button>
        </div>

        {testError && <ErrorBanner message={testError} />}

        {testResult && (
          <div className="bg-gray-900 rounded-xl px-4 py-3 space-y-2 text-sm">
            <p className="text-xs text-gray-400 uppercase tracking-wide mb-2">Routing Decision</p>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              <div><p className="text-gray-500 text-xs">Model</p><p className="text-white mt-0.5">{testResult.selected_model}</p></div>
              <div><p className="text-gray-500 text-xs">Context Tier</p><StatusBadge status={testResult.context_tier} /></div>
              <div><p className="text-gray-500 text-xs">Context Size</p><p className="text-white mt-0.5">{testResult.context_size.toLocaleString()}</p></div>
              <div><p className="text-gray-500 text-xs">Temperature</p><p className="text-white mt-0.5">{testResult.temperature}</p></div>
              <div className="md:col-span-2"><p className="text-gray-500 text-xs">Reason</p><p className="text-white mt-0.5">{testResult.routing_reason}</p></div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
