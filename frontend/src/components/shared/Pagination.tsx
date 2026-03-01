interface PaginationProps {
  offset: number
  limit: number
  total: number
  onNext: () => void
  onPrev: () => void
}

export default function Pagination({ offset, limit, total, onNext, onPrev }: PaginationProps) {
  const from = Math.min(offset + 1, total)
  const to = Math.min(offset + limit, total)

  return (
    <div className="flex items-center justify-between text-sm text-gray-400 mt-4">
      <span>
        Showing {from}–{to} of {total}
      </span>
      <div className="flex gap-2">
        <button
          onClick={onPrev}
          disabled={offset === 0}
          className="px-3 py-1 rounded-lg bg-gray-800 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          Previous
        </button>
        <button
          onClick={onNext}
          disabled={to >= total}
          className="px-3 py-1 rounded-lg bg-gray-800 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          Next
        </button>
      </div>
    </div>
  )
}
