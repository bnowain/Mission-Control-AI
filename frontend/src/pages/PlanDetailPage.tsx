import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { ArrowLeft, ChevronDown, ChevronRight, RefreshCw } from 'lucide-react'
import StatusBadge from '../components/shared/StatusBadge'
import LoadingSpinner from '../components/shared/LoadingSpinner'
import ErrorBanner from '../components/shared/ErrorBanner'
import { getPlan, executePlanStep, replan, completeStep, failStep } from '../api/plans'
import { formatDate } from '../utils/formatters'
import type { PlanResponse, PlanPhaseResponse, PlanStepResponse } from '../api/types'

const stepStatusColor: Record<string, string> = {
  completed: 'border-green-700 bg-green-900/20',
  running: 'border-blue-700 bg-blue-900/20',
  failed: 'border-red-700 bg-red-900/20',
  pending: 'border-gray-700 bg-gray-900/20',
  skipped: 'border-gray-700 bg-gray-800/20',
}

export default function PlanDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [plan, setPlan] = useState<PlanResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [openPhases, setOpenPhases] = useState<Set<string>>(new Set())
  const [replanReason, setReplanReason] = useState('')
  const [replanning, setReplanning] = useState(false)
  const [actionLoading, setActionLoading] = useState<string | null>(null)

  const load = async () => {
    if (!id) return
    try {
      const p = await getPlan(id)
      setPlan(p)
      // Open all phases by default
      setOpenPhases(new Set(p.phases.map(ph => ph.id)))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [id])

  const togglePhase = (phaseId: string) => {
    setOpenPhases(prev => {
      const next = new Set(prev)
      if (next.has(phaseId)) next.delete(phaseId)
      else next.add(phaseId)
      return next
    })
  }

  const handleExecuteStep = async (planId: string, stepId: string) => {
    setActionLoading(stepId)
    try {
      await executePlanStep(planId, stepId)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setActionLoading(null)
    }
  }

  const handleCompleteStep = async (planId: string, stepId: string) => {
    setActionLoading(stepId + '_complete')
    try {
      await completeStep(planId, stepId)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setActionLoading(null)
    }
  }

  const handleFailStep = async (planId: string, stepId: string) => {
    setActionLoading(stepId + '_fail')
    try {
      await failStep(planId, stepId, 'Manual fail')
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setActionLoading(null)
    }
  }

  const handleReplan = async () => {
    if (!id || !replanReason.trim()) return
    setReplanning(true)
    try {
      await replan(id, { reason: replanReason })
      setReplanReason('')
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setReplanning(false)
    }
  }

  if (loading) return <LoadingSpinner message="Loading plan..." />
  if (error && !plan) return <ErrorBanner message={error} />
  if (!plan) return <ErrorBanner message="Plan not found" />

  return (
    <div className="space-y-6 max-w-4xl">
      <div className="flex items-center gap-3">
        <Link to="/plans" className="text-gray-400 hover:text-white">
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <div className="flex-1 min-w-0">
          <h1 className="text-xl font-semibold truncate">{plan.plan_title}</h1>
          <p className="text-xs text-gray-500 font-mono">{plan.id}</p>
        </div>
        <StatusBadge status={plan.plan_status} />
      </div>

      {error && <ErrorBanner message={error} />}

      {/* Plan meta */}
      <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-4 grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
        <div><p className="text-gray-500 text-xs">Project</p><p className="text-white mt-0.5">{plan.project_id}</p></div>
        <div><p className="text-gray-500 text-xs">Version</p><p className="text-white mt-0.5">v{plan.plan_version}</p></div>
        <div><p className="text-gray-500 text-xs">Created</p><p className="text-white mt-0.5">{formatDate(plan.created_at)}</p></div>
        <div><p className="text-gray-500 text-xs">Updated</p><p className="text-white mt-0.5">{formatDate(plan.updated_at)}</p></div>
      </div>

      {/* Phases + Steps */}
      <div className="space-y-3">
        {plan.phases.map((phase: PlanPhaseResponse) => (
          <div key={phase.id} className="bg-gray-800 border border-gray-700 rounded-xl overflow-hidden">
            <button
              onClick={() => togglePhase(phase.id)}
              className="w-full flex items-center gap-3 px-4 py-3 hover:bg-gray-700/50 transition-colors"
            >
              {openPhases.has(phase.id)
                ? <ChevronDown className="w-4 h-4 text-gray-400 shrink-0" />
                : <ChevronRight className="w-4 h-4 text-gray-400 shrink-0" />}
              <span className="text-sm font-medium flex-1 text-left">
                Phase {phase.phase_index + 1}: {phase.phase_title}
              </span>
              <StatusBadge status={phase.phase_status} />
            </button>

            {openPhases.has(phase.id) && (
              <div className="px-4 pb-3 space-y-2">
                {phase.steps.map((step: PlanStepResponse) => (
                  <div
                    key={step.id}
                    className={`ml-6 border rounded-lg px-3 py-2 ${stepStatusColor[step.step_status] ?? 'border-gray-700'}`}
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-gray-500">{step.step_index + 1}.</span>
                      <span className="text-sm flex-1">{step.step_title}</span>
                      <StatusBadge status={step.step_status} />
                    </div>
                    {step.result_summary && (
                      <p className="text-xs text-gray-400 mt-1 ml-4">{step.result_summary}</p>
                    )}
                    {step.step_status === 'pending' && (
                      <div className="flex gap-2 mt-2 ml-4">
                        <button
                          onClick={() => handleExecuteStep(plan.id, step.id)}
                          disabled={actionLoading === step.id}
                          className="text-xs bg-blue-700 hover:bg-blue-600 disabled:opacity-40 px-2 py-1 rounded transition-colors"
                        >
                          {actionLoading === step.id ? 'Running…' : 'Execute'}
                        </button>
                        <button
                          onClick={() => handleCompleteStep(plan.id, step.id)}
                          disabled={actionLoading === step.id + '_complete'}
                          className="text-xs bg-green-800 hover:bg-green-700 disabled:opacity-40 px-2 py-1 rounded transition-colors"
                        >
                          Complete
                        </button>
                        <button
                          onClick={() => handleFailStep(plan.id, step.id)}
                          disabled={actionLoading === step.id + '_fail'}
                          className="text-xs bg-red-800 hover:bg-red-700 disabled:opacity-40 px-2 py-1 rounded transition-colors"
                        >
                          Fail
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Replan */}
      <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-4 space-y-3">
        <p className="text-sm font-medium text-gray-300">Replan</p>
        <div className="flex gap-3">
          <input
            value={replanReason}
            onChange={e => setReplanReason(e.target.value)}
            placeholder="Reason for replan..."
            className="flex-1 bg-gray-900 border border-gray-600 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500"
          />
          <button
            onClick={handleReplan}
            disabled={replanning || !replanReason.trim()}
            className="flex items-center gap-2 bg-yellow-700 hover:bg-yellow-600 disabled:opacity-40 px-3 py-2 rounded-lg text-sm transition-colors"
          >
            <RefreshCw className="w-4 h-4" />
            {replanning ? 'Replanning…' : 'Replan'}
          </button>
        </div>
      </div>

      {/* Diff history */}
      {plan.plan_diff_history.length > 0 && (
        <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-4">
          <p className="text-sm font-medium text-gray-400 uppercase tracking-wide mb-3">Diff History</p>
          <div className="space-y-2">
            {plan.plan_diff_history.map((diff, i) => (
              <pre key={i} className="text-xs text-gray-400 bg-gray-900 rounded p-2 overflow-auto">
                {JSON.stringify(diff, null, 2)}
              </pre>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
