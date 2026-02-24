import { cn } from '@/lib/utils'
import type { McStatus } from '@/lib/types'

interface Props {
  status: McStatus
}

const variants: Record<NonNullable<McStatus> | 'unknown', { label: string; className: string }> = {
  approved:     { label: 'Approved',     className: 'bg-green-100 text-green-800' },
  disapproved:  { label: 'Disapproved',  className: 'bg-red-100 text-red-800' },
  pending:      { label: 'Pending',      className: 'bg-yellow-100 text-yellow-800' },
  not_synced:   { label: 'Not Synced',   className: 'bg-gray-100 text-gray-600' },
  unknown:      { label: '—',            className: 'bg-gray-100 text-gray-400' },
}

export default function McStatusBadge({ status }: Props) {
  const v = variants[status ?? 'unknown'] ?? variants.unknown
  return (
    <span className={cn('rounded-full px-2.5 py-0.5 text-xs font-medium', v.className)}>
      {v.label}
    </span>
  )
}
