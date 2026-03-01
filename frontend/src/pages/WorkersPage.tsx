import { useState, useEffect, useCallback } from 'react'
import StatCard from '../components/shared/StatCard'
import StatusBadge from '../components/shared/StatusBadge'
import DataTable from '../components/shared/DataTable'
import Pagination from '../components/shared/Pagination'
import LoadingSpinner from '../components/shared/LoadingSpinner'
import ErrorBanner from '../components/shared/ErrorBanner'
import { getPipelines, getJobs, getWorkerStats } from '../api/workers'
import { formatDate } from '../utils/formatters'
import type { JobResponse, WorkerStatsResponse, PipelineAvailabilityResponse } from '../api/types'

const LIMIT = 50
const STATUS_OPTIONS = ['', 'QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'RETRYING']

export default function WorkersPage() {
  const [stats, setStats] = useState<WorkerStatsResponse | null>(null)
  const [pipelines, setPipelines] = useState<PipelineAvailabilityResponse[]>([])
  const [jobs, setJobs] = useState<JobResponse[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [statusFilter, setStatusFilter] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [s, p, j] = await Promise.all([
        getWorkerStats(),
        getPipelines(),
        getJobs(LIMIT, offset, statusFilter || undefined),
      ])
      setStats(s)
      setPipelines(p)
      setJobs(j.jobs)
      setTotal(j.total)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [offset, statusFilter])

  useEffect(() => { void load() }, [load])

  const jobColumns = [
    { key: 'id', label: 'Job ID', render: (r: JobResponse) => <span className="font-mono text-xs">{r.id.slice(0, 16)}…</span> },
    { key: 'job_type', label: 'Type' },
    { key: 'job_status', label: 'Status', render: (r: JobResponse) => <StatusBadge status={r.job_status} /> },
    { key: 'priority', label: 'Priority' },
    { key: 'retry_count', label: 'Retries' },
    { key: 'created_at', label: 'Created', render: (r: JobResponse) => <span className="text-xs">{formatDate(r.created_at)}</span> },
    { key: 'started_at', label: 'Started', render: (r: JobResponse) => <span className="text-xs">{r.started_at ? formatDate(r.started_at) : '—'}</span> },
  ]

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Workers</h1>

      {error && <ErrorBanner message={error} />}
      {loading ? <LoadingSpinner /> : (
        <>
          {/* Stats */}
          {stats && (
            <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
              <StatCard label="Queued" value={stats.queued} />
              <StatCard label="Running" value={stats.running} />
              <StatCard label="Completed" value={stats.completed} />
              <StatCard label="Failed" value={stats.failed} />
              <StatCard label="Retrying" value={stats.retrying} />
              <StatCard label="Total" value={stats.total} />
            </div>
          )}

          {/* Pipelines */}
          {pipelines.length > 0 && (
            <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-4">
              <p className="text-sm font-medium text-gray-400 uppercase tracking-wide mb-3">Pipeline Availability</p>
              <div className="flex flex-wrap gap-3">
                {pipelines.map(p => (
                  <div key={p.name} className="flex items-center gap-2 bg-gray-900 rounded-lg px-3 py-2">
                    <span className={`w-2 h-2 rounded-full ${p.available ? 'bg-green-400' : 'bg-red-400'}`} />
                    <span className="text-sm text-gray-300">{p.name}</span>
                    <StatusBadge status={p.available ? 'ok' : 'offline'} />
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Jobs */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium text-gray-400 uppercase tracking-wide">Jobs ({total})</p>
              <select
                value={statusFilter}
                onChange={e => { setStatusFilter(e.target.value); setOffset(0) }}
                className="bg-gray-900 border border-gray-600 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500"
              >
                {STATUS_OPTIONS.map(s => <option key={s} value={s}>{s || 'All statuses'}</option>)}
              </select>
            </div>
            <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-2">
              <DataTable
                columns={jobColumns}
                rows={jobs as unknown as Record<string, unknown>[]}
                emptyMessage="No jobs found"
              />
              <Pagination offset={offset} limit={LIMIT} total={total}
                onNext={() => setOffset(o => o + LIMIT)}
                onPrev={() => setOffset(o => Math.max(0, o - LIMIT))} />
            </div>
          </div>
        </>
      )}
    </div>
  )
}

