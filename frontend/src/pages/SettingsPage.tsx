import { useState, useEffect, useCallback } from 'react'
import { Plus } from 'lucide-react'
import DataTable from '../components/shared/DataTable'
import Pagination from '../components/shared/Pagination'
import StatusBadge from '../components/shared/StatusBadge'
import LoadingSpinner from '../components/shared/LoadingSpinner'
import ErrorBanner from '../components/shared/ErrorBanner'
import {
  getFeatureFlags, updateFeatureFlag,
  getPromptRegistry, registerPrompt,
  getAuditLog,
} from '../api/governance'
import { formatDate } from '../utils/formatters'
import type { FeatureFlag, PromptRegistryEntry, AuditLogEntry } from '../api/types'

type Section = 'flags' | 'prompts' | 'audit'

const AUDIT_LIMIT = 50

export default function SettingsPage() {
  const [section, setSection] = useState<Section>('flags')

  // Feature flags
  const [flags, setFlags] = useState<FeatureFlag[]>([])
  const [flagsLoading, setFlagsLoading] = useState(false)
  const [flagsError, setFlagsError] = useState<string | null>(null)
  const [togglingFlag, setTogglingFlag] = useState<string | null>(null)

  // Prompt registry
  const [prompts, setPrompts] = useState<PromptRegistryEntry[]>([])
  const [promptsTotal, setPromptsTotal] = useState(0)
  const [promptsOffset, setPromptsOffset] = useState(0)
  const [promptsLoading, setPromptsLoading] = useState(false)
  const [promptsError, setPromptsError] = useState<string | null>(null)
  const [showRegister, setShowRegister] = useState(false)
  const [newPromptId, setNewPromptId] = useState('')
  const [newVersion, setNewVersion] = useState('1.0')
  const [newContent, setNewContent] = useState('')
  const [registering, setRegistering] = useState(false)

  // Audit log
  const [auditEntries, setAuditEntries] = useState<AuditLogEntry[]>([])
  const [auditTotal, setAuditTotal] = useState(0)
  const [auditOffset, setAuditOffset] = useState(0)
  const [auditLoading, setAuditLoading] = useState(false)
  const [auditError, setAuditError] = useState<string | null>(null)

  const loadFlags = useCallback(async () => {
    setFlagsLoading(true)
    setFlagsError(null)
    try {
      const res = await getFeatureFlags()
      setFlags(res.flags)
    } catch (e) {
      setFlagsError(e instanceof Error ? e.message : String(e))
    } finally {
      setFlagsLoading(false)
    }
  }, [])

  const loadPrompts = useCallback(async () => {
    setPromptsLoading(true)
    setPromptsError(null)
    try {
      const res = await getPromptRegistry(AUDIT_LIMIT, promptsOffset)
      setPrompts(res.prompts)
      setPromptsTotal(res.total)
    } catch (e) {
      setPromptsError(e instanceof Error ? e.message : String(e))
    } finally {
      setPromptsLoading(false)
    }
  }, [promptsOffset])

  const loadAudit = useCallback(async () => {
    setAuditLoading(true)
    setAuditError(null)
    try {
      const res = await getAuditLog(AUDIT_LIMIT, auditOffset)
      setAuditEntries(res.entries)
      setAuditTotal(res.total)
    } catch (e) {
      setAuditError(e instanceof Error ? e.message : String(e))
    } finally {
      setAuditLoading(false)
    }
  }, [auditOffset])

  useEffect(() => {
    if (section === 'flags') void loadFlags()
  }, [section, loadFlags])

  useEffect(() => {
    if (section === 'prompts') void loadPrompts()
  }, [section, loadPrompts])

  useEffect(() => {
    if (section === 'audit') void loadAudit()
  }, [section, loadAudit])

  const handleToggleFlag = async (flag: FeatureFlag) => {
    setTogglingFlag(flag.flag)
    try {
      await updateFeatureFlag(flag.flag, !flag.enabled, flag.project_id ?? undefined)
      await loadFlags()
    } catch (e) {
      setFlagsError(e instanceof Error ? e.message : String(e))
    } finally {
      setTogglingFlag(null)
    }
  }

  const handleRegisterPrompt = async () => {
    if (!newPromptId.trim() || !newContent.trim()) return
    setRegistering(true)
    try {
      await registerPrompt({ prompt_id: newPromptId, version: newVersion, content: newContent })
      setNewPromptId('')
      setNewVersion('1.0')
      setNewContent('')
      setShowRegister(false)
      await loadPrompts()
    } catch (e) {
      setPromptsError(e instanceof Error ? e.message : String(e))
    } finally {
      setRegistering(false)
    }
  }

  const promptColumns = [
    { key: 'prompt_id', label: 'Prompt ID' },
    { key: 'version', label: 'Version' },
    { key: 'task_type', label: 'Task Type', render: (r: PromptRegistryEntry) => <span>{r.task_type ?? '—'}</span> },
    { key: 'model_id', label: 'Model', render: (r: PromptRegistryEntry) => <span>{r.model_id ?? '—'}</span> },
    { key: 'created_at', label: 'Created', render: (r: PromptRegistryEntry) => <span className="text-xs">{formatDate(r.created_at)}</span> },
  ]

  const auditColumns = [
    { key: 'action', label: 'Action' },
    { key: 'actor', label: 'Actor', render: (r: AuditLogEntry) => <span>{r.actor ?? '—'}</span> },
    { key: 'target_type', label: 'Target', render: (r: AuditLogEntry) => <span>{r.target_type ?? '—'}</span> },
    { key: 'detail', label: 'Detail', render: (r: AuditLogEntry) => <span className="text-xs truncate max-w-xs block">{r.detail ?? '—'}</span> },
    { key: 'created_at', label: 'When', render: (r: AuditLogEntry) => <span className="text-xs">{formatDate(r.created_at)}</span> },
  ]

  return (
    <div className="space-y-4 max-w-5xl">
      <h1 className="text-2xl font-semibold">Settings</h1>

      {/* Section tabs */}
      <div className="flex gap-1 border-b border-gray-700">
        {(['flags', 'prompts', 'audit'] as Section[]).map(s => (
          <button
            key={s}
            onClick={() => setSection(s)}
            className={`px-4 py-2 text-sm transition-colors border-b-2 -mb-px capitalize ${
              section === s ? 'border-blue-500 text-blue-400' : 'border-transparent text-gray-400 hover:text-gray-200'
            }`}
          >
            {s === 'flags' ? 'Feature Flags' : s === 'prompts' ? 'Prompt Registry' : 'Audit Log'}
          </button>
        ))}
      </div>

      {/* Feature Flags */}
      {section === 'flags' && (
        <div className="space-y-3">
          {flagsError && <ErrorBanner message={flagsError} />}
          {flagsLoading && <LoadingSpinner />}
          {!flagsLoading && flags.length === 0 && (
            <p className="text-sm text-gray-500 text-center py-8">No feature flags configured</p>
          )}
          <div className="space-y-2">
            {flags.map(f => (
              <div key={f.flag + (f.project_id ?? '')} className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-3 flex items-center gap-3">
                <div className="flex-1">
                  <p className="text-sm text-white">{f.flag}</p>
                  {f.project_id && <p className="text-xs text-gray-500 mt-0.5">project: {f.project_id}</p>}
                </div>
                <StatusBadge status={f.enabled ? 'ok' : 'failed'} />
                <button
                  onClick={() => void handleToggleFlag(f)}
                  disabled={togglingFlag === f.flag}
                  className={`px-3 py-1.5 rounded-lg text-sm transition-colors disabled:opacity-40 ${
                    f.enabled ? 'bg-red-800 hover:bg-red-700' : 'bg-green-800 hover:bg-green-700'
                  }`}
                >
                  {togglingFlag === f.flag ? '…' : f.enabled ? 'Disable' : 'Enable'}
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Prompt Registry */}
      {section === 'prompts' && (
        <div className="space-y-3">
          <div className="flex justify-end">
            <button
              onClick={() => setShowRegister(!showRegister)}
              className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 px-3 py-1.5 rounded-lg text-sm transition-colors"
            >
              <Plus className="w-4 h-4" />
              Register Prompt
            </button>
          </div>

          {showRegister && (
            <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-4 space-y-3">
              <div className="flex gap-3">
                <input value={newPromptId} onChange={e => setNewPromptId(e.target.value)}
                  placeholder="Prompt ID"
                  className="flex-1 bg-gray-900 border border-gray-600 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500" />
                <input value={newVersion} onChange={e => setNewVersion(e.target.value)}
                  placeholder="Version"
                  className="w-24 bg-gray-900 border border-gray-600 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500" />
              </div>
              <textarea value={newContent} onChange={e => setNewContent(e.target.value)}
                rows={4} placeholder="Prompt content..."
                className="w-full bg-gray-900 border border-gray-600 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500 resize-none" />
              <div className="flex gap-2">
                <button onClick={handleRegisterPrompt} disabled={registering || !newPromptId.trim() || !newContent.trim()}
                  className="bg-blue-600 hover:bg-blue-500 disabled:opacity-40 px-3 py-2 rounded-lg text-sm transition-colors">
                  {registering ? 'Registering…' : 'Register'}
                </button>
                <button onClick={() => setShowRegister(false)} className="bg-gray-700 hover:bg-gray-600 px-3 py-2 rounded-lg text-sm transition-colors">
                  Cancel
                </button>
              </div>
            </div>
          )}

          {promptsError && <ErrorBanner message={promptsError} />}
          <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-2">
            {promptsLoading ? <LoadingSpinner /> : (
              <>
                <DataTable columns={promptColumns} rows={prompts as unknown as Record<string, unknown>[]} emptyMessage="No prompts registered" />
                <Pagination offset={promptsOffset} limit={AUDIT_LIMIT} total={promptsTotal}
                  onNext={() => setPromptsOffset(o => o + AUDIT_LIMIT)}
                  onPrev={() => setPromptsOffset(o => Math.max(0, o - AUDIT_LIMIT))} />
              </>
            )}
          </div>
        </div>
      )}

      {/* Audit Log */}
      {section === 'audit' && (
        <div className="space-y-3">
          {auditError && <ErrorBanner message={auditError} />}
          <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-2">
            {auditLoading ? <LoadingSpinner /> : (
              <>
                <DataTable columns={auditColumns} rows={auditEntries as unknown as Record<string, unknown>[]} emptyMessage="No audit entries" />
                <Pagination offset={auditOffset} limit={AUDIT_LIMIT} total={auditTotal}
                  onNext={() => setAuditOffset(o => o + AUDIT_LIMIT)}
                  onPrev={() => setAuditOffset(o => Math.max(0, o - AUDIT_LIMIT))} />
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

