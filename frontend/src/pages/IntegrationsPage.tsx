import { useState, useEffect, useCallback } from 'react'
import { Plus, Trash2, ChevronDown, ChevronRight, Globe } from 'lucide-react'
import Pagination from '../components/shared/Pagination'
import StatusBadge from '../components/shared/StatusBadge'
import LoadingSpinner from '../components/shared/LoadingSpinner'
import ErrorBanner from '../components/shared/ErrorBanner'
import EmptyState from '../components/shared/EmptyState'
import { getWebhooks, createWebhook, deleteWebhook, getEvents } from '../api/events'
import { getHealth } from '../api/health'
import { formatDate } from '../utils/formatters'
import type { WebhookResponse, EventResponse, HealthResponse } from '../api/types'

const LIMIT = 50

export default function IntegrationsPage() {
  // Webhooks
  const [webhooks, setWebhooks] = useState<WebhookResponse[]>([])
  const [webhooksLoading, setWebhooksLoading] = useState(true)
  const [webhooksError, setWebhooksError] = useState<string | null>(null)
  const [showAddWebhook, setShowAddWebhook] = useState(false)
  const [newUrl, setNewUrl] = useState('')
  const [newEventTypes, setNewEventTypes] = useState('')
  const [addingWebhook, setAddingWebhook] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  // Events
  const [events, setEvents] = useState<EventResponse[]>([])
  const [eventsTotal, setEventsTotal] = useState(0)
  const [eventsOffset, setEventsOffset] = useState(0)
  const [eventsLoading, setEventsLoading] = useState(true)
  const [eventsError, setEventsError] = useState<string | null>(null)
  const [expandedEvent, setExpandedEvent] = useState<string | null>(null)

  // Atlas status
  const [atlasHealth, setAtlasHealth] = useState<HealthResponse | null>(null)
  const [atlasError, setAtlasError] = useState<string | null>(null)

  const loadWebhooks = useCallback(async () => {
    setWebhooksLoading(true)
    setWebhooksError(null)
    try {
      const res = await getWebhooks()
      setWebhooks(res.webhooks)
    } catch (e) {
      setWebhooksError(e instanceof Error ? e.message : String(e))
    } finally {
      setWebhooksLoading(false)
    }
  }, [])

  const loadEvents = useCallback(async () => {
    setEventsLoading(true)
    setEventsError(null)
    try {
      const res = await getEvents(LIMIT, eventsOffset)
      setEvents(res.events)
      setEventsTotal(res.total)
    } catch (e) {
      setEventsError(e instanceof Error ? e.message : String(e))
    } finally {
      setEventsLoading(false)
    }
  }, [eventsOffset])

  useEffect(() => { void loadWebhooks() }, [loadWebhooks])
  useEffect(() => { void loadEvents() }, [loadEvents])
  useEffect(() => {
    // Try to fetch Atlas health (may fail if Atlas not running)
    getHealth().then(setAtlasHealth).catch(e => setAtlasError(String(e)))
  }, [])

  const handleAddWebhook = async () => {
    if (!newUrl.trim()) return
    setAddingWebhook(true)
    try {
      await createWebhook({
        url: newUrl,
        event_types: newEventTypes.split(',').map(s => s.trim()).filter(Boolean),
      })
      setNewUrl('')
      setNewEventTypes('')
      setShowAddWebhook(false)
      await loadWebhooks()
    } catch (e) {
      setWebhooksError(e instanceof Error ? e.message : String(e))
    } finally {
      setAddingWebhook(false)
    }
  }

  const handleDeleteWebhook = async (id: string) => {
    setDeletingId(id)
    try {
      await deleteWebhook(id)
      await loadWebhooks()
    } catch (e) {
      setWebhooksError(e instanceof Error ? e.message : String(e))
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <div className="space-y-8 max-w-4xl">
      <h1 className="text-2xl font-semibold">Integrations</h1>

      {/* Webhooks */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <p className="text-sm font-medium text-gray-400 uppercase tracking-wide">Webhooks</p>
          <button
            onClick={() => setShowAddWebhook(!showAddWebhook)}
            className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 px-3 py-1.5 rounded-lg text-sm transition-colors"
          >
            <Plus className="w-4 h-4" />
            Add Webhook
          </button>
        </div>

        {webhooksError && <ErrorBanner message={webhooksError} />}

        {showAddWebhook && (
          <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-4 space-y-3">
            <input value={newUrl} onChange={e => setNewUrl(e.target.value)}
              placeholder="Webhook URL (https://...)"
              className="w-full bg-gray-900 border border-gray-600 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500" />
            <input value={newEventTypes} onChange={e => setNewEventTypes(e.target.value)}
              placeholder="Event types (comma-separated, e.g. artifact.processed,job.failed)"
              className="w-full bg-gray-900 border border-gray-600 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500" />
            <div className="flex gap-2">
              <button onClick={handleAddWebhook} disabled={addingWebhook || !newUrl.trim()}
                className="bg-blue-600 hover:bg-blue-500 disabled:opacity-40 px-3 py-2 rounded-lg text-sm transition-colors">
                {addingWebhook ? 'Adding…' : 'Add'}
              </button>
              <button onClick={() => setShowAddWebhook(false)} className="bg-gray-700 hover:bg-gray-600 px-3 py-2 rounded-lg text-sm transition-colors">
                Cancel
              </button>
            </div>
          </div>
        )}

        {webhooksLoading && <LoadingSpinner />}
        {!webhooksLoading && webhooks.length === 0 && <EmptyState message="No webhooks configured" />}
        <div className="space-y-2">
          {webhooks.map(w => (
            <div key={w.id} className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-3 flex items-center gap-3">
              <div className="flex-1 min-w-0">
                <p className="text-sm text-white truncate">{w.url}</p>
                <p className="text-xs text-gray-500 mt-0.5">
                  Events: {w.event_types.length > 0 ? w.event_types.join(', ') : 'all'} |
                  <StatusBadge status={w.active ? 'ok' : 'failed'} className="ml-1" />
                </p>
              </div>
              <button
                onClick={() => void handleDeleteWebhook(w.id)}
                disabled={deletingId === w.id}
                className="text-red-400 hover:text-red-300 disabled:opacity-40 p-1"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          ))}
        </div>
      </section>

      {/* Events */}
      <section className="space-y-3">
        <p className="text-sm font-medium text-gray-400 uppercase tracking-wide">Events ({eventsTotal})</p>
        {eventsError && <ErrorBanner message={eventsError} />}
        <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-2">
          {eventsLoading ? <LoadingSpinner /> : (
            <>
              <div className="space-y-1">
                {events.map(ev => (
                  <div key={ev.id} className="border-b border-gray-800 last:border-0">
                    <div className="flex items-center gap-2 py-2 text-sm">
                      <button onClick={() => setExpandedEvent(expandedEvent === ev.id ? null : ev.id)} className="text-gray-400">
                        {expandedEvent === ev.id ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                      </button>
                      <span className="font-mono text-xs text-gray-500">{ev.id.slice(0, 12)}…</span>
                      <span className="flex-1">{ev.event_type}</span>
                      <StatusBadge status={String(ev.delivered)} />
                      <span className="text-xs text-gray-500">{formatDate(ev.created_at)}</span>
                    </div>
                    {expandedEvent === ev.id && ev.payload_json && (
                      <pre className="text-xs text-gray-400 bg-gray-900 rounded p-2 mb-2 overflow-auto max-h-32">
                        {JSON.stringify(JSON.parse(ev.payload_json), null, 2)}
                      </pre>
                    )}
                  </div>
                ))}
                {events.length === 0 && <p className="text-sm text-gray-500 py-4 text-center">No events</p>}
              </div>
              <Pagination offset={eventsOffset} limit={LIMIT} total={eventsTotal}
                onNext={() => setEventsOffset(o => o + LIMIT)}
                onPrev={() => setEventsOffset(o => Math.max(0, o - LIMIT))} />
            </>
          )}
        </div>
      </section>

      {/* Atlas Status */}
      <section className="space-y-3">
        <p className="text-sm font-medium text-gray-400 uppercase tracking-wide">Atlas Hub Status</p>
        <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-4 flex items-center gap-3">
          <Globe className="w-5 h-5 text-blue-400" />
          {atlasError ? (
            <div>
              <p className="text-sm text-gray-300">Atlas Hub</p>
              <p className="text-xs text-red-400 mt-0.5">Unreachable — {atlasError.slice(0, 80)}</p>
            </div>
          ) : atlasHealth ? (
            <div>
              <p className="text-sm text-gray-300">Atlas Hub</p>
              <StatusBadge status={atlasHealth.status} />
            </div>
          ) : (
            <p className="text-sm text-gray-500">Checking Atlas status…</p>
          )}
          <a
            href="http://localhost:8888"
            target="_blank"
            rel="noopener noreferrer"
            className="ml-auto text-xs text-blue-400 hover:text-blue-300 underline"
          >
            Open Atlas →
          </a>
        </div>
      </section>

    </div>
  )
}
