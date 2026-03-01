import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, ChevronDown, ChevronRight } from 'lucide-react'
import DataTable from '../components/shared/DataTable'
import StatusBadge from '../components/shared/StatusBadge'
import LoadingSpinner from '../components/shared/LoadingSpinner'
import ErrorBanner from '../components/shared/ErrorBanner'
import { listPlansSQL, createPlan } from '../api/plans'
import { formatDate } from '../utils/formatters'

interface PlanRow extends Record<string, unknown> {
  id: string
  project_id: string
  plan_title: string
  plan_status: string
  plan_version: number
  created_at: string
  updated_at: string
}

const LIMIT = 50

export default function PlansPage() {
  const navigate = useNavigate()
  const [rows, setRows] = useState<PlanRow[]>([])
  const [total, setTotal] = useState(0)
  const [offset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Create form
  const [showCreate, setShowCreate] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [newProjectId, setNewProjectId] = useState('default')
  const [newPlanTitle, setNewPlanTitle] = useState('')
  const [phaseTitle, setPhaseTitle] = useState('Phase 1')
  const [stepTitle, setStepTitle] = useState('Step 1')
  const [creating, setCreating] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await listPlansSQL(LIMIT, offset)
      const cols = res.columns
      const mapped = res.rows.map(r => {
        const obj: Record<string, unknown> = {}
        cols.forEach((c, i) => { obj[c] = r[i] })
        return obj as PlanRow
      })
      setRows(mapped)
      setTotal(res.row_count)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [offset])

  useEffect(() => { void load() }, [load])

  const handleCreate = async () => {
    if (!newPlanTitle.trim()) return
    setCreating(true)
    try {
      const plan = await createPlan({
        project_id: newProjectId,
        plan_title: newPlanTitle,
        phases: [{
          phase_title: phaseTitle,
          steps: [{ step_title: stepTitle, step_type: 'generic' }],
        }],
      })
      navigate(`/plans/${plan.id}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setCreating(false)
    }
  }

  const columns = [
    { key: 'id', label: 'ID', render: (r: PlanRow) => <span className="font-mono text-xs">{String(r.id).slice(0, 16)}…</span> },
    { key: 'plan_title', label: 'Title' },
    { key: 'project_id', label: 'Project' },
    { key: 'plan_status', label: 'Status', render: (r: PlanRow) => <StatusBadge status={String(r.plan_status)} /> },
    { key: 'plan_version', label: 'v' },
    { key: 'created_at', label: 'Created', render: (r: PlanRow) => <span className="text-xs">{formatDate(String(r.created_at))}</span> },
  ]

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Plans ({total})</h1>
        <button
          onClick={() => setShowCreate(!showCreate)}
          className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 px-3 py-1.5 rounded-lg text-sm transition-colors"
        >
          <Plus className="w-4 h-4" />
          New Plan
        </button>
      </div>

      {showCreate && (
        <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-4">
          <button
            onClick={() => setCreateOpen(!createOpen)}
            className="flex items-center gap-2 text-sm font-medium text-gray-300 w-full"
          >
            {createOpen ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
            Create Plan
          </button>
          {createOpen && (
            <div className="mt-3 space-y-3">
              <div className="flex flex-wrap gap-3">
                <input value={newProjectId} onChange={e => setNewProjectId(e.target.value)}
                  placeholder="Project ID"
                  className="bg-gray-900 border border-gray-600 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500" />
                <input value={newPlanTitle} onChange={e => setNewPlanTitle(e.target.value)}
                  placeholder="Plan title"
                  className="flex-1 bg-gray-900 border border-gray-600 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500" />
              </div>
              <div className="flex flex-wrap gap-3">
                <input value={phaseTitle} onChange={e => setPhaseTitle(e.target.value)}
                  placeholder="First phase title"
                  className="bg-gray-900 border border-gray-600 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500" />
                <input value={stepTitle} onChange={e => setStepTitle(e.target.value)}
                  placeholder="First step title"
                  className="bg-gray-900 border border-gray-600 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500" />
                <button onClick={handleCreate} disabled={creating || !newPlanTitle.trim()}
                  className="bg-blue-600 hover:bg-blue-500 disabled:opacity-40 px-3 py-2 rounded-lg text-sm transition-colors">
                  {creating ? 'Creating…' : 'Create'}
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {error && <ErrorBanner message={error} />}

      <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-2">
        {loading ? <LoadingSpinner /> : (
          <DataTable
            columns={columns}
            rows={rows}
            onRowClick={r => navigate(`/plans/${r.id}`)}
          />
        )}
      </div>
    </div>
  )
}
