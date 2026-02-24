'use client'

import { useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { Check, X, Loader2 } from 'lucide-react'
import { formatDateTime, cn } from '@/lib/utils'
import type { ActionRow } from '@/lib/types'

interface Props {
  action: ActionRow
}

export default function ApprovalRow({ action }: Props) {
  const [isPending, startTransition] = useTransition()
  const router = useRouter()

  const respond = (response: 'YES' | 'NO') => {
    startTransition(async () => {
      try {
        const res = await fetch('/api/actions/respond', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            action_log_id: action.id,
            response,
          }),
        })
        if (!res.ok) throw new Error('Request failed')
        toast.success(response === 'YES' ? 'Action approved' : 'Action rejected')
        router.refresh()
      } catch {
        toast.error('Failed to respond — try again')
      }
    })
  }

  const statusColors: Record<string, string> = {
    pending:  'bg-yellow-100 text-yellow-800',
    approved: 'bg-green-100 text-green-800',
    rejected: 'bg-red-100 text-red-800',
    executed: 'bg-blue-100 text-blue-800',
    failed:   'bg-gray-100 text-gray-700',
  }

  return (
    <tr className="border-b border-gray-100 last:border-0 hover:bg-gray-50">
      <td className="py-3 pr-4">
        <span className="text-xs font-medium uppercase text-gray-500">{action.platform}</span>
      </td>
      <td className="py-3 pr-4">
        <p className="text-sm font-medium text-gray-900">{action.action_type}</p>
        <p className="text-xs text-gray-500">{action.entity_level} · {action.entity_id}</p>
      </td>
      <td className="py-3 pr-4">
        <div className="text-sm text-gray-700">
          {action.old_value && <span className="line-through text-gray-400">{action.old_value}</span>}
          {action.old_value && action.new_value && <span className="mx-1 text-gray-400">→</span>}
          {action.new_value && <span className="font-medium">{action.new_value}</span>}
          {!action.old_value && !action.new_value && <span className="text-gray-400">—</span>}
        </div>
      </td>
      <td className="py-3 pr-4 text-sm text-gray-500">{formatDateTime(action.ts)}</td>
      <td className="py-3 pr-4">
        <span className={cn('rounded-full px-2 py-0.5 text-xs font-medium', statusColors[action.status] ?? 'bg-gray-100 text-gray-700')}>
          {action.status}
        </span>
      </td>
      <td className="py-3">
        {action.status === 'pending' ? (
          <div className="flex gap-2">
            <button
              onClick={() => respond('YES')}
              disabled={isPending}
              className="flex items-center gap-1 rounded-lg bg-green-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50"
            >
              {isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
              Approve
            </button>
            <button
              onClick={() => respond('NO')}
              disabled={isPending}
              className="flex items-center gap-1 rounded-lg border border-red-200 bg-white px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
            >
              <X className="h-3 w-3" />
              Reject
            </button>
          </div>
        ) : (
          <span className="text-xs text-gray-400">{formatDateTime(action.executed_at)}</span>
        )}
      </td>
    </tr>
  )
}
