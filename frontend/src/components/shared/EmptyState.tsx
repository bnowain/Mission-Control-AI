import { InboxIcon } from 'lucide-react'

interface EmptyStateProps {
  message?: string
}

export default function EmptyState({ message = 'No data available' }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 gap-3 text-gray-500">
      <InboxIcon className="w-10 h-10" />
      <span className="text-sm">{message}</span>
    </div>
  )
}
