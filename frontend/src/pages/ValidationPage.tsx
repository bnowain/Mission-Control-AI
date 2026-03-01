import { useState } from 'react'
import { Play, CheckCircle, XCircle } from 'lucide-react'
import ErrorBanner from '../components/shared/ErrorBanner'
import { apiPost } from '../api/client'
import type { GradingResult, TaskType } from '../api/types'

const TASK_TYPES: TaskType[] = [
  'bug_fix', 'refactor_small', 'refactor_large',
  'architecture_design', 'file_edit', 'test_write', 'docs', 'generic',
]

function PassIcon({ passed }: { passed: boolean | null | undefined }) {
  if (passed == null) return <span className="w-5 h-5 rounded-full bg-gray-700 inline-block" />
  return passed
    ? <CheckCircle className="w-5 h-5 text-green-400 inline" />
    : <XCircle className="w-5 h-5 text-red-400 inline" />
}

export default function ValidationPage() {
  const [responseText, setResponseText] = useState('')
  const [taskType, setTaskType] = useState<TaskType>('generic')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<GradingResult | null>(null)

  const handleValidate = async () => {
    if (!responseText.trim()) return
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const res = await apiPost<GradingResult>('/validate', {
        response_text: responseText,
        task_type: taskType,
      })
      setResult(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <h1 className="text-2xl font-semibold">Validation</h1>
      <p className="text-sm text-gray-400">
        Run deterministic validators (compile, tests, lint, runtime) on a model response.
      </p>

      <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-4 space-y-4">
        <div>
          <label className="text-xs text-gray-400 uppercase tracking-wide block mb-1">Task Type</label>
          <select
            value={taskType}
            onChange={e => setTaskType(e.target.value as TaskType)}
            className="bg-gray-900 border border-gray-600 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500"
          >
            {TASK_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>

        <div>
          <label className="text-xs text-gray-400 uppercase tracking-wide block mb-1">Response Text</label>
          <textarea
            value={responseText}
            onChange={e => setResponseText(e.target.value)}
            rows={8}
            placeholder="Paste the model's response to validate..."
            className="w-full bg-gray-900 border border-gray-600 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500 resize-none"
          />
        </div>

        <button
          onClick={handleValidate}
          disabled={loading || !responseText.trim()}
          className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 px-4 py-2 rounded-lg text-sm transition-colors"
        >
          <Play className="w-4 h-4" />
          {loading ? 'Running Validators…' : 'Run Validators'}
        </button>

        {error && <ErrorBanner message={error} />}
      </div>

      {result && (
        <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-4 space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium text-gray-300">Validation Result</p>
            <div className="flex items-center gap-2">
              <span className="text-2xl font-bold text-white">{result.score.toFixed(1)}</span>
              <PassIcon passed={result.passed} />
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="flex flex-col items-center gap-1 bg-gray-900 rounded-xl p-3">
              <PassIcon passed={result.compile_success} />
              <p className="text-xs text-gray-400 mt-1">Compile</p>
            </div>
            <div className="flex flex-col items-center gap-1 bg-gray-900 rounded-xl p-3">
              <PassIcon passed={result.tests_passed} />
              <p className="text-xs text-gray-400 mt-1">Tests</p>
            </div>
            <div className="flex flex-col items-center gap-1 bg-gray-900 rounded-xl p-3">
              <PassIcon passed={result.lint_passed} />
              <p className="text-xs text-gray-400 mt-1">Lint</p>
            </div>
            <div className="flex flex-col items-center gap-1 bg-gray-900 rounded-xl p-3">
              <PassIcon passed={result.runtime_success} />
              <p className="text-xs text-gray-400 mt-1">Runtime</p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 text-sm">
            <div><p className="text-gray-500 text-xs">Retries</p><p className="text-white mt-0.5">{result.retry_count}</p></div>
            <div><p className="text-gray-500 text-xs">Human Flag</p><p className="text-white mt-0.5">{String(result.human_flag)}</p></div>
          </div>

          {Object.keys(result.grade_components).length > 0 && (
            <div>
              <p className="text-xs text-gray-400 uppercase tracking-wide mb-2">Grade Components</p>
              <div className="space-y-1">
                {Object.entries(result.grade_components).map(([k, v]) => (
                  <div key={k} className="flex items-center justify-between text-xs">
                    <span className="text-gray-400">{k}</span>
                    <span className="text-white">{v.toFixed(1)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
