import { useState, useEffect } from 'react'
import { Search, BarChart3, Layers } from 'lucide-react'
import StatCard from '../components/shared/StatCard'
import StatusBadge from '../components/shared/StatusBadge'
import DataTable from '../components/shared/DataTable'
import LoadingSpinner from '../components/shared/LoadingSpinner'
import ErrorBanner from '../components/shared/ErrorBanner'
import EmptyState from '../components/shared/EmptyState'
import { searchCodex, getCodexStats, getFailureClusters } from '../api/codex'
import { useDebounce } from '../hooks/useDebounce'
import { formatDate, formatPercent } from '../utils/formatters'
import type { CodexSearchResult, CodexStatsResponse, FailureClusterRow } from '../api/types'

type Tab = 'search' | 'stats' | 'clusters'

export default function CodexPage() {
  const [tab, setTab] = useState<Tab>('search')

  // Search tab
  const [query, setQuery] = useState('')
  const debounced = useDebounce(query, 400)
  const [searchResults, setSearchResults] = useState<CodexSearchResult[]>([])
  const [searchLoading, setSearchLoading] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)

  // Stats tab
  const [stats, setStats] = useState<CodexStatsResponse | null>(null)
  const [statsLoading, setStatsLoading] = useState(false)
  const [statsError, setStatsError] = useState<string | null>(null)

  // Clusters tab
  const [clusters, setClusters] = useState<FailureClusterRow[]>([])
  const [clustersLoading, setClustersLoading] = useState(false)
  const [clustersError, setClustersError] = useState<string | null>(null)

  useEffect(() => {
    if (!debounced.trim()) { setSearchResults([]); return }
    setSearchLoading(true)
    setSearchError(null)
    searchCodex(debounced, 20, 0)
      .then(res => setSearchResults(res.results))
      .catch(e => setSearchError(e instanceof Error ? e.message : String(e)))
      .finally(() => setSearchLoading(false))
  }, [debounced])

  useEffect(() => {
    if (tab !== 'stats') return
    setStatsLoading(true)
    getCodexStats()
      .then(setStats)
      .catch(e => setStatsError(e instanceof Error ? e.message : String(e)))
      .finally(() => setStatsLoading(false))
  }, [tab])

  useEffect(() => {
    if (tab !== 'clusters') return
    setClustersLoading(true)
    getFailureClusters(20, 0)
      .then(res => setClusters(res.clusters))
      .catch(e => setClustersError(e instanceof Error ? e.message : String(e)))
      .finally(() => setClustersLoading(false))
  }, [tab])

  const clusterColumns = [
    { key: 'stack_trace_hash', label: 'Hash', render: (r: FailureClusterRow) => <span className="font-mono text-xs">{r.stack_trace_hash.slice(0, 12)}</span> },
    { key: 'cluster_label', label: 'Label', render: (r: FailureClusterRow) => <span>{r.cluster_label ?? '—'}</span> },
    { key: 'occurrence_count', label: 'Occurrences' },
    { key: 'first_seen_at', label: 'First Seen', render: (r: FailureClusterRow) => <span className="text-xs">{formatDate(r.first_seen_at)}</span> },
    { key: 'last_seen_at', label: 'Last Seen', render: (r: FailureClusterRow) => <span className="text-xs">{formatDate(r.last_seen_at)}</span> },
  ]

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Codex</h1>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-700">
        {([['search', 'Search', Search], ['stats', 'Stats', BarChart3], ['clusters', 'Clusters', Layers]] as const).map(([t, label, Icon]) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`flex items-center gap-2 px-4 py-2 text-sm transition-colors border-b-2 -mb-px ${
              tab === t ? 'border-blue-500 text-blue-400' : 'border-transparent text-gray-400 hover:text-gray-200'
            }`}
          >
            <Icon className="w-4 h-4" />
            {label}
          </button>
        ))}
      </div>

      {/* Search tab */}
      {tab === 'search' && (
        <div className="space-y-4">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
            <input
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Search codex lessons..."
              className="w-full pl-9 bg-gray-900 border border-gray-600 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500"
            />
          </div>
          {searchError && <ErrorBanner message={searchError} />}
          {searchLoading && <LoadingSpinner message="Searching..." />}
          {!searchLoading && !searchError && query && searchResults.length === 0 && (
            <EmptyState message="No codex entries found" />
          )}
          <div className="space-y-3">
            {searchResults.map(r => (
              <div key={r.id} className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-3 space-y-2">
                <div className="flex items-start justify-between gap-3">
                  <p className="text-sm text-white font-medium">{r.root_cause}</p>
                  <div className="flex items-center gap-2 shrink-0">
                    {r.category && <StatusBadge status={r.category} />}
                    <span className="text-xs text-gray-500">{formatPercent(r.confidence_score)}</span>
                  </div>
                </div>
                <p className="text-xs text-gray-400">{r.prevention_guideline}</p>
                <div className="flex items-center gap-2 text-xs text-gray-500">
                  <span>scope: {r.scope}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Stats tab */}
      {tab === 'stats' && (
        <div>
          {statsError && <ErrorBanner message={statsError} />}
          {statsLoading && <LoadingSpinner />}
          {stats && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <StatCard label="Master Codex" value={stats.master_codex_count} sublabel="verified lessons" />
              <StatCard label="Project Codex" value={stats.project_codex_count} sublabel="project-scoped" />
              <StatCard label="Candidates" value={stats.candidate_count} sublabel="pending review" />
              <StatCard label="Promoted" value={stats.promoted_count} sublabel="total promoted" />
            </div>
          )}
        </div>
      )}

      {/* Clusters tab */}
      {tab === 'clusters' && (
        <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-2">
          {clustersError && <ErrorBanner message={clustersError} />}
          {clustersLoading && <LoadingSpinner />}
          {!clustersLoading && !clustersError && (
            <DataTable
              columns={clusterColumns}
              rows={clusters as unknown as Record<string, unknown>[]}
              emptyMessage="No failure clusters"
            />
          )}
        </div>
      )}
    </div>
  )
}
