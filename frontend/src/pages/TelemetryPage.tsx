import { useState, useEffect, useCallback } from 'react'
import { Activity, Cpu, BarChart3, Server } from 'lucide-react'
import DataTable from '../components/shared/DataTable'
import Pagination from '../components/shared/Pagination'
import StatCard from '../components/shared/StatCard'
import StatusBadge from '../components/shared/StatusBadge'
import LoadingSpinner from '../components/shared/LoadingSpinner'
import ErrorBanner from '../components/shared/ErrorBanner'
import { getRuns, getModels, getPerformance, getHardware } from '../api/telemetry'
import { formatDate, formatScore, formatDuration, formatPercent } from '../utils/formatters'
import type { TelemetryModelStats } from '../api/types'

type Tab = 'runs' | 'models' | 'performance' | 'hardware'

const LIMIT = 50

export default function TelemetryPage() {
  const [tab, setTab] = useState<Tab>('runs')

  // Runs
  const [runs, setRuns] = useState<Record<string, unknown>[]>([])
  const [runsTotal, setRunsTotal] = useState(0)
  const [runsOffset, setRunsOffset] = useState(0)
  const [runsLoading, setRunsLoading] = useState(false)
  const [runsError, setRunsError] = useState<string | null>(null)
  const [filterTaskId, setFilterTaskId] = useState('')
  const [filterModelId, setFilterModelId] = useState('')

  // Models
  const [models, setModels] = useState<TelemetryModelStats[]>([])
  const [modelsLoading, setModelsLoading] = useState(false)
  const [modelsError, setModelsError] = useState<string | null>(null)

  // Performance
  const [perf, setPerf] = useState<{ total_runs: number; total_tasks: number; overall_pass_rate: number | null; average_score: number | null; average_duration_ms: number | null } | null>(null)
  const [perfLoading, setPerfLoading] = useState(false)
  const [perfError, setPerfError] = useState<string | null>(null)

  // Hardware
  const [hardware, setHardware] = useState<Record<string, unknown>[]>([])
  const [hwLoading, setHwLoading] = useState(false)
  const [hwError, setHwError] = useState<string | null>(null)

  const loadRuns = useCallback(async () => {
    setRunsLoading(true)
    setRunsError(null)
    try {
      const res = await getRuns(LIMIT, runsOffset, filterTaskId || undefined, filterModelId || undefined)
      setRuns(res.runs)
      setRunsTotal(res.total)
    } catch (e) {
      setRunsError(e instanceof Error ? e.message : String(e))
    } finally {
      setRunsLoading(false)
    }
  }, [runsOffset, filterTaskId, filterModelId])

  useEffect(() => {
    if (tab === 'runs') void loadRuns()
  }, [tab, loadRuns])

  useEffect(() => {
    if (tab !== 'models') return
    setModelsLoading(true)
    getModels()
      .then(res => setModels(res.models))
      .catch(e => setModelsError(e instanceof Error ? e.message : String(e)))
      .finally(() => setModelsLoading(false))
  }, [tab])

  useEffect(() => {
    if (tab !== 'performance') return
    setPerfLoading(true)
    getPerformance()
      .then(setPerf)
      .catch(e => setPerfError(e instanceof Error ? e.message : String(e)))
      .finally(() => setPerfLoading(false))
  }, [tab])

  useEffect(() => {
    if (tab !== 'hardware') return
    setHwLoading(true)
    getHardware()
      .then(res => setHardware(res.profiles))
      .catch(e => setHwError(e instanceof Error ? e.message : String(e)))
      .finally(() => setHwLoading(false))
  }, [tab])

  const runColumns = [
    { key: 'id', label: 'Run ID', render: (r: Record<string, unknown>) => <span className="font-mono text-xs">{String(r['id'] ?? '').slice(0, 16)}…</span> },
    { key: 'model_id', label: 'Model' },
    { key: 'score', label: 'Score', render: (r: Record<string, unknown>) => <span>{formatScore(r['score'] as number | null)}</span> },
    { key: 'passed', label: 'Passed', render: (r: Record<string, unknown>) => <StatusBadge status={String(r['passed'] ?? false)} /> },
    { key: 'duration_ms', label: 'Duration', render: (r: Record<string, unknown>) => <span>{formatDuration(r['duration_ms'] as number | null)}</span> },
    { key: 'created_at', label: 'When', render: (r: Record<string, unknown>) => <span className="text-xs">{formatDate(r['created_at'] as string)}</span> },
  ]

  const modelColumns = [
    { key: 'model_id', label: 'Model' },
    { key: 'run_count', label: 'Runs' },
    { key: 'average_score', label: 'Avg Score', render: (r: TelemetryModelStats) => <span>{formatScore(r.average_score)}</span> },
    { key: 'pass_rate', label: 'Pass Rate', render: (r: TelemetryModelStats) => <span>{formatPercent(r.pass_rate)}</span> },
    { key: 'average_duration_ms', label: 'Avg Duration', render: (r: TelemetryModelStats) => <span>{formatDuration(r.average_duration_ms)}</span> },
  ]

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Telemetry</h1>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-700">
        {([['runs', 'Runs', Activity], ['models', 'Models', Cpu], ['performance', 'Performance', BarChart3], ['hardware', 'Hardware', Server]] as const).map(([t, label, Icon]) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`flex items-center gap-2 px-4 py-2 text-sm transition-colors border-b-2 -mb-px ${
              tab === t ? 'border-blue-500 text-blue-400' : 'border-transparent text-gray-400 hover:text-gray-200'
            }`}
          >
            <Icon className="w-4 h-4" />
            {label}
          </button>
        ))}
      </div>

      {tab === 'runs' && (
        <div className="space-y-3">
          <div className="flex gap-3">
            <input
              value={filterTaskId}
              onChange={e => { setFilterTaskId(e.target.value); setRunsOffset(0) }}
              placeholder="Filter by task ID..."
              className="bg-gray-900 border border-gray-600 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500"
            />
            <input
              value={filterModelId}
              onChange={e => { setFilterModelId(e.target.value); setRunsOffset(0) }}
              placeholder="Filter by model ID..."
              className="bg-gray-900 border border-gray-600 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500"
            />
          </div>
          {runsError && <ErrorBanner message={runsError} />}
          <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-2">
            {runsLoading ? <LoadingSpinner /> : (
              <>
                <DataTable columns={runColumns} rows={runs} emptyMessage="No telemetry runs" />
                <Pagination offset={runsOffset} limit={LIMIT} total={runsTotal}
                  onNext={() => setRunsOffset(o => o + LIMIT)}
                  onPrev={() => setRunsOffset(o => Math.max(0, o - LIMIT))} />
              </>
            )}
          </div>
        </div>
      )}

      {tab === 'models' && (
        <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-2">
          {modelsError && <ErrorBanner message={modelsError} />}
          {modelsLoading ? <LoadingSpinner /> : (
            <DataTable
              columns={modelColumns}
              rows={models as unknown as Record<string, unknown>[]}
              emptyMessage="No model stats" />
          )}
        </div>
      )}

      {tab === 'performance' && (
        <div>
          {perfError && <ErrorBanner message={perfError} />}
          {perfLoading && <LoadingSpinner />}
          {perf && (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
              <StatCard label="Total Runs" value={perf.total_runs} />
              <StatCard label="Total Tasks" value={perf.total_tasks} />
              <StatCard label="Pass Rate" value={formatPercent(perf.overall_pass_rate)} />
              <StatCard label="Avg Score" value={formatScore(perf.average_score)} />
              <StatCard label="Avg Duration" value={formatDuration(perf.average_duration_ms)} />
            </div>
          )}
        </div>
      )}

      {tab === 'hardware' && (
        <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-4">
          {hwError && <ErrorBanner message={hwError} />}
          {hwLoading && <LoadingSpinner />}
          {!hwLoading && !hwError && hardware.length === 0 && (
            <p className="text-sm text-gray-500 py-4 text-center">No hardware profiles recorded</p>
          )}
          <div className="space-y-2">
            {hardware.map((h, i) => (
              <div key={i} className="grid grid-cols-3 gap-4 text-sm border-b border-gray-700 pb-2">
                <div><p className="text-gray-500 text-xs">GPU</p><p className="text-white mt-0.5">{String(h['gpu_name'] ?? '—')}</p></div>
                <div><p className="text-gray-500 text-xs">VRAM (MB)</p><p className="text-white mt-0.5">{String(h['vram_mb'] ?? '—')}</p></div>
                <div><p className="text-gray-500 text-xs">Tokens/sec</p><p className="text-white mt-0.5">{String(h['benchmark_tokens_per_sec'] ?? '—')}</p></div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
