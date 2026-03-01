import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Plus, Terminal, BookOpen, Cpu } from 'lucide-react'
import StatCard from '../components/shared/StatCard'
import StatusBadge from '../components/shared/StatusBadge'
import LoadingSpinner from '../components/shared/LoadingSpinner'
import ErrorBanner from '../components/shared/ErrorBanner'
import { getHealth, getSystemStatus, getSystemHardware } from '../api/health'
import type { HealthResponse, SystemStatusResponse, SystemHardwareResponse } from '../api/types'

export default function DashboardPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [status, setStatus] = useState<SystemStatusResponse | null>(null)
  const [hardware, setHardware] = useState<SystemHardwareResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([getHealth(), getSystemStatus(), getSystemHardware()])
      .then(([h, s, hw]) => {
        setHealth(h)
        setStatus(s)
        setHardware(hw)
      })
      .catch(e => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <LoadingSpinner message="Loading dashboard..." />
  if (error) return <ErrorBanner message={error} />

  // gpu_status may be a string or {available: bool}
  const gpuStatusStr = health?.gpu_status == null
    ? 'none'
    : typeof health.gpu_status === 'object'
      ? (health.gpu_status.available ? 'GPU available' : 'no GPU')
      : String(health.gpu_status)

  return (
    <div className="space-y-6">
      {/* Page heading */}
      <div>
        <h1 className="text-2xl font-semibold">Dashboard</h1>
        <p className="text-sm text-gray-400 mt-1">Mission Control — Adaptive AI Execution Framework</p>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Health Status"
          value={health?.status ?? '—'}
          sublabel={health?.db_connectivity ? 'DB connected' : 'DB disconnected'}
        />
        <StatCard
          label="Active Tasks"
          value={status?.active_task_count ?? 0}
          sublabel="currently running"
        />
        <StatCard
          label="Schema Version"
          value={status?.schema_version ?? '—'}
          sublabel={`v${status?.version ?? '?'}`}
        />
        <StatCard
          label="Worker Status"
          value={health?.worker_status ?? '—'}
          sublabel={gpuStatusStr}
        />
      </div>

      {/* Hardware card */}
      {hardware && (
        <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-4">
          <p className="text-sm font-medium text-gray-400 uppercase tracking-wide mb-3">Hardware</p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <p className="text-xs text-gray-500">GPU</p>
              <p className="text-sm text-white mt-0.5">{hardware.gpu_name ?? 'None'}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500">VRAM</p>
              <p className="text-sm text-white mt-0.5">
                {hardware.vram_mb != null ? `${(hardware.vram_mb / 1024).toFixed(1)} GB` : '—'}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-500">Tokens/sec</p>
              <p className="text-sm text-white mt-0.5">
                {hardware.benchmark_tokens_per_sec != null
                  ? `${hardware.benchmark_tokens_per_sec.toFixed(0)} t/s`
                  : '—'}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-500">Capability Classes</p>
              <div className="flex flex-wrap gap-1 mt-0.5">
                {hardware.available_capability_classes.length > 0
                  ? hardware.available_capability_classes.map(c => (
                      <StatusBadge key={c} status={c} />
                    ))
                  : <span className="text-sm text-gray-500">none</span>
                }
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Quick actions */}
      <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-4">
        <p className="text-sm font-medium text-gray-400 uppercase tracking-wide mb-3">Quick Actions</p>
        <div className="flex flex-wrap gap-3">
          <Link
            to="/tasks"
            className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 px-3 py-1.5 rounded-lg text-sm transition-colors"
          >
            <Plus className="w-4 h-4" />
            New Task
          </Link>
          <Link
            to="/sql"
            className="flex items-center gap-2 bg-gray-700 hover:bg-gray-600 px-3 py-1.5 rounded-lg text-sm transition-colors"
          >
            <Terminal className="w-4 h-4" />
            SQL Console
          </Link>
          <Link
            to="/codex"
            className="flex items-center gap-2 bg-gray-700 hover:bg-gray-600 px-3 py-1.5 rounded-lg text-sm transition-colors"
          >
            <BookOpen className="w-4 h-4" />
            Codex Search
          </Link>
          <Link
            to="/workers"
            className="flex items-center gap-2 bg-gray-700 hover:bg-gray-600 px-3 py-1.5 rounded-lg text-sm transition-colors"
          >
            <Cpu className="w-4 h-4" />
            View Workers
          </Link>
        </div>
      </div>

      {/* System info */}
      {status && (
        <div className="text-xs text-gray-600 space-y-0.5">
          <p>Service: {status.service} v{status.version}</p>
          <p>DB: {status.db_path}</p>
        </div>
      )}
    </div>
  )
}
