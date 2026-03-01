import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus } from 'lucide-react'
import DataTable from '../components/shared/DataTable'
import Pagination from '../components/shared/Pagination'
import StatusBadge from '../components/shared/StatusBadge'
import LoadingSpinner from '../components/shared/LoadingSpinner'
import ErrorBanner from '../components/shared/ErrorBanner'
import { listTasksSQL, createTask } from '../api/tasks'
import { formatDate } from '../utils/formatters'
import type { TaskType } from '../api/types'

const TASK_TYPES: TaskType[] = [
  'bug_fix', 'refactor_small', 'refactor_large',
  'architecture_design', 'file_edit', 'test_write', 'docs', 'generic',
]

const STATUS_OPTIONS = ['', 'pending', 'running', 'completed', 'failed', 'cancelled']

const LIMIT = 50

interface TaskRow extends Record<string, unknown> {
  id: string
  project_id: string
  task_type: string
  task_status: string
  created_at: string
  updated_at: string
}

export default function TasksPage() {
  const navigate = useNavigate()
  const [rows, setRows] = useState<TaskRow[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Filters
  const [statusFilter, setStatusFilter] = useState('')
  const [typeFilter, setTypeFilter] = useState('')

  // Create form
  const [showCreate, setShowCreate] = useState(false)
  const [newProjectId, setNewProjectId] = useState('default')
  const [newTaskType, setNewTaskType] = useState<TaskType>('generic')
  const [creating, setCreating] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await listTasksSQL(LIMIT, offset, {
        task_status: statusFilter || undefined,
        task_type: typeFilter || undefined,
      })
      // Convert SQL rows to objects
      const cols = res.columns
      const mapped = res.rows.map(r => {
        const obj: Record<string, unknown> = {}
        cols.forEach((c, i) => { obj[c] = r[i] })
        return obj as TaskRow
      })
      setRows(mapped)
      setTotal(res.row_count)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [offset, statusFilter, typeFilter])

  useEffect(() => { void load() }, [load])

  const handleCreate = async () => {
    setCreating(true)
    try {
      const task = await createTask({ project_id: newProjectId, task_type: newTaskType })
      navigate(`/tasks/${task.id}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setCreating(false)
    }
  }

  const columns = [
    { key: 'id', label: 'ID', render: (r: TaskRow) => <span className="font-mono text-xs">{String(r.id).slice(0, 16)}…</span> },
    { key: 'project_id', label: 'Project' },
    { key: 'task_type', label: 'Type' },
    { key: 'task_status', label: 'Status', render: (r: TaskRow) => <StatusBadge status={String(r.task_status)} /> },
    { key: 'created_at', label: 'Created', render: (r: TaskRow) => <span className="text-xs">{formatDate(String(r.created_at))}</span> },
  ]

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Tasks</h1>
        <button
          onClick={() => setShowCreate(!showCreate)}
          className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 px-3 py-1.5 rounded-lg text-sm transition-colors"
        >
          <Plus className="w-4 h-4" />
          New Task
        </button>
      </div>

      {/* Create form */}
      {showCreate && (
        <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-4 space-y-3">
          <p className="text-sm font-medium text-gray-300">Create Task</p>
          <div className="flex flex-wrap gap-3">
            <input
              value={newProjectId}
              onChange={e => setNewProjectId(e.target.value)}
              placeholder="Project ID"
              className="bg-gray-900 border border-gray-600 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500"
            />
            <select
              value={newTaskType}
              onChange={e => setNewTaskType(e.target.value as TaskType)}
              className="bg-gray-900 border border-gray-600 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500"
            >
              {TASK_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
            <button
              onClick={handleCreate}
              disabled={creating}
              className="bg-blue-600 hover:bg-blue-500 disabled:opacity-40 px-3 py-2 rounded-lg text-sm transition-colors"
            >
              {creating ? 'Creating…' : 'Create'}
            </button>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex gap-3">
        <select
          value={statusFilter}
          onChange={e => { setStatusFilter(e.target.value); setOffset(0) }}
          className="bg-gray-900 border border-gray-600 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500"
        >
          <option value="">All statuses</option>
          {STATUS_OPTIONS.filter(Boolean).map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <select
          value={typeFilter}
          onChange={e => { setTypeFilter(e.target.value); setOffset(0) }}
          className="bg-gray-900 border border-gray-600 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500"
        >
          <option value="">All types</option>
          {TASK_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>

      {error && <ErrorBanner message={error} />}

      <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-2">
        {loading ? (
          <LoadingSpinner />
        ) : (
          <>
            <DataTable
              columns={columns}
              rows={rows}
              onRowClick={r => navigate(`/tasks/${r.id}`)}
            />
            <Pagination
              offset={offset}
              limit={LIMIT}
              total={total}
              onNext={() => setOffset(o => o + LIMIT)}
              onPrev={() => setOffset(o => Math.max(0, o - LIMIT))}
            />
          </>
        )}
      </div>
    </div>
  )
}
