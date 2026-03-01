import { apiFetch, apiPost } from './client'
import type {
  ArtifactCreateRequest, ArtifactResponse, ArtifactListResponse,
  ArtifactExportResponse, ArtifactStateTransitionRequest,
  ProcessArtifactRequest,
} from './types'

export function listArtifacts(limit = 50, offset = 0, state?: string, sourceType?: string): Promise<ArtifactListResponse> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (state) params.set('state', state)
  if (sourceType) params.set('source_type', sourceType)
  return apiFetch<ArtifactListResponse>(`/artifacts?${params}`)
}

export function getArtifact(id: string): Promise<ArtifactResponse> {
  return apiFetch<ArtifactResponse>(`/artifacts/${id}`)
}

export function ingestArtifact(req: ArtifactCreateRequest): Promise<ArtifactResponse> {
  return apiPost<ArtifactResponse>('/artifacts', req)
}

export function exportArtifact(id: string): Promise<ArtifactExportResponse> {
  return apiFetch<ArtifactExportResponse>(`/artifacts/${id}/export`)
}

export function transitionState(id: string, req: ArtifactStateTransitionRequest): Promise<ArtifactResponse> {
  return apiPost<ArtifactResponse>(`/artifacts/${id}/transition`, req)
}

export function processArtifact(id: string, req: ProcessArtifactRequest): Promise<{ job_id: string }> {
  return apiPost<{ job_id: string }>(`/artifacts/${id}/process`, req)
}

export function archiveArtifact(id: string): Promise<{ id: string; processing_state: string }> {
  return apiPost(`/artifacts/${id}/archive`, {})
}
