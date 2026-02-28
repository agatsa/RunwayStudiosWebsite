'use client'

import { useState, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import {
  ArrowRight, TrendingUp, PauseCircle, Sparkles,
  MapPin, Hash, Target, Loader2, ChevronDown, ChevronUp,
} from 'lucide-react'

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
  increase_budget:      <span className="text-base leading-none">💰</span>,
  reduce_budget:        <span className="text-base leading-none">📉</span>,
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

function OpportunityCard({
  opp,
  index,
  workspaceId,
}: {
  opp: Opportunity
  index: number
  workspaceId: string
}) {
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
    <div className="flex gap-3 rounded-xl border border-amber-100 bg-white p-4 hover:border-amber-200 transition-colors">
      <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-amber-500 text-[11px] font-bold text-white mt-0.5">
        {index + 1}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-2">
            <span className="text-amber-600">{ACTION_ICONS[opp.action_type] ?? <TrendingUp className="h-4 w-4" />}</span>
            <p className="text-sm font-semibold text-gray-900">{opp.title}</p>
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
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
  const [expanded, setExpanded] = useState(false)

  /* ── Empty state ── */
  if (!opportunities || opportunities.length === 0) {
    return (
      <div className="flex items-center gap-3 rounded-xl border border-amber-100 bg-amber-50/40 px-5 py-4">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-amber-100">
          <Sparkles className="h-4 w-4 text-amber-500" />
        </div>
        <div>
          <p className="text-sm font-semibold text-gray-700">Today&apos;s Growth Actions</p>
          <p className="text-xs text-gray-400">Connect a platform to receive AI growth recommendations</p>
        </div>
      </div>
    )
  }

  const highCount   = opportunities.filter(o => o.expected_impact === 'High').length
  const medCount    = opportunities.filter(o => o.expected_impact === 'Medium').length
  const first       = opportunities[0]
  const rest        = opportunities.slice(1)
  const timeLabel   = generatedAt
    ? new Date(generatedAt).toLocaleString('en-IN', { timeStyle: 'short' })
    : null

  return (
    <div className="rounded-xl border border-amber-200 bg-gradient-to-br from-amber-50/70 to-orange-50/30 overflow-hidden">

      {/* ── Header row (always visible, click to expand/collapse) ── */}
      <button
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center justify-between px-5 py-3.5 hover:bg-amber-50/60 transition-colors text-left"
      >
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-amber-500 shadow-sm">
            <Sparkles className="h-4 w-4 text-white" />
          </div>
          <div>
            <p className="text-sm font-bold text-gray-900 leading-tight">Today&apos;s Growth Actions</p>
            <p className="text-[11px] text-gray-400 leading-tight mt-0.5">
              {timeLabel
                ? `${cached ? '⚡ Cached' : '✨ Fresh analysis'} · ${timeLabel}`
                : 'AI-analysed from your live campaign data'}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {highCount > 0 && (
            <span className="rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-bold text-red-600">
              {highCount} High
            </span>
          )}
          {medCount > 0 && (
            <span className="rounded-full bg-yellow-100 px-2 py-0.5 text-[10px] font-bold text-yellow-700">
              {medCount} Med
            </span>
          )}
          <span className="text-[11px] text-gray-400">{opportunities.length} actions</span>
          {expanded
            ? <ChevronUp  className="h-4 w-4 text-amber-500 ml-1" />
            : <ChevronDown className="h-4 w-4 text-amber-500 ml-1" />}
        </div>
      </button>

      {/* ── First card — always visible ── */}
      <div className="px-5 pb-4">
        <OpportunityCard opp={first} index={0} workspaceId={workspaceId} />
      </div>

      {/* ── Rest — smooth slide open/close ── */}
      {rest.length > 0 && (
        <>
          <div
            className="overflow-hidden transition-all duration-300 ease-in-out"
            style={{ maxHeight: expanded ? `${rest.length * 220}px` : 0 }}
          >
            <div className="px-5 space-y-3 pb-4">
              {rest.map((opp, i) => (
                <OpportunityCard key={i + 1} opp={opp} index={i + 1} workspaceId={workspaceId} />
              ))}
            </div>
          </div>

          {/* Toggle strip */}
          <button
            onClick={() => setExpanded(e => !e)}
            className="w-full flex items-center justify-center gap-1.5 border-t border-amber-100 py-2.5 text-xs font-semibold text-blue-600 hover:bg-blue-50 transition-colors"
          >
            {expanded ? (
              <><ChevronUp className="h-3.5 w-3.5" />Show less</>
            ) : (
              <><ChevronDown className="h-3.5 w-3.5" />{rest.length} more action{rest.length !== 1 ? 's' : ''} — tap to expand</>
            )}
          </button>
        </>
      )}
    </div>
  )
}
