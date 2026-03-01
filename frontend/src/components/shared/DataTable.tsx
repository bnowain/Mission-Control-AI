import type { ReactNode } from 'react'

export interface Column {
  key: string
  label: string
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  render?: (row: any) => ReactNode
}

interface DataTableProps {
  columns: Column[]
  rows: Record<string, unknown>[]
  onRowClick?: (row: Record<string, unknown>) => void
  emptyMessage?: string
}

export default function DataTable({
  columns,
  rows,
  onRowClick,
  emptyMessage = 'No results',
}: DataTableProps) {
  if (rows.length === 0) {
    return (
      <div className="text-center py-8 text-gray-500 text-sm">{emptyMessage}</div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-700">
            {columns.map(col => (
              <th
                key={col.key}
                className="text-left text-xs text-gray-400 uppercase px-3 py-2 font-medium"
              >
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={i}
              onClick={() => onRowClick?.(row)}
              className={`border-b border-gray-800 ${
                onRowClick ? 'cursor-pointer hover:bg-gray-800/50' : ''
              }`}
            >
              {columns.map(col => (
                <td key={col.key} className="px-3 py-2 text-gray-300">
                  {col.render
                    ? col.render(row)
                    : String(row[col.key] ?? '—')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
