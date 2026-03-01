import { apiFetch } from './client'
import type {
  TelemetryRunsResponse, TelemetryModelsResponse,
  TelemetryPerformanceResponse, TelemetryHardwareResponse,
} from './types'

export function getRuns(limit = 50, offset = 0, taskId?: string, modelId?: string): Promise<TelemetryRunsResponse> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (taskId) params.set('task_id', taskId)
  if (modelId) params.set('model_id', modelId)
  return apiFetch<TelemetryRunsResponse>(`/telemetry/runs?${params}`)
}

export function getModels(): Promise<TelemetryModelsResponse> {
  return apiFetch<TelemetryModelsResponse>('/telemetry/models')
}

export function getPerformance(): Promise<TelemetryPerformanceResponse> {
  return apiFetch<TelemetryPerformanceResponse>('/telemetry/performance')
}

export function getHardware(): Promise<TelemetryHardwareResponse> {
  return apiFetch<TelemetryHardwareResponse>('/telemetry/hardware')
}
