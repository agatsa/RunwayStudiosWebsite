'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { RefreshCw, Send, CheckCircle2, AlertTriangle, Sparkles, Youtube, Megaphone, BarChart2, Globe } from 'lucide-react'
import { cn } from '@/lib/utils'
import BoldText from '@/components/ui/BoldText'

// ── Types ──────────────────────────────────────────────────────────────────────

interface GrowthAction {
  id: string
  platform: 'youtube' | 'meta' | 'google' | 'all'
  action_type: 'new_creative' | 'create_campaign' | 'keyword_addition' | 'review'
  title: string
  rationale: string
  source: string
  source_detail: string
  impact: 'high' | 'medium' | 'low'
  effort: 'low' | 'medium' | 'high'
  action_data?: Record<string, unknown>
}

interface GrowthOSPlan {
  plan_id: string | null
  generated_at: string | null
  actions: GrowthAction[]
  sources_used: Record<string, boolean>
}

interface Props {
  workspaceId: string
  initialPlan?: GrowthOSPlan | null
}

// ── Helpers ────────────────────────────────────────────────────────────────────

const PLATFORM_ICONS: Record<string, React.ElementType> = {
  youtube: Youtube,
  meta: Megaphone,
  google: BarChart2,
  all: Globe,
}

const PLATFORM_COLORS: Record<string, string> = {
  youtube: 'bg-red-100 text-red-700',
  meta: 'bg-blue-100 text-blue-700',
  google: 'bg-green-100 text-green-700',
  all: 'bg-purple-100 text-purple-700',
}

const IMPACT_COLORS: Record<string, string> = {
  high: 'text-red-600 bg-red-50 border-red-200',
  medium: 'text-amber-600 bg-amber-50 border-amber-200',
  low: 'text-slate-500 bg-slate-50 border-slate-200',
}

const IMPACT_DOTS: Record<string, string> = {
  high: 'bg-red-500',
  medium: 'bg-amber-400',
  low: 'bg-slate-400',
}

const EFFORT_LABELS: Record<string, string> = {
  low: 'Easy',
  medium: 'Medium effort',
  high: 'High effort',
}

const ACTION_TYPE_LABELS: Record<string, string> = {
  new_creative: '✨ New Creative',
  create_campaign: '🚀 Campaign',
  keyword_addition: '# Keywords',
  review: '👁 Review',
}

const SOURCE_LABELS: Record<string, string> = {
  yt_competitor_intel: 'YT Intel',
  meta_performance: 'Meta',
  google_ads: 'Google Ads',
  search_trends: 'Search',
  comment_intel: 'Comments',
  all: 'All Sources',
}

