import { apiFetch } from './client'
import type {
  JobListResponse, JobResponse,
  WorkerStatsResponse, PipelineAvailabilityResponse,
} from './types'

export function getPipelines(): Promise<PipelineAvailabilityResponse[]> {
  return apiFetch<PipelineAvailabilityResponse[]>('/workers/pipelines')
}

export function getJobs(limit = 50, offset = 0, status?: string): Promise<JobListResponse> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (status) params.set('status', status)
  return apiFetch<JobListResponse>(`/workers/jobs?${params}`)
}

export function getJob(id: string): Promise<JobResponse> {
  return apiFetch<JobResponse>(`/workers/jobs/${id}`)
}

export function getWorkerStats(): Promise<WorkerStatsResponse> {
  return apiFetch<WorkerStatsResponse>('/workers/stats')
}
