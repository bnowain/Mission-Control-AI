import { apiFetch, apiPost } from './client'
import type {
  TaskCreate, TaskResponse,
  TaskExecuteRequest, TaskExecuteResponse,
  TaskStreamEvent, TaskDoneEvent,
  SqlQueryResponse,
} from './types'

export interface StreamTaskOptions {
  prompt: string
  force_model_class?: string
  force_context_tier?: string
  onEvent: (event: TaskStreamEvent) => void
  onDone: (result: TaskDoneEvent) => void
  onError: (message: string) => void
  signal?: AbortSignal
}

export async function streamTaskExecution(taskId: string, opts: StreamTaskOptions): Promise<void> {
  const { prompt, force_model_class, force_context_tier, onEvent, onDone, onError, signal } = opts
  const body: Record<string, unknown> = { prompt }
  if (force_model_class) body.force_model_class = force_model_class
  if (force_context_tier) body.force_context_tier = force_context_tier

  let response: Response
  try {
    response = await fetch(`/tasks/${taskId}/execute/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    })
  } catch (err: unknown) {
    if (err instanceof Error && err.name === 'AbortError') return
    onError(String(err))
    return
  }

  if (!response.ok) {
    const text = await response.text().catch(() => response.statusText)
    onError(`HTTP ${response.status}: ${text}`)
    return
  }

  const reader = response.body?.getReader()
  if (!reader) { onError('No response body'); return }

  const decoder = new TextDecoder()
  let buffer = ''
  let currentEventType = ''
  let currentData = ''

  const processLine = (line: string) => {
    if (line.startsWith('event:')) {
      currentEventType = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      currentData = line.slice(5).trim()
    } else if (line === '') {
      if (!currentEventType || !currentData) { currentEventType = ''; currentData = ''; return }
      try {
        const parsed = JSON.parse(currentData)
        if (currentEventType === 'done') {
          onDone(parsed as TaskDoneEvent)
        } else if (currentEventType === 'cancelled') {
          onDone({ ...parsed, cancelled: true } as TaskDoneEvent)
        } else if (currentEventType === 'error') {
          onError(parsed.content ?? JSON.stringify(parsed))
        } else {
          onEvent({ event_type: currentEventType as TaskStreamEvent['event_type'], ...parsed })
        }
      } catch { /* ignore malformed */ }
      currentEventType = ''
      currentData = ''
    }
  }

  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''
      for (const line of lines) processLine(line)
    }
    if (buffer) processLine(buffer)
  } catch (err: unknown) {
    if (err instanceof Error && err.name === 'AbortError') return
    onError(String(err))
  } finally {
    reader.releaseLock()
  }
}

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
