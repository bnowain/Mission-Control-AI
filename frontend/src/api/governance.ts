import { apiFetch, apiPost } from './client'
import type { AuditLogEntry, FeatureFlag, PromptRegistryEntry } from './types'

export function getAuditLog(limit = 50, offset = 0): Promise<{ entries: AuditLogEntry[]; total: number }> {
  return apiFetch(`/audit?limit=${limit}&offset=${offset}`)
}

export function getFeatureFlags(): Promise<{ flags: FeatureFlag[] }> {
  return apiFetch('/feature-flags')
}

export function updateFeatureFlag(flag: string, enabled: boolean, projectId?: string): Promise<FeatureFlag> {
  return apiPost('/feature-flags', { flag, enabled, project_id: projectId ?? null })
}

export function getPromptRegistry(limit = 50, offset = 0): Promise<{ prompts: PromptRegistryEntry[]; total: number }> {
  return apiFetch(`/prompt-registry?limit=${limit}&offset=${offset}`)
}

export function registerPrompt(req: {
  prompt_id: string
  version: string
  content: string
  task_type?: string
  model_id?: string
}): Promise<PromptRegistryEntry> {
  return apiPost('/prompt-registry', req)
}
