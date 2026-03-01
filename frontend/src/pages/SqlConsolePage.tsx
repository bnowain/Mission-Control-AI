import { useState, useEffect } from 'react'
import { Play, Shield, ChevronRight } from 'lucide-react'
import DataTable from '../components/shared/DataTable'
import ErrorBanner from '../components/shared/ErrorBanner'
import { executeQuery } from '../api/sql'
import type { SqlQueryResponse } from '../api/types'

const QUICK_QUERIES = [
  { label: 'Recent tasks', sql: 'SELECT id, project_id, task_type, task_status, created_at FROM tasks ORDER BY created_at DESC LIMIT 20' },
  { label: 'Recent runs', sql: 'SELECT id, task_id, model_id, score, passed, duration_ms, created_at FROM execution_logs ORDER BY created_at DESC LIMIT 20' },
  { label: 'Codex entries', sql: 'SELECT id, category, root_cause, confidence_score, verified FROM codex_master ORDER BY confidence_score DESC LIMIT 20' },
  { label: 'Active jobs', sql: "SELECT id, job_type, job_status, priority, retry_count FROM jobs WHERE job_status IN ('QUEUED','RUNNING') ORDER BY priority ASC LIMIT 20" },
  { label: 'Tables', sql: "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name" },
]

export default function SqlConsolePage() {
  const [sql, setSql] = useState(QUICK_QUERIES[0]!.sql)
  const [safeMode, setSafeMode] = useState(true)
  const [result, setResult] = useState<SqlQueryResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  // Schema browser
  const [tables, setTables] = useState<string[]>([])
  const [selectedTable, setSelectedTable] = useState<string | null>(null)
  const [columns, setColumns] = useState<string[]>([])

  useEffect(() => {
    executeQuery("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
      .then(res => setTables(res.rows.map(r => String(r[0]))))
      .catch(() => setTables([]))
  }, [])

  const loadColumns = async (table: string) => {
    setSelectedTable(table)
    try {
      const res = await executeQuery(`PRAGMA table_info(${table})`)
      setColumns(res.rows.map(r => String(r[1])))
    } catch {
      setColumns([])
    }
  }

  const run = async () => {
    if (!sql.trim()) return
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const res = await executeQuery(sql, [], !safeMode)
      setResult(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  const resultColumns = result?.columns.map(c => ({ key: c, label: c })) ?? []
  const resultRows = result?.rows.map(r => {
    const obj: Record<string, unknown> = {}
    result.columns.forEach((c, i) => { obj[c] = r[i] })
    return obj
  }) ?? []

  return (
    <div className="space-y-4 h-full flex flex-col">
      <h1 className="text-2xl font-semibold">SQL Console</h1>

      <div className="flex-1 flex gap-4 min-h-0">
        {/* Schema browser */}
        <div className="w-48 shrink-0 bg-gray-800 border border-gray-700 rounded-xl p-3 overflow-y-auto">
          <p className="text-xs text-gray-400 uppercase tracking-wide mb-2">Tables</p>
          <div className="space-y-0.5">
            {tables.map(t => (
              <div key={t}>
                <button
                  onClick={() => void loadColumns(t)}
                  className={`w-full flex items-center gap-1 px-2 py-1 rounded text-xs text-left transition-colors ${
                    selectedTable === t ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-gray-200 hover:bg-gray-700/50'
                  }`}
                >
                  <ChevronRight className="w-3 h-3 shrink-0" />
                  {t}
                </button>
                {selectedTable === t && columns.length > 0 && (
                  <div className="ml-4 mt-0.5 space-y-0.5">
                    {columns.map(c => (
                      <p key={c} className="text-xs text-gray-500 px-2 py-0.5">{c}</p>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Editor + results */}
        <div className="flex-1 flex flex-col gap-3 min-w-0">
          {/* Quick queries */}
          <div className="flex flex-wrap gap-2">
            {QUICK_QUERIES.map(q => (
              <button
                key={q.label}
                onClick={() => setSql(q.sql)}
                className="text-xs bg-gray-800 hover:bg-gray-700 border border-gray-600 px-2 py-1 rounded transition-colors"
              >
                {q.label}
              </button>
            ))}
          </div>

          {/* SQL editor */}
          <textarea
            value={sql}
            onChange={e => setSql(e.target.value)}
            rows={6}
            spellCheck={false}
            className="font-mono text-sm w-full bg-gray-900 border border-gray-600 rounded-lg px-3 py-2 outline-none focus:border-blue-500 resize-none text-green-300"
          />

          {/* Controls */}
          <div className="flex items-center gap-3">
            <button
              onClick={run}
              disabled={loading || !sql.trim()}
              className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 px-3 py-1.5 rounded-lg text-sm transition-colors"
            >
              <Play className="w-4 h-4" />
              {loading ? 'Running…' : 'Execute'}
            </button>
            <label className="flex items-center gap-2 text-sm text-gray-400 cursor-pointer">
              <Shield className={`w-4 h-4 ${safeMode ? 'text-green-400' : 'text-yellow-400'}`} />
              <input
                type="checkbox"
                checked={safeMode}
                onChange={e => setSafeMode(e.target.checked)}
                className="rounded"
              />
              Safe mode (read-only)
            </label>
            {result && (
              <span className="text-xs text-gray-500">{result.row_count} row{result.row_count !== 1 ? 's' : ''}</span>
            )}
          </div>

          {error && <ErrorBanner message={error} />}

          {/* Results */}
          {result && (
            <div className="flex-1 overflow-auto bg-gray-800 border border-gray-700 rounded-xl px-4 py-2">
              <DataTable columns={resultColumns} rows={resultRows} emptyMessage="Query returned 0 rows" />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
