import { useEffect, useState } from 'react'
import StatCard from '../components/shared/StatCard'
import StatusBadge from '../components/shared/StatusBadge'
import LoadingSpinner from '../components/shared/LoadingSpinner'
import ErrorBanner from '../components/shared/ErrorBanner'
import { getHealth, getSystemStatus } from '../api/health'
import { getPerformance, getModels } from '../api/telemetry'
import { getCodexStats } from '../api/codex'
import { formatPercent, formatScore, formatDuration } from '../utils/formatters'
import type {
  HealthResponse, SystemStatusResponse,
  TelemetryPerformanceResponse, TelemetryModelStats, CodexStatsResponse,
} from '../api/types'

export default function ReportsPage() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [status, setStatus] = useState<SystemStatusResponse | null>(null)
  const [perf, setPerf] = useState<TelemetryPerformanceResponse | null>(null)
  const [models, setModels] = useState<TelemetryModelStats[]>([])
  const [codexStats, setCodexStats] = useState<CodexStatsResponse | null>(null)

  useEffect(() => {
    Promise.all([
      getHealth(),
      getSystemStatus(),
      getPerformance(),
      getModels().then(r => r.models),
      getCodexStats(),
    ])
      .then(([h, s, p, m, c]) => {
        setHealth(h); setStatus(s); setPerf(p); setModels(m); setCodexStats(c)
      })
      .catch(e => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <LoadingSpinner message="Generating report..." />
  if (error) return <ErrorBanner message={error} />

  const topModels = [...models].sort((a, b) => (b.average_score ?? 0) - (a.average_score ?? 0)).slice(0, 5)

  return (
    <div className="space-y-8 max-w-5xl">
      <h1 className="text-2xl font-semibold">Reports</h1>

      {/* System Overview */}
      <section>
        <p className="text-sm font-medium text-gray-400 uppercase tracking-wide mb-3">System Overview</p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatCard label="Health" value={health?.status ?? '—'} sublabel={health?.db_connectivity ? 'DB ok' : 'DB error'} />
          <StatCard label="Schema Version" value={status?.schema_version ?? '—'} sublabel={`v${status?.version ?? '?'}`} />
          <StatCard label="Active Tasks" value={status?.active_task_count ?? 0} />
          <StatCard label="Worker Status" value={health?.worker_status ?? '—'} />
        </div>
      </section>

      {/* Execution Summary */}
      {perf && (
        <section>
          <p className="text-sm font-medium text-gray-400 uppercase tracking-wide mb-3">Execution Summary</p>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
            <StatCard label="Total Runs" value={perf.total_runs} />
            <StatCard label="Total Tasks" value={perf.total_tasks} />
            <StatCard label="Pass Rate" value={formatPercent(perf.overall_pass_rate)} />
            <StatCard label="Avg Score" value={formatScore(perf.average_score)} />
            <StatCard label="Avg Duration" value={formatDuration(perf.average_duration_ms)} />
          </div>
        </section>
      )}

      {/* Top Models */}
      {topModels.length > 0 && (
        <section>
          <p className="text-sm font-medium text-gray-400 uppercase tracking-wide mb-3">Top Models by Score</p>
          <div className="bg-gray-800 border border-gray-700 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-700">
                  <th className="text-left text-xs text-gray-400 uppercase px-4 py-2">Model</th>
                  <th className="text-left text-xs text-gray-400 uppercase px-4 py-2">Runs</th>
                  <th className="text-left text-xs text-gray-400 uppercase px-4 py-2">Avg Score</th>
                  <th className="text-left text-xs text-gray-400 uppercase px-4 py-2">Pass Rate</th>
                </tr>
              </thead>
              <tbody>
                {topModels.map((m, i) => (
                  <tr key={i} className="border-b border-gray-800">
                    <td className="px-4 py-2 text-gray-300 font-mono text-xs">{m.model_id}</td>
                    <td className="px-4 py-2 text-gray-300">{m.run_count}</td>
                    <td className="px-4 py-2 text-gray-300">{formatScore(m.average_score)}</td>
                    <td className="px-4 py-2"><span className="text-gray-300">{formatPercent(m.pass_rate)}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Knowledge Base */}
      {codexStats && (
        <section>
          <p className="text-sm font-medium text-gray-400 uppercase tracking-wide mb-3">Knowledge Base</p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <StatCard label="Master Codex" value={codexStats.master_codex_count} />
            <StatCard label="Project Codex" value={codexStats.project_codex_count} />
            <StatCard label="Candidates" value={codexStats.candidate_count} />
            <StatCard label="Promoted" value={codexStats.promoted_count} />
          </div>
        </section>
      )}

      {/* Worker Health */}
      {health && (
        <section>
          <p className="text-sm font-medium text-gray-400 uppercase tracking-wide mb-3">Worker Health</p>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            <StatCard label="API Health" value={health.status} />
            <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-3">
              <p className="text-xs text-gray-400 uppercase tracking-wide mb-1">Workers</p>
              <StatusBadge status={health.worker_status} />
            </div>
            <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-3">
              <p className="text-xs text-gray-400 uppercase tracking-wide mb-1">GPU</p>
              <p className="text-sm text-white mt-0.5">
              {health.gpu_status == null ? 'none'
                : typeof health.gpu_status === 'object'
                  ? (health.gpu_status.available ? 'available' : 'unavailable')
                  : health.gpu_status}
            </p>
            </div>
          </div>
        </section>
      )}
    </div>
  )
}
