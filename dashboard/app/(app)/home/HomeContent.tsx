'use client'

import { useEffect, useState } from 'react'
import { useSearchParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import {
  Sparkles, BarChart2, Target, Brain, Settings,
  TrendingUp, ArrowRight, Loader2, AlertTriangle,
  CheckCircle2, Upload, Zap, RefreshCw,
} from 'lucide-react'
import { cn } from '@/lib/utils'

interface Opportunity {
  action_type: string
  title: string
  detail: string
  expected_impact: 'High' | 'Medium' | 'Low'
  platform: string
  entity_name?: string
  suggested_value?: string
}

interface DailyBrief {
  opportunities: Opportunity[]
  generated_at: string | null
  cached: boolean
  brief_text?: string
}

interface KpiSummary {
  spend: number
  clicks: number
  roas: number
  impressions: number
}

interface GrowthOSLatest {
  status?: string
  generated_at?: string
  actions?: { priority: string }[]
  relevant_modules?: string[]
}

interface PendingAction {
  id: string
  action_type: string
  description: string
  platform: string
  entity_name: string
  expected_impact?: string
}

const IMPACT_COLORS: Record<string, string> = {
  High: 'bg-red-100 text-red-600',
  Medium: 'bg-yellow-100 text-yellow-700',
  Low: 'bg-gray-100 text-gray-600',
}

const PLATFORM_COLORS: Record<string, string> = {
  meta: 'bg-blue-100 text-blue-700',
  google: 'bg-green-100 text-green-700',
  youtube: 'bg-red-100 text-red-700',
  all: 'bg-violet-100 text-violet-700',
}

function fmt(n: number | null | undefined, prefix = '') {
  if (n == null || isNaN(n)) return `${prefix}0`
  if (n >= 100_000) return `${prefix}${(n / 100_000).toFixed(1)}L`
  if (n >= 1_000) return `${prefix}${(n / 1_000).toFixed(1)}K`
  return `${prefix}${n.toLocaleString('en-IN')}`
}

export default function HomeContent() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const wsId = searchParams.get('ws') ?? ''

  const [brief, setBrief] = useState<DailyBrief | null>(null)
  const [briefLoading, setBriefLoading] = useState(false)
  const [kpi, setKpi] = useState<KpiSummary | null>(null)
  const [gos, setGos] = useState<GrowthOSLatest | null>(null)
  const [pending, setPending] = useState<PendingAction[]>([])

  // Greeting
  const hour = new Date().getHours()
  const greeting = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'

  useEffect(() => {
    if (!wsId) return
    // Fetch all data in parallel
    const fetches = [
      fetch(`/api/ai/daily-brief?workspace_id=${wsId}`)
        .then(r => r.ok ? r.json() : null)
        .then(d => setBrief(d)),
      fetch(`/api/kpi/summary?workspace_id=${wsId}&days=7`)
        .then(r => r.ok ? r.json() : null)
        .then(d => setKpi(d?.summary ?? null)),
      fetch(`/api/growth-os/latest?workspace_id=${wsId}`)
        .then(r => r.ok ? r.json() : null)
        .then(d => setGos(d)),
      fetch(`/api/actions/list?workspace_id=${wsId}&status=pending&limit=5`)
        .then(r => r.ok ? r.json() : null)
        .then(d => setPending(d?.actions ?? [])),
    ]
    Promise.all(fetches).catch(() => {})
  }, [wsId])

  const refreshBrief = async () => {
    if (!wsId || briefLoading) return
    setBriefLoading(true)
    try {
      const r = await fetch(`/api/ai/daily-brief?workspace_id=${wsId}&refresh=1`)
      if (r.ok) setBrief(await r.json())
    } finally {
      setBriefLoading(false)
    }
  }

  if (!wsId) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-gray-500">No workspace selected.</p>
      </div>
    )
  }

  const topOpps = brief?.opportunities?.slice(0, 3) ?? []
  const highCount = brief?.opportunities?.filter(o => o.expected_impact === 'High').length ?? 0
  const planReady = gos?.status === 'completed'
  const hasPending = pending.length > 0

  return (
    <div className="mx-auto max-w-3xl space-y-6 py-4 px-2">

      {/* ── Greeting ── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">{greeting} 👋</h1>
          <p className="text-sm text-gray-500 mt-0.5">Here&apos;s what ARIA sees today</p>
        </div>
        <button
          onClick={refreshBrief}
          disabled={briefLoading}
          className="flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50 transition-colors disabled:opacity-50"
        >
          <RefreshCw className={cn('h-3.5 w-3.5', briefLoading && 'animate-spin')} />
          Refresh brief
        </button>
      </div>

      {/* ── KPI strip ── */}
      {kpi ? (
        <div className="grid grid-cols-3 gap-3">
          <div className="rounded-xl border border-gray-100 bg-white p-4">
            <p className="text-[11px] font-medium uppercase tracking-wide text-gray-400">Spend (7d)</p>
            <p className="mt-1 text-lg font-bold text-gray-900">₹{fmt(kpi.spend)}</p>
          </div>
          <div className="rounded-xl border border-gray-100 bg-white p-4">
            <p className="text-[11px] font-medium uppercase tracking-wide text-gray-400">ROAS (7d)</p>
            <p className={cn('mt-1 text-lg font-bold', (kpi.roas ?? 0) >= 2.5 ? 'text-green-600' : (kpi.roas ?? 0) > 0 ? 'text-yellow-600' : 'text-gray-900')}>
              {(kpi.roas ?? 0) > 0 ? `${kpi.roas!.toFixed(2)}x` : '—'}
            </p>
          </div>
          <div className="rounded-xl border border-gray-100 bg-white p-4">
            <p className="text-[11px] font-medium uppercase tracking-wide text-gray-400">Clicks (7d)</p>
            <p className="mt-1 text-lg font-bold text-gray-900">{fmt(kpi.clicks)}</p>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-3">
          {[0, 1, 2].map(i => (
            <div key={i} className="rounded-xl border border-gray-100 bg-gray-50 p-4 animate-pulse h-16" />
          ))}
        </div>
      )}

      {/* ── Today's Growth Actions (ARIA brief) ── */}
      <div className="rounded-xl border border-amber-200 bg-gradient-to-br from-amber-50/70 to-orange-50/30 overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-amber-100">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-amber-500">
              <Sparkles className="h-4 w-4 text-white" />
            </div>
            <div>
              <p className="text-sm font-bold text-gray-900">Today&apos;s Growth Actions</p>
              <p className="text-[11px] text-gray-400">
                {brief
                  ? brief.cached ? '⚡ Cached analysis' : '✨ Fresh analysis'
                  : 'Loading...'}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {highCount > 0 && (
              <span className="rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-bold text-red-600">
                {highCount} High
              </span>
            )}
            {brief?.opportunities?.length ? (
              <span className="text-[11px] text-gray-400">{brief.opportunities.length} actions</span>
            ) : null}
          </div>
        </div>

        <div className="px-5 py-4 space-y-3">
          {!brief && (
            <div className="flex items-center gap-3 py-2">
              <Loader2 className="h-4 w-4 animate-spin text-amber-500" />
              <p className="text-sm text-gray-500">ARIA is preparing today&apos;s brief...</p>
            </div>
          )}
          {brief?.brief_text && (
            <p className="text-sm text-gray-700 leading-relaxed border-l-2 border-amber-300 pl-3 italic">
              {brief.brief_text}
            </p>
          )}
          {topOpps.length === 0 && brief && (
            <div className="flex items-center gap-3 py-2">
              <CheckCircle2 className="h-4 w-4 text-green-500" />
              <p className="text-sm text-gray-600">No urgent actions today. Connect a platform to get personalised recommendations.</p>
            </div>
          )}
          {topOpps.map((opp, i) => (
            <div key={i} className="flex gap-3 rounded-xl border border-amber-100 bg-white p-4">
              <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-amber-500 text-[10px] font-bold text-white mt-0.5">
                {i + 1}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-start justify-between gap-2 flex-wrap">
                  <p className="text-sm font-semibold text-gray-900">{opp.title}</p>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${IMPACT_COLORS[opp.expected_impact] ?? 'bg-gray-100 text-gray-600'}`}>
                      {opp.expected_impact}
                    </span>
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${PLATFORM_COLORS[opp.platform] ?? 'bg-gray-100 text-gray-600'}`}>
                      {opp.platform?.toUpperCase()}
                    </span>
                  </div>
                </div>
                <p className="mt-1 text-xs text-gray-500 leading-relaxed">{opp.detail}</p>
              </div>
            </div>
          ))}
          {(brief?.opportunities?.length ?? 0) > 3 && (
            <Link
              href={`/plan?ws=${wsId}`}
              className="flex items-center justify-center gap-1.5 rounded-lg border border-amber-200 py-2 text-xs font-semibold text-amber-700 hover:bg-amber-50 transition-colors"
            >
              <ArrowRight className="h-3.5 w-3.5" />
              {(brief?.opportunities?.length ?? 0) - 3} more in Plan →
            </Link>
          )}
        </div>
      </div>

      {/* ── Pending approvals ── */}
      {hasPending && (
        <div className="rounded-xl border border-orange-200 bg-orange-50/40 overflow-hidden">
          <div className="flex items-center justify-between px-5 py-3 border-b border-orange-100">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-orange-500" />
              <p className="text-sm font-semibold text-gray-800">{pending.length} action{pending.length !== 1 ? 's' : ''} waiting for your approval</p>
            </div>
            <Link href={`/plan?ws=${wsId}&tab=approvals`} className="text-xs font-medium text-orange-600 hover:underline">
              Review all →
            </Link>
          </div>
          <div className="px-5 py-3 space-y-2">
            {pending.slice(0, 3).map(a => (
              <div key={a.id} className="flex items-center gap-3">
                <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${PLATFORM_COLORS[a.platform] ?? 'bg-gray-100 text-gray-600'}`}>
                  {a.platform?.toUpperCase()}
                </span>
                <p className="text-xs text-gray-700 flex-1 truncate">{a.description || a.action_type}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Section status grid ── */}
      <div className="grid grid-cols-2 gap-3">
        <Link href={`/data?ws=${wsId}`} className="group rounded-xl border border-gray-100 bg-white p-4 hover:border-brand-200 hover:shadow-sm transition-all">
          <div className="flex items-center gap-2 mb-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-50">
              <BarChart2 className="h-4 w-4 text-blue-500" />
            </div>
            <p className="text-sm font-semibold text-gray-900">Data</p>
          </div>
          <p className="text-xs text-gray-500">
            {kpi && kpi.spend > 0
              ? `₹${fmt(kpi.spend)} spend tracked`
              : 'Upload Meta/Google report'}
          </p>
          <div className="mt-2 flex items-center gap-1 text-[11px] font-medium text-brand-600 group-hover:gap-2 transition-all">
            {kpi && kpi.spend > 0 ? 'View reports' : 'Upload now'} <ArrowRight className="h-3 w-3" />
          </div>
        </Link>

        <Link href={`/plan?ws=${wsId}`} className="group rounded-xl border border-gray-100 bg-white p-4 hover:border-brand-200 hover:shadow-sm transition-all">
          <div className="flex items-center gap-2 mb-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-amber-50">
              <Target className="h-4 w-4 text-amber-500" />
            </div>
            <p className="text-sm font-semibold text-gray-900">Plan</p>
          </div>
          <p className="text-xs text-gray-500">
            {planReady
              ? `90-day strategy ready · ${gos?.actions?.length ?? 0} actions`
              : 'Run ARIA to get your 90-day plan'}
          </p>
          <div className="mt-2 flex items-center gap-1 text-[11px] font-medium text-brand-600 group-hover:gap-2 transition-all">
            {planReady ? 'View plan' : 'Generate plan'} <ArrowRight className="h-3 w-3" />
          </div>
        </Link>

        <Link href={`/intel?ws=${wsId}`} className="group rounded-xl border border-gray-100 bg-white p-4 hover:border-brand-200 hover:shadow-sm transition-all">
          <div className="flex items-center gap-2 mb-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-purple-50">
              <Brain className="h-4 w-4 text-purple-500" />
            </div>
            <p className="text-sm font-semibold text-gray-900">Intel</p>
          </div>
          <p className="text-xs text-gray-500">Competitor analysis, LP audit, brand insights</p>
          <div className="mt-2 flex items-center gap-1 text-[11px] font-medium text-brand-600 group-hover:gap-2 transition-all">
            View intel <ArrowRight className="h-3 w-3" />
          </div>
        </Link>

        <Link href={`/setup?ws=${wsId}`} className="group rounded-xl border border-gray-100 bg-white p-4 hover:border-brand-200 hover:shadow-sm transition-all">
          <div className="flex items-center gap-2 mb-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gray-50">
              <Settings className="h-4 w-4 text-gray-500" />
            </div>
            <p className="text-sm font-semibold text-gray-900">Setup</p>
          </div>
          <p className="text-xs text-gray-500">Connect accounts, products, team &amp; billing</p>
          <div className="mt-2 flex items-center gap-1 text-[11px] font-medium text-brand-600 group-hover:gap-2 transition-all">
            Manage setup <ArrowRight className="h-3 w-3" />
          </div>
        </Link>
      </div>

      {/* ── Upload nudge (if no data) ── */}
      {kpi && kpi.spend === 0 && (
        <div className="flex items-start gap-3 rounded-xl border border-dashed border-gray-300 bg-gray-50 p-4">
          <Upload className="h-4 w-4 text-gray-400 mt-0.5 shrink-0" />
          <div>
            <p className="text-sm font-medium text-gray-700">Upload this week&apos;s ad report</p>
            <p className="text-xs text-gray-500 mt-0.5">Upload your Meta or Google Ads Excel export from Ads Manager to unlock ARIA&apos;s insights.</p>
            <Link href={`/data?ws=${wsId}&tab=upload`} className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-brand-600 hover:underline">
              Go to Data <ArrowRight className="h-3 w-3" />
            </Link>
          </div>
        </div>
      )}

    </div>
  )
}
