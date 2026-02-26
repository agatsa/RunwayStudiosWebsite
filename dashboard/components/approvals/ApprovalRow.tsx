'use client'

import { useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { Check, X, Loader2, TrendingUp, PauseCircle, Sparkles, MapPin, Hash, Target, Eye, Clock } from 'lucide-react'
import type { ActionRow } from '@/lib/types'

interface Props {
  action: ActionRow
}

const ACTION_META: Record<string, { icon: React.ReactNode; label: string; color: string }> = {
  increase_budget:      { icon: <span className="text-lg">💰</span>, label: 'Increase Budget', color: 'bg-green-100 text-green-700' },
  reduce_budget:        { icon: <span className="text-lg">📉</span>, label: 'Reduce Budget', color: 'bg-orange-100 text-orange-700' },
  pause_campaign:       { icon: <PauseCircle className="h-5 w-5" />, label: 'Pause Campaign', color: 'bg-yellow-100 text-yellow-700' },
  new_creative:         { icon: <Sparkles className="h-5 w-5" />, label: 'New Creative', color: 'bg-purple-100 text-purple-700' },
  geographic_expansion: { icon: <MapPin className="h-5 w-5" />, label: 'Geo Expansion', color: 'bg-blue-100 text-blue-700' },
  keyword_addition:     { icon: <Hash className="h-5 w-5" />, label: 'Add Keywords', color: 'bg-indigo-100 text-indigo-700' },
  bid_adjustment:       { icon: <Target className="h-5 w-5" />, label: 'Adjust Bids', color: 'bg-cyan-100 text-cyan-700' },
  review:               { icon: <Eye className="h-5 w-5" />, label: 'Review', color: 'bg-gray-100 text-gray-700' },
  ai_brief:             { icon: <span className="text-lg">✨</span>, label: 'AI Opportunity', color: 'bg-amber-100 text-amber-700' },
}

const PLATFORM_COLORS: Record<string, string> = {
  meta:   'bg-blue-100 text-blue-700',
  google: 'bg-green-100 text-green-700',
  youtube:'bg-red-100 text-red-700',
  all:    'bg-violet-100 text-violet-700',
}

const STATUS_COLORS: Record<string, string> = {
  pending:  'bg-yellow-100 text-yellow-800',
  approved: 'bg-green-100 text-green-800',
  rejected: 'bg-red-100 text-red-800',
  executed: 'bg-blue-100 text-blue-800',
  failed:   'bg-gray-100 text-gray-700',
}

function timeAgo(ts: string) {
  if (!ts) return ''
  const diff = Date.now() - new Date(ts).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

export default function ApprovalRow({ action }: Props) {
  const [isPending, startTransition] = useTransition()
  const router = useRouter()

  const meta = ACTION_META[action.action_type] ?? ACTION_META['review']

  // Parse context from new_value (may be JSON string or object)
  let ctx: Record<string, string> = {}
  try {
    const raw = action.new_value
    if (typeof raw === 'string') ctx = JSON.parse(raw)
    else if (raw && typeof raw === 'object') ctx = raw as Record<string, string>
  } catch { /* ignore */ }

  const description = ctx.description || ctx.detail || ''
  const entityName = ctx.entity_name || action.entity_id || ''
  const suggestedValue = ctx.suggested_value || (action.new_value && typeof action.new_value === 'string' && !action.new_value.startsWith('{') ? action.new_value : '')
  const oldValue = action.old_value && typeof action.old_value !== 'object' ? String(action.old_value) : ''

  const respond = (decision: 'approve' | 'reject') => {
    startTransition(async () => {
      try {
        const res = await fetch('/api/actions/respond', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action_id: action.id, decision }),
        })
        const data = await res.json()
        if (!res.ok || data.ok === false) {
          toast.error(data.detail || data.error || 'Failed to respond — try again')
          return
        }
        if (decision === 'approve') {
          if (data.status === 'executed') toast.success('✓ Action approved and executed via API')
          else toast.success('✓ Action approved — ready for manual execution')
        } else {
          toast.success('Action rejected')
        }
        router.refresh()
      } catch {
        toast.error('Failed to respond — try again')
      }
    })
  }

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4 hover:border-gray-300 transition-colors">
      {/* Header row */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3">
          <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${meta.color}`}>
            {meta.icon}
          </div>
          <div>
            <p className="text-sm font-semibold text-gray-900">{meta.label}</p>
            {entityName && (
              <p className="text-sm text-gray-500 truncate max-w-[260px]">{entityName}</p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${PLATFORM_COLORS[action.platform] ?? 'bg-gray-100 text-gray-600'}`}>
            {action.platform?.toUpperCase()}
          </span>
          {action.triggered_by && action.triggered_by !== 'dashboard_user' && (
            <span className="rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-500">
              {action.triggered_by.replace(/_/g, ' ')}
            </span>
          )}
          <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_COLORS[action.status] ?? 'bg-gray-100 text-gray-600'}`}>
            {action.status}
          </span>
        </div>
      </div>

      {/* Value change */}
      {(oldValue || suggestedValue) && (
        <div className="mt-3 flex items-center gap-2 rounded-lg bg-gray-50 px-3 py-2 text-sm">
          {oldValue && <span className="font-mono text-gray-400 line-through">{oldValue}</span>}
          {oldValue && suggestedValue && <span className="text-gray-400">→</span>}
          {suggestedValue && <span className="font-mono font-semibold text-gray-800">{suggestedValue}</span>}
        </div>
      )}

      {/* Description */}
      {description && (
        <p className="mt-2.5 text-sm text-gray-600 leading-relaxed">{description}</p>
      )}

      {/* Footer */}
      <div className="mt-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-1 text-xs text-gray-400">
          <Clock className="h-3.5 w-3.5" />
          <span>{timeAgo(action.ts)}</span>
        </div>

        {action.status === 'pending' ? (
          <div className="flex gap-2">
            <button
              onClick={() => respond('approve')}
              disabled={isPending}
              className="flex items-center gap-1.5 rounded-lg bg-green-600 px-4 py-2 text-sm font-semibold text-white hover:bg-green-700 disabled:opacity-50 transition-colors"
            >
              {isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
              Approve
            </button>
            <button
              onClick={() => respond('reject')}
              disabled={isPending}
              className="flex items-center gap-1.5 rounded-lg border border-red-200 bg-white px-3 py-2 text-sm font-semibold text-red-600 hover:bg-red-50 disabled:opacity-50 transition-colors"
            >
              <X className="h-4 w-4" />
              Reject
            </button>
          </div>
        ) : (
          <span className="text-xs text-gray-400">
            {action.executed_at ? `Executed ${timeAgo(action.executed_at)}` : action.status}
          </span>
        )}
      </div>
    </div>
  )
}
