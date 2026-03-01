import { apiFetch, apiPost } from './client'
import type {
  TaskCreate, TaskResponse,
  TaskExecuteRequest, TaskExecuteResponse,
  SqlQueryResponse,
} from './types'

export function createTask(req: TaskCreate): Promise<TaskResponse> {
  return apiPost<TaskResponse>('/tasks', req)
}

export function getTask(id: string): Promise<TaskResponse> {
  return apiFetch<TaskResponse>(`/tasks/${id}`)
}

export function executeTask(id: string, req: TaskExecuteRequest): Promise<TaskExecuteResponse> {
  return apiPost<TaskExecuteResponse>(`/tasks/${id}/execute`, req)
}

export function cancelTask(id: string): Promise<{ task_id: string; task_status: string }> {
  return apiPost(`/tasks/${id}/cancel`, {})
}

export function listTasksSQL(
  limit = 50,
  offset = 0,
  filters: { task_status?: string; task_type?: string } = {},
): Promise<SqlQueryResponse> {
  const conditions: string[] = []
  const params: unknown[] = []

  if (filters.task_status) {
    conditions.push(`task_status = ?`)
    params.push(filters.task_status)
  }
  if (filters.task_type) {
    conditions.push(`task_type = ?`)
    params.push(filters.task_type)
  }

  const where = conditions.length > 0 ? `WHERE ${conditions.join(' AND ')}` : ''
  const sql = `SELECT id, project_id, task_type, task_status, created_at, updated_at FROM tasks ${where} ORDER BY created_at DESC LIMIT ? OFFSET ?`
  params.push(limit, offset)

  return apiPost<SqlQueryResponse>('/sql/query', { sql, params, write_mode: false })
}
