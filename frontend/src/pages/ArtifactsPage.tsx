import { useState, useEffect, useCallback } from 'react'
import { Archive, Cog } from 'lucide-react'
import DataTable from '../components/shared/DataTable'
import Pagination from '../components/shared/Pagination'
import StatusBadge from '../components/shared/StatusBadge'
import LoadingSpinner from '../components/shared/LoadingSpinner'
import ErrorBanner from '../components/shared/ErrorBanner'
import { listArtifacts, archiveArtifact, processArtifact } from '../api/artifacts'
import { formatDate, formatBytes } from '../utils/formatters'
import type { ArtifactResponse, ArtifactState } from '../api/types'

const LIMIT = 50
const STATE_OPTIONS: Array<ArtifactState | ''> = [
  '', 'RECEIVED', 'PROCESSING', 'PROCESSED', 'AVAILABLE_FOR_EXPORT', 'EXPORTED', 'ARCHIVED',
]

export default function ArtifactsPage() {
  const [artifacts, setArtifacts] = useState<ArtifactResponse[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [stateFilter, setStateFilter] = useState<ArtifactState | ''>('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionId, setActionId] = useState<string | null>(null)
  const [selected, setSelected] = useState<ArtifactResponse | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await listArtifacts(LIMIT, offset, stateFilter || undefined)
      setArtifacts(res.artifacts)
      setTotal(res.total)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [offset, stateFilter])

  useEffect(() => { void load() }, [load])

  const handleArchive = async (id: string) => {
    setActionId(id)
    try {
      await archiveArtifact(id)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setActionId(null)
    }
  }

  const handleProcess = async (id: string) => {
    setActionId(id + '_proc')
    try {
      await processArtifact(id, { pipeline_name: 'ocr', priority: 5 })
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setActionId(null)
    }
  }

  const columns = [
    { key: 'id', label: 'ID', render: (r: ArtifactResponse) => <span className="font-mono text-xs">{r.id.slice(0, 16)}…</span> },
    { key: 'source_type', label: 'Type', render: (r: ArtifactResponse) => <span>{r.source_type ?? '—'}</span> },
    { key: 'processing_state', label: 'State', render: (r: ArtifactResponse) => <StatusBadge status={r.processing_state} /> },
    { key: 'file_size_bytes', label: 'Size', render: (r: ArtifactResponse) => <span>{formatBytes(r.file_size_bytes)}</span> },
    { key: 'ingest_at', label: 'Ingested', render: (r: ArtifactResponse) => <span className="text-xs">{formatDate(r.ingest_at)}</span> },
    {
      key: 'actions', label: 'Actions',
      render: (r: ArtifactResponse) => (
        <div className="flex gap-2">
          {r.processing_state !== 'ARCHIVED' && (
            <button
              onClick={e => { e.stopPropagation(); void handleArchive(r.id) }}
              disabled={actionId === r.id}
              className="flex items-center gap-1 text-xs bg-gray-700 hover:bg-gray-600 disabled:opacity-40 px-2 py-1 rounded transition-colors"
            >
              <Archive className="w-3 h-3" />
              Archive
            </button>
          )}
          <button
            onClick={e => { e.stopPropagation(); void handleProcess(r.id) }}
            disabled={actionId === r.id + '_proc'}
            className="flex items-center gap-1 text-xs bg-blue-800 hover:bg-blue-700 disabled:opacity-40 px-2 py-1 rounded transition-colors"
          >
            <Cog className="w-3 h-3" />
            Process
          </button>
        </div>
      ),
    },
  ]

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Artifacts ({total})</h1>
        <select
          value={stateFilter}
          onChange={e => { setStateFilter(e.target.value as ArtifactState | ''); setOffset(0) }}
          className="bg-gray-900 border border-gray-600 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500"
        >
          {STATE_OPTIONS.map(s => <option key={s} value={s}>{s || 'All states'}</option>)}
        </select>
      </div>

      {error && <ErrorBanner message={error} />}

      {/* Detail card */}
      {selected && (
        <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-4 space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium text-gray-300">Artifact Detail</p>
            <button onClick={() => setSelected(null)} className="text-xs text-gray-500 hover:text-gray-300">Close</button>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-sm">
            <div><p className="text-gray-500 text-xs">ID</p><p className="text-white mt-0.5 font-mono text-xs">{selected.id}</p></div>
            <div><p className="text-gray-500 text-xs">State</p><StatusBadge status={selected.processing_state} /></div>
            <div><p className="text-gray-500 text-xs">Type</p><p className="text-white mt-0.5">{selected.source_type ?? '—'}</p></div>
            <div><p className="text-gray-500 text-xs">MIME</p><p className="text-white mt-0.5">{selected.mime_type ?? '—'}</p></div>
            <div><p className="text-gray-500 text-xs">Size</p><p className="text-white mt-0.5">{formatBytes(selected.file_size_bytes)}</p></div>
            <div><p className="text-gray-500 text-xs">Version</p><p className="text-white mt-0.5">v{selected.artifact_version}</p></div>
            {selected.page_url && (
              <div className="md:col-span-3"><p className="text-gray-500 text-xs">URL</p>
                <a href={selected.page_url} target="_blank" rel="noopener noreferrer" className="text-blue-400 text-xs underline truncate block">{selected.page_url}</a>
              </div>
            )}
            {selected.file_path && (
              <div className="md:col-span-3"><p className="text-gray-500 text-xs">File</p><p className="text-white mt-0.5 text-xs font-mono">{selected.file_path}</p></div>
            )}
          </div>
        </div>
      )}

      <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-2">
        {loading ? <LoadingSpinner /> : (
          <>
            <DataTable
              columns={columns}
              rows={artifacts as unknown as Record<string, unknown>[]}
              onRowClick={r => setSelected(r as unknown as ArtifactResponse)}
              emptyMessage="No artifacts found"
            />
            <Pagination offset={offset} limit={LIMIT} total={total}
              onNext={() => setOffset(o => o + LIMIT)}
              onPrev={() => setOffset(o => Math.max(0, o - LIMIT))} />
          </>
        )}
      </div>
    </div>
  )
}
