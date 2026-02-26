'use client'

import { useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { Check, X, Loader2, PauseCircle, Sparkles, MapPin, Hash, Target, Eye, Clock, Rocket } from 'lucide-react'
import type { ActionRow } from '@/lib/types'

interface Props {
  action: ActionRow
}

const ACTION_META: Record<string, { icon: React.ReactNode; label: string; color: string }> = {
  increase_budget:      { icon: <span className="text-2xl">💰</span>, label: 'Increase Budget',    color: 'bg-green-100 text-green-700' },
  reduce_budget:        { icon: <span className="text-2xl">📉</span>, label: 'Reduce Budget',     color: 'bg-orange-100 text-orange-700' },
  pause_campaign:       { icon: <PauseCircle className="h-7 w-7" />,  label: 'Pause Campaign',    color: 'bg-yellow-100 text-yellow-700' },
  new_creative:         { icon: <Sparkles className="h-7 w-7" />,     label: 'New Creative',      color: 'bg-purple-100 text-purple-700' },
  geographic_expansion: { icon: <MapPin className="h-7 w-7" />,       label: 'Geo Expansion',     color: 'bg-blue-100 text-blue-700' },
  keyword_addition:     { icon: <Hash className="h-7 w-7" />,         label: 'Add Keywords',      color: 'bg-indigo-100 text-indigo-700' },
  bid_adjustment:       { icon: <Target className="h-7 w-7" />,       label: 'Adjust Bids',       color: 'bg-cyan-100 text-cyan-700' },
  review:               { icon: <Eye className="h-7 w-7" />,          label: 'Review',            color: 'bg-gray-100 text-gray-700' },
  ai_brief:             { icon: <span className="text-2xl">✨</span>,  label: 'AI Opportunity',   color: 'bg-amber-100 text-amber-700' },
  create_campaign:      { icon: <Rocket className="h-7 w-7" />,       label: 'Create Campaign',   color: 'bg-indigo-100 text-indigo-700' },
}

const PLATFORM_COLORS: Record<string, string> = {
  meta:    'bg-blue-100 text-blue-700',
  google:  'bg-green-100 text-green-700',
  youtube: 'bg-red-100 text-red-700',
  all:     'bg-violet-100 text-violet-700',
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

// ── Campaign plan detail card (shown for create_campaign action type) ─────────
function CampaignPlanDetail({ newValue, platform }: { newValue: unknown; platform?: string }) {
  let nv: Record<string, unknown> = {}
  try {
    if (typeof newValue === 'string') nv = JSON.parse(newValue)
    else if (newValue && typeof newValue === 'object') nv = newValue as Record<string, unknown>
  } catch { /* ignore */ }

  const concept = (nv.concept ?? {}) as Record<string, unknown>
  const brief   = (nv.brief   ?? {}) as Record<string, unknown>

  const headline           = concept.headline           as string | undefined
  const rationale          = concept.rationale          as string | undefined
  const format             = concept.recommended_format as string | undefined
  const channels           = (concept.recommended_channels ?? brief.channels) as string[] | undefined
  const budgetDaily        = (brief.budget_daily ?? concept.recommended_budget_daily) as number | undefined
  const duration           = brief.duration_days        as number | undefined
  const goal               = (brief.goal as string | undefined)?.replace('_', ' ')
  const kpi                = concept.kpi_targets        as { expected_roas?: number; expected_cpa?: number; expected_ctr?: number } | undefined
  const insights           = concept.growth_insights    as string[] | undefined
  const bodyCopy           = concept.body_copy          as string | undefined
  const hook               = concept.hook               as string | undefined
  const creativeDirection  = concept.creative_direction as string | undefined

  return (
    <div className="mt-4 space-y-3">
      {/* Headline */}
      {headline && (
        <div className="rounded-lg bg-indigo-50 border border-indigo-100 px-4 py-3">
          <p className="text-xs font-semibold uppercase text-indigo-400 mb-0.5">Campaign Headline</p>
          <p className="text-base font-bold text-indigo-900">{headline}</p>
        </div>
      )}

      {/* Brief summary row */}
      {(goal || budgetDaily || duration || channels?.length) && (
        <div className="flex flex-wrap gap-2">
          {goal        && <span className="rounded-full bg-gray-100 px-3 py-1 text-sm font-medium text-gray-600 capitalize">{goal}</span>}
          {budgetDaily && <span className="rounded-full bg-gray-100 px-3 py-1 text-sm font-medium text-gray-600">₹{Number(budgetDaily).toLocaleString()}/day</span>}
          {duration    && <span className="rounded-full bg-gray-100 px-3 py-1 text-sm font-medium text-gray-600">{duration} days</span>}
          {channels?.map(ch => (
            <span key={ch} className="rounded-full bg-blue-100 px-3 py-1 text-sm font-semibold text-blue-700 capitalize">{ch}</span>
          ))}
          {format      && <span className="rounded-full bg-purple-100 px-3 py-1 text-sm font-medium text-purple-700">{format}</span>}
        </div>
      )}

      {/* KPI targets */}
      {kpi && (
        <div className="grid grid-cols-3 gap-2">
          {[
            ['Target ROAS', kpi.expected_roas ? `${kpi.expected_roas}x` : '—'],
            ['Target CPA',  kpi.expected_cpa  ? `₹${kpi.expected_cpa}` : '—'],
            ['Target CTR',  kpi.expected_ctr  ? `${kpi.expected_ctr}%` : '—'],
          ].map(([l, v]) => (
            <div key={l} className="rounded-lg bg-gray-50 p-2.5 text-center">
              <p className="text-xs text-gray-400">{l}</p>
              <p className="text-sm font-bold text-indigo-700">{v}</p>
            </div>
          ))}
        </div>
      )}

      {/* Growth insights */}
      {insights && insights.length > 0 && (
        <div className="rounded-lg bg-gray-50 px-4 py-3">
          <p className="text-xs font-semibold uppercase text-gray-400 mb-2">Growth Insights</p>
          <ul className="space-y-1">
            {insights.map((ins, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
                <span className="text-indigo-400 shrink-0 mt-0.5">→</span>{ins}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Creative Brief — hook, body copy, creative direction */}
      {(hook || bodyCopy || creativeDirection) && (
        <div className="rounded-lg border border-gray-200 bg-white px-4 py-3 space-y-3">
          <p className="text-xs font-semibold uppercase text-gray-400">Creative Brief</p>
          {hook && (
            <div>
              <p className="text-xs font-medium text-gray-400 uppercase mb-0.5">Hook</p>
              <p className="text-sm font-medium text-gray-800 italic">&ldquo;{hook}&rdquo;</p>
            </div>
          )}
          {bodyCopy && (
            <div>
              <p className="text-xs font-medium text-gray-400 uppercase mb-0.5">Ad Copy</p>
              <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-line">{bodyCopy}</p>
            </div>
          )}
          {creativeDirection && (
            <div>
              <p className="text-xs font-medium text-gray-400 uppercase mb-0.5">Creative Direction</p>
              <p className="text-sm text-gray-600 leading-relaxed">{creativeDirection}</p>
            </div>
          )}
        </div>
      )}

      {/* Rationale */}
      {rationale && (
        <p className="text-sm text-gray-600 leading-relaxed">{rationale}</p>
      )}

      <div className="rounded-lg bg-amber-50 border border-amber-200 px-4 py-2.5 flex items-center gap-2">
        <Rocket className="h-4 w-4 text-amber-600 shrink-0" />
        <p className="text-sm text-amber-800 font-medium">
          {platform === 'google'
            ? <>Approving will create a <strong>PAUSED</strong> Performance Max campaign in Google Ads. No budget spent until you activate it.</>
            : <>Approving will create a <strong>PAUSED</strong> Campaign + Ad Set on Meta. No budget spent until you activate it.</>
          }
        </p>
      </div>
    </div>
  )
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

  const description    = ctx.description || ctx.detail || ''
  const entityName     = ctx.entity_name || action.entity_id || ''
  const suggestedValue = ctx.suggested_value || (action.new_value && typeof action.new_value === 'string' && !action.new_value.startsWith('{') ? action.new_value : '')
  const oldValue       = action.old_value && typeof action.old_value !== 'object' ? String(action.old_value) : ''

  // For create_campaign: headline is the entity name
  const isCampaignPlan = action.action_type === 'create_campaign'
  let planHeadline = ''
  if (isCampaignPlan) {
    try {
      const nv = typeof action.new_value === 'string' ? JSON.parse(action.new_value) : (action.new_value ?? {}) as Record<string, unknown>
      planHeadline = ((nv as Record<string, Record<string, string>>)?.concept?.headline ?? '') as string
    } catch { /* ignore */ }
  }
  const displayName = isCampaignPlan ? (planHeadline || 'Campaign Plan') : entityName

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
          const REDIRECT_LABELS: Record<string, string> = {
            '/campaign-planner': 'View in Campaign Planner →',
            '/google-ads':       'View in Google Ads →',
            '/campaigns':        'View in Campaigns →',
          }
          const linkLabel = data.redirect ? REDIRECT_LABELS[data.redirect] : null

          if (data.campaign_created && data.platform === 'google') {
            // create_campaign approved and executed on Google
            const name = data.campaign_name ? `"${data.campaign_name}"` : 'Campaign'
            toast.success(
              `✓ ${name} created in Google Ads (PAUSED PMax)`,
              {
                description: 'Performance Max campaign — activate in Google Ads when ready',
                action: { label: 'View in Campaigns →', onClick: () => router.push(data.redirect ?? '/campaigns') },
                duration: 7000,
              }
            )
          } else if (data.campaign_created) {
            // create_campaign was approved and executed on Meta
            const name = data.campaign_name ? `"${data.campaign_name}"` : 'Campaign'
            toast.success(
              `✓ ${name} + Ad Set created on Meta (PAUSED)`,
              {
                description: data.adset_name ? `Ad Set: "${data.adset_name}" · India 25–55` : undefined,
                action: { label: 'View in Campaigns →', onClick: () => router.push(data.redirect ?? '/campaigns') },
                duration: 7000,
              }
            )
          } else if (data.status === 'failed' && data.launch_error) {
            toast.error(`Campaign creation failed: ${data.launch_error}`, { duration: 8000 })
          } else if (data.status === 'executed' && data.execution_note) {
            toast.success(`✓ ${data.execution_note}`, { duration: 5000 })
          } else if (data.status === 'executed') {
            toast.success('✓ Budget / status updated', { duration: 4000 })
          } else if (data.execution_note) {
            toast.success('✓ Approved', { description: data.execution_note, duration: 6000 })
          } else if (data.redirect === '/campaign-planner') {
            toast.success(
              `✓ Campaign brief created by AI — ${linkLabel}`,
              { action: { label: linkLabel ?? 'Open', onClick: () => router.push(data.redirect) }, duration: 6000 }
            )
          } else if (data.redirect) {
            toast.success(
              `✓ Approved`,
              { action: { label: linkLabel ?? 'Open', onClick: () => router.push(data.redirect) }, duration: 6000 }
            )
          } else {
            toast.success('✓ Action approved')
          }
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
    <div className="rounded-xl border border-gray-200 bg-white p-6 hover:border-gray-300 transition-colors">
      {/* Header row */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-4">
          <div className={`flex h-14 w-14 shrink-0 items-center justify-center rounded-xl ${meta.color}`}>
            {meta.icon}
          </div>
          <div>
            <p className="text-xl font-semibold text-gray-900">{meta.label}</p>
            {displayName && (
              <p className="text-base text-gray-500 truncate max-w-[320px]">{displayName}</p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`rounded-full px-3 py-1 text-sm font-medium ${PLATFORM_COLORS[action.platform] ?? 'bg-gray-100 text-gray-600'}`}>
            {action.platform?.toUpperCase()}
          </span>
          {action.triggered_by && action.triggered_by !== 'dashboard_user' && (
            <span className="rounded-full bg-gray-100 px-3 py-1 text-sm font-medium text-gray-500">
              {action.triggered_by.replace(/_/g, ' ')}
            </span>
          )}
          <span className={`rounded-full px-3 py-1 text-sm font-medium ${STATUS_COLORS[action.status] ?? 'bg-gray-100 text-gray-600'}`}>
            {action.status}
          </span>
        </div>
      </div>

      {/* Campaign plan detail — replaces generic description for create_campaign */}
      {isCampaignPlan ? (
        <CampaignPlanDetail newValue={action.new_value} platform={action.platform} />
      ) : (
        <>
          {/* Value change */}
          {(oldValue || suggestedValue) && (
            <div className="mt-4 flex items-center gap-3 rounded-lg bg-gray-50 px-4 py-3 text-base">
              {oldValue && <span className="font-mono text-gray-400 line-through">{oldValue}</span>}
              {oldValue && suggestedValue && <span className="text-gray-400">→</span>}
              {suggestedValue && <span className="font-mono font-semibold text-gray-800">{suggestedValue}</span>}
            </div>
          )}
          {description && (
            <p className="mt-3 text-base text-gray-600 leading-relaxed">{description}</p>
          )}
        </>
      )}

      {/* Footer */}
      <div className="mt-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-1.5 text-sm text-gray-400">
          <Clock className="h-4 w-4" />
          <span>{timeAgo(action.ts)}</span>
        </div>

        {action.status === 'pending' ? (
          <div className="flex gap-3">
            <button
              onClick={() => respond('approve')}
              disabled={isPending}
              className="flex items-center gap-2 rounded-lg bg-green-600 px-6 py-2.5 text-base font-semibold text-white hover:bg-green-700 disabled:opacity-50 transition-colors"
            >
              {isPending ? <Loader2 className="h-5 w-5 animate-spin" /> : <Check className="h-5 w-5" />}
              {isCampaignPlan
                ? (action.platform === 'google' ? 'Approve & Launch on Google' : 'Approve & Launch on Meta')
                : 'Approve'}
            </button>
            <button
              onClick={() => respond('reject')}
              disabled={isPending}
              className="flex items-center gap-2 rounded-lg border border-red-200 bg-white px-5 py-2.5 text-base font-semibold text-red-600 hover:bg-red-50 disabled:opacity-50 transition-colors"
            >
              <X className="h-5 w-5" />
              Reject
            </button>
          </div>
        ) : (
          <span className="text-sm text-gray-400">
            {action.executed_at ? `Executed ${timeAgo(action.executed_at)}` : action.status}
          </span>
        )}
      </div>
    </div>
  )
}
