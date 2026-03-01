import { apiFetch, apiPost, apiDelete } from './client'
import type {
  EventListResponse,
  WebhookCreateRequest, WebhookResponse, WebhookListResponse,
} from './types'

export function getEvents(limit = 50, offset = 0): Promise<EventListResponse> {
  return apiFetch<EventListResponse>(`/events?limit=${limit}&offset=${offset}`)
}

export function getWebhooks(): Promise<WebhookListResponse> {
  return apiFetch<WebhookListResponse>('/events/webhooks')
}

export function createWebhook(req: WebhookCreateRequest): Promise<WebhookResponse> {
  return apiPost<WebhookResponse>('/events/webhooks', req)
}

export function deleteWebhook(id: string): Promise<void> {
  return apiDelete(`/events/webhooks/${id}`)
}
