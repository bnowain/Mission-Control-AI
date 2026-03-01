import { apiFetch, apiPost } from './client'
import type {
  PlanCreate, PlanResponse, ReplanRequest,
  PlanStepResponse,
} from './types'

export function createPlan(req: PlanCreate): Promise<PlanResponse> {
  return apiPost<PlanResponse>('/plans', req)
}

export function getPlan(id: string): Promise<PlanResponse> {
  return apiFetch<PlanResponse>(`/plans/${id}`)
}

export function executePlanStep(planId: string, stepId: string): Promise<PlanStepResponse> {
  return apiPost<PlanStepResponse>(`/plans/${planId}/steps/${stepId}/execute`, {})
}

export function replan(planId: string, req: ReplanRequest): Promise<PlanResponse> {
  return apiPost<PlanResponse>(`/plans/${planId}/replan`, req)
}

export function getPlanDiff(planId: string): Promise<{ diff_history: Record<string, unknown>[] }> {
  return apiFetch(`/plans/${planId}/diff`)
}

export function completeStep(planId: string, stepId: string): Promise<PlanStepResponse> {
  return apiPost<PlanStepResponse>(`/plans/${planId}/steps/${stepId}/complete`, {})
}

export function failStep(planId: string, stepId: string, reason: string): Promise<PlanStepResponse> {
  return apiPost<PlanStepResponse>(`/plans/${planId}/steps/${stepId}/fail`, { reason })
}

export function listPlansSQL(limit = 50, offset = 0): Promise<{ columns: string[]; rows: unknown[][]; row_count: number }> {
  return apiPost('/sql/query', {
    sql: `SELECT id, project_id, plan_title, plan_status, plan_version, created_at, updated_at FROM plans ORDER BY created_at DESC LIMIT ? OFFSET ?`,
    params: [limit, offset],
    write_mode: false,
  })
}
