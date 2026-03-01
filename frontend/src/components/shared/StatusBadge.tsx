interface StatusBadgeProps {
  status: string
  className?: string
}

const colorMap: Record<string, string> = {
  ok: 'bg-green-900 text-green-300',
  online: 'bg-green-900 text-green-300',
  healthy: 'bg-green-900 text-green-300',
  running: 'bg-blue-900 text-blue-300',
  pending: 'bg-gray-700 text-gray-300',
  completed: 'bg-green-900 text-green-300',
  failed: 'bg-red-900 text-red-300',
  cancelled: 'bg-gray-700 text-gray-300',
  degraded: 'bg-yellow-900 text-yellow-300',
  replanning: 'bg-yellow-900 text-yellow-300',
  skipped: 'bg-gray-700 text-gray-300',
  queued: 'bg-gray-700 text-gray-300',
  retrying: 'bg-orange-900 text-orange-300',
  received: 'bg-gray-700 text-gray-300',
  processing: 'bg-blue-900 text-blue-300',
  processed: 'bg-green-900 text-green-300',
  available_for_export: 'bg-teal-900 text-teal-300',
  exported: 'bg-purple-900 text-purple-300',
  archived: 'bg-gray-700 text-gray-400',
  true: 'bg-green-900 text-green-300',
  false: 'bg-red-900 text-red-300',
}

export default function StatusBadge({ status, className = '' }: StatusBadgeProps) {
  const key = status.toLowerCase()
  const color = colorMap[key] ?? 'bg-gray-700 text-gray-300'
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${color} ${className}`}>
      {status}
    </span>
  )
}
