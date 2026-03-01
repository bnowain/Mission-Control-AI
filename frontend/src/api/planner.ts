/**
 * Mission Control — Planner SSE Client
 *
 * Streams planning events from POST /planner/claude or /planner/local.
 * Uses fetch() + ReadableStream for SSE parsing.
 */

import type { PlanEvent, PlanDoneEvent } from './types'

export type PlanMode = 'claude' | 'local'

export interface StreamPlanOptions {
  mode: PlanMode
  prompt: string
  projectId?: string
  modelClass?: string    // only used for local mode
  timeoutS?: number
  onEvent: (event: PlanEvent) => void
  onDone: (result: PlanDoneEvent) => void
  onError: (message: string) => void
  signal?: AbortSignal
}

/**
 * Stream a planning session via SSE.
 * Calls onEvent for each thinking/output/tool_use/error event.
 * Calls onDone when the "done" event arrives.
 */
export async function streamPlan(options: StreamPlanOptions): Promise<void> {
  const { mode, prompt, projectId, modelClass, timeoutS, onEvent, onDone, onError, signal } = options

  const endpoint = `/planner/${mode}`
  const body: Record<string, unknown> = { prompt, project_id: projectId }
  if (mode === 'local' && modelClass) body.model_class = modelClass
  if (timeoutS) body.timeout_s = timeoutS

  let response: Response
  try {
    response = await fetch(endpoint, {
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
    onError(`HTTP ${response.status}: ${response.statusText}`)
    return
  }

  const reader = response.body?.getReader()
  if (!reader) {
    onError('No response body — SSE not supported')
    return
  }

  const decoder = new TextDecoder()
  let buffer = ''

  // SSE parser state
  let currentEventType = ''
  let currentData = ''

  const processLine = (line: string) => {
    if (line.startsWith('event:')) {
      currentEventType = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      currentData = line.slice(5).trim()
    } else if (line === '') {
      // Empty line = end of event block
      if (!currentEventType || !currentData) {
        currentEventType = ''
        currentData = ''
        return
      }

      try {
        const parsed = JSON.parse(currentData)

        if (currentEventType === 'done') {
          onDone(parsed as PlanDoneEvent)
        } else if (currentEventType === 'cancelled') {
          onDone({ ...parsed, cancelled: true } as PlanDoneEvent)
        } else if (currentEventType !== '') {
          // thinking, output, tool_use, error
          onEvent({
            event_type: currentEventType as PlanEvent['event_type'],
            content: parsed.content ?? JSON.stringify(parsed),
            timestamp: parsed.timestamp ?? Date.now() / 1000,
          })
        }
      } catch {
        // ignore malformed data
      }

      currentEventType = ''
      currentData = ''
    }
    // Lines starting with ':' are comments (pings) — ignore
  }

  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')

      // Keep the last (possibly incomplete) line in the buffer
      buffer = lines.pop() ?? ''

      for (const line of lines) {
        processLine(line)
      }
    }

    // Process any remaining buffer
    if (buffer) processLine(buffer)

  } catch (err: unknown) {
    if (err instanceof Error && err.name === 'AbortError') return
    onError(String(err))
  } finally {
    reader.releaseLock()
  }
}

/**
 * Cancel the currently active planning session on the server.
 */
export async function cancelPlan(sessionId: string): Promise<void> {
  await fetch('/planner/cancel', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId }),
  }).catch(() => undefined)
}
