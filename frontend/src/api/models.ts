import { apiFetch, apiPost } from './client'
import type { ModelRecord, ModelRunRequest, ModelRunResponse, ModelBenchmarkResponse } from './types'

export function listModels(): Promise<ModelRecord[]> {
  return apiFetch<ModelRecord[]>('/models')
}

export function runModel(req: ModelRunRequest): Promise<ModelRunResponse> {
  return apiPost<ModelRunResponse>('/models/run', req)
}

export function benchmarkModel(modelId: string, apiBase?: string): Promise<ModelBenchmarkResponse> {
  return apiPost<ModelBenchmarkResponse>('/models/benchmark', { model_id: modelId, api_base: apiBase })
}
