import { apiFetch, apiPost } from './client'
import type { RouterSelectRequest, RoutingDecision, RouterStatsResponse } from './types'

export function selectModel(req: RouterSelectRequest): Promise<RoutingDecision> {
  return apiPost<RoutingDecision>('/router/select', req)
}

export function getRouterStats(): Promise<RouterStatsResponse> {
  return apiFetch<RouterStatsResponse>('/api/router/stats')
}
