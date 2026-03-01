import { apiFetch } from './client'
import type { HealthResponse, SystemStatusResponse, SystemHardwareResponse } from './types'

export function getHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>('/api/health')
}

export function getSystemStatus(): Promise<SystemStatusResponse> {
  return apiFetch<SystemStatusResponse>('/system/status')
}

export function getSystemHardware(): Promise<SystemHardwareResponse> {
  return apiFetch<SystemHardwareResponse>('/system/hardware')
}
