import { usePolling } from './usePolling'
import { getHealth } from '../api/health'
import type { HealthResponse } from '../api/types'

export function useHealth() {
  return usePolling<HealthResponse>(getHealth, 30000)
}