function timeAgo(isoStr: string | null): string {
  if (!isoStr) return 'never'
  const ms = Date.now() - new Date(isoStr).getTime()
  const mins = Math.floor(ms / 60000)
  if (mins < 2) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

// ── Source Badges ──────────────────────────────────────────────────────────────

function SourceBadges({ sources }: { sources: Record<string, boolean> }) {
  const SOURCE_DISPLAY: [string, string][] = [
    ['yt_competitor_intel', 'YouTube Intel'],
    ['meta_performance', 'Meta'],
    ['google_ads', 'Google'],
    ['yt_growth_recipe', 'Growth Recipe'],
    ['competitor_auction', 'Auction Intel'],
    ['search_trends', 'Search Trends'],
    ['comment_intel', 'Comments'],
  ]

  return (
    <div className="flex flex-wrap gap-2 text-xs">
      {SOURCE_DISPLAY.map(([key, label]) => {
        const has = sources[key]
        return (
          <span
            key={key}
            className={cn(
              'inline-flex items-center gap-1 rounded-full px-2.5 py-1 font-medium border',
              has
                ? 'bg-green-50 text-green-700 border-green-200'
                : 'bg-gray-50 text-gray-400 border-gray-200',
            )}
          >
            <span className={cn('h-1.5 w-1.5 rounded-full', has ? 'bg-green-500' : 'bg-gray-300')} />
            {label}
          </span>
        )
      })}
    </div>
  )
}

// ── Action Card ────────────────────────────────────────────────────────────────

function ActionCard({
  action,
  sent,
  onSend,
}: {
  action: GrowthAction
  sent: boolean
  onSend: (action: GrowthAction) => void
}) {
  const PlatformIcon = PLATFORM_ICONS[action.platform] ?? Globe

  return (
    <div className="rounded-xl border bg-white p-4 shadow-sm hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          {/* Platform + action type badges */}
          <div className="flex items-center gap-2 mb-2 flex-wrap">
            <span className={cn('inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide', PLATFORM_COLORS[action.platform])}>
              <PlatformIcon className="h-3 w-3" />
              {action.platform.toUpperCase()}
            </span>
            <span className="rounded-md bg-gray-100 px-2 py-0.5 text-[11px] text-gray-600 font-medium">
              {ACTION_TYPE_LABELS[action.action_type] ?? action.action_type}
            </span>
          </div>

          {/* Title */}
          <h3 className="text-sm font-semibold text-gray-900 leading-tight mb-1.5">
            <BoldText text={action.title} />
          </h3>

          {/* Rationale */}
          <p className="text-xs text-gray-600 leading-relaxed mb-2">
            <BoldText text={action.rationale} />
          </p>

          {/* Source detail */}
          {action.source_detail && (
            <p className="text-[11px] text-gray-400 mb-3">
              📍 {SOURCE_LABELS[action.source] ?? action.source} — {action.source_detail}
            </p>
          )}

          {/* Effort */}
          <p className="text-[11px] text-gray-500">
            Effort: <span className="font-medium text-gray-700">{EFFORT_LABELS[action.effort] ?? action.effort}</span>
          </p>
        </div>

        {/* Send button */}
        <div className="shrink-0">
          {sent ? (
            <span className="inline-flex items-center gap-1.5 rounded-lg bg-green-50 px-3 py-2 text-xs font-semibold text-green-700 border border-green-200">
              <CheckCircle2 className="h-3.5 w-3.5" />
              In Queue
            </span>
          ) : (
            <button
              onClick={() => onSend(action)}
              className="inline-flex items-center gap-1.5 rounded-lg bg-gray-900 px-3 py-2 text-xs font-semibold text-white hover:bg-gray-700 transition-colors"
            >
              <Send className="h-3.5 w-3.5" />
              Send
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Impact Section ─────────────────────────────────────────────────────────────

function ImpactSection({
  impact,
  actions,
  sentIds,
  onSend,
}: {
  impact: 'high' | 'medium' | 'low'
  actions: GrowthAction[]
  sentIds: Set<string>
  onSend: (action: GrowthAction) => void
}) {
  if (actions.length === 0) return null

  const labels = { high: 'HIGH IMPACT', medium: 'MEDIUM IMPACT', low: 'LOW IMPACT' }
  const dotColor = IMPACT_DOTS[impact]

  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <span className={cn('h-2 w-2 rounded-full shrink-0', dotColor)} />
        <span className="text-[11px] font-bold uppercase tracking-widest text-gray-500">
          {labels[impact]}
        </span>
        <div className="flex-1 h-px bg-gray-100" />
        <span className="text-[11px] text-gray-400">{actions.length} action{actions.length !== 1 ? 's' : ''}</span>
      </div>
      <div className="space-y-3">
        {actions.map(a => (
          <ActionCard key={a.id} action={a} sent={sentIds.has(a.id)} onSend={onSend} />
        ))}
      </div>
    </div>
  )
}

// ── Main Panel ─────────────────────────────────────────────────────────────────

export default function GrowthOSPanel({ workspaceId, initialPlan }: Props) {
  const [plan, setPlan] = useState<GrowthOSPlan | null>(initialPlan ?? null)
  const [generating, setGenerating] = useState(false)
  const [sending, setSending] = useState(false)
  const [sentIds, setSentIds] = useState<Set<string>>(new Set())
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<NodeJS.Timeout | null>(null)

  const fetchLatest = useCallback(async () => {
    try {
      const res = await fetch(`/api/growth-os/latest?workspace_id=${workspaceId}`, { cache: 'no-store' })
      if (!res.ok) return
      const data: GrowthOSPlan = await res.json()
      setPlan(data)
      return data
    } catch {
      return null
    }
  }, [workspaceId])

  // Initial load if no initialPlan
  useEffect(() => {
    if (!initialPlan || !initialPlan.plan_id) {
      fetchLatest()
    }
  }, [initialPlan, fetchLatest])

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  const startPolling = (prevGeneratedAt: string | null) => {
    stopPolling()
    pollRef.current = setInterval(async () => {
      const data = await fetchLatest()
      if (data?.plan_id && data.generated_at !== prevGeneratedAt) {
        stopPolling()
        setGenerating(false)
      }
    }, 3000)
  }

  useEffect(() => () => stopPolling(), [])

  const handleRegenerate = async () => {
    setGenerating(true)
    setError(null)
    const prevAt = plan?.generated_at ?? null
    try {
      const res = await fetch('/api/growth-os/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: workspaceId }),
      })
      if (res.status === 402) {
        const d = await res.json().catch(() => ({}))
        setError(`Insufficient credits — need ${d.required ?? 10} credits but have ${d.balance ?? 0}. Top up from the Billing page.`)
        setGenerating(false)
        return
      }
      startPolling(prevAt)
    } catch (e) {
      setError('Failed to start generation. Please try again.')
      setGenerating(false)
    }
  }

  const handleSend = async (action: GrowthAction) => {
    setSending(true)
    try {
      const res = await fetch('/api/growth-os/send-to-approvals', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: workspaceId, actions: [action] }),
      })
      if (res.ok) {
        setSentIds(prev => { const s = new Set(prev); s.add(action.id); return s })
      }
    } catch {
      // silent
    } finally {
      setSending(false)
    }
  }

  const handleSendAllHigh = async () => {
    if (!plan) return
    const highActions = plan.actions.filter(a => a.impact === 'high' && !sentIds.has(a.id))
    if (highActions.length === 0) return
    setSending(true)
    try {
      const res = await fetch('/api/growth-os/send-to-approvals', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: workspaceId, actions: highActions }),
      })
      if (res.ok) {
        setSentIds(prev => { const s = new Set(prev); highActions.forEach(a => s.add(a.id)); return s })
      }
    } catch {
      // silent
    } finally {
      setSending(false)
    }
  }

  // Grouped actions
  const highActions = plan?.actions.filter(a => a.impact === 'high') ?? []
  const mediumActions = plan?.actions.filter(a => a.impact === 'medium') ?? []
  const lowActions = plan?.actions.filter(a => a.impact === 'low') ?? []
  const totalActions = plan?.actions.length ?? 0
  const unsentHigh = highActions.filter(a => !sentIds.has(a.id))
  const hasAnySent = sentIds.size > 0

  return (
    <div className="space-y-6">

      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Sparkles className="h-5 w-5 text-amber-500" />
            <h1 className="text-xl font-bold text-gray-900">Growth OS — Command Center</h1>
          </div>
          {plan?.plan_id ? (
            <p className="text-sm text-gray-500">
              {totalActions} action{totalActions !== 1 ? 's' : ''} ·{' '}
              {highActions.length} High Impact ·{' '}
              Generated {timeAgo(plan.generated_at)}
            </p>
          ) : (
            <p className="text-sm text-gray-400">No plan generated yet</p>
          )}
        </div>
        <button
          onClick={handleRegenerate}
          disabled={generating}
          className="inline-flex items-center gap-2 rounded-xl bg-amber-500 px-4 py-2 text-sm font-semibold text-white hover:bg-amber-400 disabled:opacity-60 transition-colors"
        >
          <RefreshCw className={cn('h-4 w-4', generating && 'animate-spin')} />
          {generating ? 'Generating…' : 'Regenerate'}
          {!generating && <span className="ml-1 rounded-full bg-amber-400 px-2 py-0.5 text-[10px] font-semibold">10 credits</span>}
        </button>
      </div>

      {/* ── Source Badges ───────────────────────────────────────────────────── */}
      {plan?.sources_used && Object.keys(plan.sources_used).length > 0 && (
        <div className="rounded-xl border bg-white p-4">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Intelligence Sources</p>
          <SourceBadges sources={plan.sources_used} />
        </div>
      )}

      {/* ── Error ───────────────────────────────────────────────────────────── */}
      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 flex items-center gap-2 text-sm text-red-700">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      {/* ── Generating state ─────────────────────────────────────────────────── */}
      {generating && (
        <div className="rounded-xl border bg-amber-50 border-amber-200 p-6 text-center">
          <RefreshCw className="h-8 w-8 text-amber-500 animate-spin mx-auto mb-3" />
          <p className="text-sm font-semibold text-amber-800">Synthesising all intelligence sources…</p>
          <p className="text-xs text-amber-600 mt-1">Claude is analysing YouTube, Meta, Google, and more. This takes ~30–60 seconds.</p>
        </div>
      )}

      {/* ── Empty state ──────────────────────────────────────────────────────── */}
      {!generating && totalActions === 0 && (
        <div className="rounded-xl border bg-white p-10 text-center">
          <Sparkles className="h-10 w-10 text-amber-300 mx-auto mb-4" />
          <h3 className="text-base font-semibold text-gray-700 mb-2">No plan generated yet</h3>
          <p className="text-sm text-gray-500 max-w-md mx-auto mb-4">
            Complete the YouTube Competitor Analysis first for richer insights, then click{' '}
            <strong>Regenerate</strong> to synthesise all intelligence into an action plan.
          </p>
          <button
            onClick={handleRegenerate}
            className="inline-flex items-center gap-2 rounded-xl bg-amber-500 px-5 py-2.5 text-sm font-semibold text-white hover:bg-amber-400 transition-colors"
          >
            <Sparkles className="h-4 w-4" />
            Generate Action Plan
            <span className="ml-1 rounded-full bg-amber-400 px-2 py-0.5 text-[10px] font-semibold">10 credits</span>
          </button>
        </div>
      )}

      {/* ── Action sections ──────────────────────────────────────────────────── */}
      {!generating && totalActions > 0 && (
        <div className="space-y-8">
          <ImpactSection impact="high" actions={highActions} sentIds={sentIds} onSend={handleSend} />
          <ImpactSection impact="medium" actions={mediumActions} sentIds={sentIds} onSend={handleSend} />
          <ImpactSection impact="low" actions={lowActions} sentIds={sentIds} onSend={handleSend} />
        </div>
      )}

      {/* ── Footer bulk action ────────────────────────────────────────────────── */}
      {!generating && unsentHigh.length > 0 && (
        <div className="rounded-xl border bg-gray-50 p-4 flex items-center justify-between gap-4">
          <div>
            <p className="text-sm font-semibold text-gray-800">
              Send all {unsentHigh.length} High-Impact action{unsentHigh.length !== 1 ? 's' : ''} to Approvals
            </p>
            <p className="text-xs text-gray-500">They'll appear as pending approvals for your team to execute</p>
          </div>
          <button
            onClick={handleSendAllHigh}
            disabled={sending}
            className="inline-flex items-center gap-2 rounded-xl bg-red-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-red-500 disabled:opacity-60 transition-colors shrink-0"
          >
            <Send className="h-4 w-4" />
            {sending ? 'Sending…' : 'Send All High-Impact'}
          </button>
        </div>
      )}

      {hasAnySent && !generating && (
        <p className="text-center text-xs text-green-600 font-medium">
          ✓ {sentIds.size} action{sentIds.size !== 1 ? 's' : ''} added to the Approvals queue
        </p>
      )}
    </div>
  )
}
