import { apiFetch, apiPost } from './client'
import type {
  CodexSearchResponse, CodexStatsResponse,
  CodexQueryRequest, CodexCandidateRequest, CodexCandidateResponse,
  CodexPromoteRequest, CodexPromoteResponse,
  FailureClustersResponse,
} from './types'

export function searchCodex(q: string, limit = 10, offset = 0): Promise<CodexSearchResponse> {
  return apiFetch<CodexSearchResponse>(`/api/codex/search?q=${encodeURIComponent(q)}&limit=${limit}&offset=${offset}`)
}

export function queryCodex(req: CodexQueryRequest): Promise<CodexSearchResponse> {
  return apiPost<CodexSearchResponse>('/codex/query', req)
}

export function getCodexStats(): Promise<CodexStatsResponse> {
  return apiFetch<CodexStatsResponse>('/codex/stats')
}

export function getFailureClusters(limit = 20, offset = 0): Promise<FailureClustersResponse> {
  return apiFetch<FailureClustersResponse>(`/codex/clusters?limit=${limit}&offset=${offset}`)
}

export function registerCandidate(req: CodexCandidateRequest): Promise<CodexCandidateResponse> {
  return apiPost<CodexCandidateResponse>('/codex/candidate', req)
}

export function promoteCandidate(req: CodexPromoteRequest): Promise<CodexPromoteResponse> {
  return apiPost<CodexPromoteResponse>('/codex/promote', req)
}

export function checkEligibility(candidateId: string): Promise<{ eligible: boolean; reason: string }> {
  return apiFetch(`/codex/promote/eligible/${candidateId}`)
}
