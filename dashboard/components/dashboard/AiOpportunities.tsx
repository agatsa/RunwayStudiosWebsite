'use client'

import { useState, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { ArrowRight, TrendingUp, PauseCircle, Sparkles, MapPin, Hash, Target, Loader2 } from 'lucide-react'

interface Opportunity {
  action_type: string
  title: string
  detail: string
  expected_impact: 'High' | 'Medium' | 'Low'
  platform: string
  entity_name?: string
  suggested_value?: string
}

interface Props {
  opportunities: Opportunity[]
  workspaceId: string
  generatedAt: string | null
  cached: boolean
}

const ACTION_ICONS: Record<string, React.ReactNode> = {
  increase_budget:      <span className="text-base">💰</span>,
  reduce_budget:        <span className="text-base">📉</span>,
  pause_campaign:       <PauseCircle className="h-4 w-4" />,
  new_creative:         <Sparkles className="h-4 w-4" />,
  geographic_expansion: <MapPin className="h-4 w-4" />,
  keyword_addition:     <Hash className="h-4 w-4" />,
  bid_adjustment:       <Target className="h-4 w-4" />,
}

const PLATFORM_COLORS: Record<string, string> = {
  meta:    'bg-blue-100 text-blue-700',
  google:  'bg-green-100 text-green-700',
  youtube: 'bg-red-100 text-red-700',
  all:     'bg-violet-100 text-violet-700',
}

const IMPACT_COLORS: Record<string, string> = {
  High:   'bg-red-100 text-red-600',
  Medium: 'bg-yellow-100 text-yellow-700',
  Low:    'bg-gray-100 text-gray-600',
}

function OpportunityCard({ opp, index, workspaceId }: { opp: Opportunity; index: number; workspaceId: string }) {
  const [isPending, startTransition] = useTransition()
  const [created, setCreated] = useState(false)
  const router = useRouter()

  const createTask = () => {
    startTransition(async () => {
      try {
        const res = await fetch('/api/actions/create', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            workspace_id: workspaceId,
            platform: opp.platform === 'all' ? 'meta' : opp.platform,
            entity_id: opp.entity_name || 'ai_opportunity',
            entity_name: opp.entity_name || opp.title,
            entity_level: 'campaign',
            action_type: opp.action_type,
            description: opp.detail,
            suggested_value: opp.suggested_value || '',
            triggered_by: 'ai_brief',
          }),
        })
        if (!res.ok) throw new Error('Failed')
        setCreated(true)
        toast.success('Task added to Approvals queue', {
          action: { label: 'View', onClick: () => router.push(`/approvals?ws=${workspaceId}`) },
        })
      } catch {
        toast.error('Failed to create task')
      }
    })
  }

  return (
    <div className="flex gap-4 rounded-xl border border-amber-100 bg-white p-4 hover:border-amber-200 transition-colors">
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-amber-500 text-xs font-bold text-white mt-0.5">
        {index + 1}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-2">
            <span className="text-amber-600">{ACTION_ICONS[opp.action_type] ?? <TrendingUp className="h-4 w-4" />}</span>
            <p className="text-sm font-semibold text-gray-900">{opp.title}</p>
          </div>
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${IMPACT_COLORS[opp.expected_impact] ?? 'bg-gray-100 text-gray-600'}`}>
              {opp.expected_impact}
            </span>
            <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${PLATFORM_COLORS[opp.platform] ?? 'bg-gray-100 text-gray-600'}`}>
              {opp.platform.toUpperCase()}
            </span>
          </div>
        </div>
        <p className="mt-1.5 text-xs text-gray-500 leading-relaxed">{opp.detail}</p>
        {opp.entity_name && (
          <p className="mt-1 text-[10px] text-gray-400 truncate">Campaign: {opp.entity_name}</p>
        )}
        <div className="mt-3">
          {created ? (
            <span className="inline-flex items-center gap-1 text-xs font-medium text-green-600">
              ✓ Added to Approvals queue
            </span>
          ) : (
            <button
              onClick={createTask}
              disabled={isPending}
              className="inline-flex items-center gap-1.5 rounded-lg bg-amber-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-600 disabled:opacity-50 transition-colors"
            >
              {isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <ArrowRight className="h-3 w-3" />}
              Create Task
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

export default function AiOpportunities({ opportunities, workspaceId, generatedAt, cached }: Props) {
  if (!opportunities || opportunities.length === 0) {
    return (
      <div className="flex h-32 items-center justify-center rounded-xl border border-amber-100 bg-amber-50/30">
        <p className="text-sm text-gray-400">Connect a platform to get AI growth recommendations</p>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {opportunities.map((opp, i) => (
        <OpportunityCard key={i} opp={opp} index={i} workspaceId={workspaceId} />
      ))}
      {generatedAt && (
        <p className="text-[10px] text-gray-400 text-right">
          {cached ? '⚡ Cached · ' : '✨ Generated · '}
          {new Date(generatedAt).toLocaleString('en-IN', { dateStyle: 'short', timeStyle: 'short' })}
        </p>
      )}
    </div>
  )
}
