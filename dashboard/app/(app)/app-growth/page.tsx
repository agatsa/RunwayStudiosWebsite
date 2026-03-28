'use client'

import { useState, useEffect, useCallback, Suspense } from 'react'
import { useSearchParams } from 'next/navigation'
import {
  Smartphone, Star, Search, TrendingUp, Zap, BarChart2,
  Mail, PlayCircle, Megaphone, Plus, Trash2, RefreshCw,
  CheckCircle, AlertCircle, ExternalLink, ChevronDown, ChevronUp,
  Download, Globe, Loader2, Send, ArrowUp, ArrowDown, Clock,
  Minus, Activity, RotateCw,
} from 'lucide-react'
import { cn } from '@/lib/utils'

// ─── Types ────────────────────────────────────────────────────────────────────

interface AppStatus {
  connected: boolean
  app_name?: string
  bundle_id?: string
  app_store_url?: string
  play_store_url?: string
  has_asc?: boolean
  has_play?: boolean
  category?: string
  review_count?: number
  kw_count?: number
  installs_30d?: number
}

interface AppReview {
  id: string
  store: 'appstore' | 'playstore'
  review_id: string
  author: string
  rating: number
  title: string
  body: string
  version: string
  sentiment: string
  category: string
  suggested_reply: string
  replied: boolean
  review_date: string | null
}

interface AsoKeyword {
  id: string
  keyword: string
  store: string
  appstore_rank: number | null
  playstore_rank: number | null
  search_score: number | null
  notes: string
  checked_at: string | null
}

interface RankTrend {
  keyword_id: string
  keyword: string
  store: string
  current_rank: number | null
  previous_rank: number | null
  delta: number | null
}

interface InstallFunnel {
  total_installs: number
  total_spend: number
  cpi: number
  by_source: { source: string; installs: number; spend: number; cpi: number }[]
  by_campaign: { campaign: string; source: string; installs: number; spend: number; cpi: number }[]
  by_country: { country: string; installs: number }[]
  by_platform: { platform: string; installs: number }[]
  daily: { date: string; installs: number }[]
}

interface GrowthAction {
  id: number
  priority: 'high' | 'medium' | 'low'
  channel: string
  title: string
  description: string
  expected_impact: string
  effort: string
  timeframe: string
}

interface GrowthPlan {
  headline: string
  priority_score: number
  actions: GrowthAction[]
  aso_quick_wins: string[]
  review_action: string
  channel_recommendations: Record<string, string>
  '30_day_goal': string
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const CHANNEL_ICON: Record<string, React.ElementType> = {
  meta: Megaphone, google: BarChart2, google_uac: BarChart2,
  youtube: PlayCircle, email: Mail, aso: Search,
  reviews: Star, organic: Globe, default: Zap,
}

const PRIORITY_COLOR = {
  high: 'bg-red-100 text-red-700 border-red-200',
  medium: 'bg-amber-100 text-amber-700 border-amber-200',
  low: 'bg-gray-100 text-gray-600 border-gray-200',
}

function StarRow({ rating }: { rating: number }) {
  return (
    <span className="flex gap-0.5">
      {[1,2,3,4,5].map(i => (
        <Star key={i} className={cn('h-3 w-3', i <= rating ? 'fill-amber-400 text-amber-400' : 'text-gray-200')} />
      ))}
    </span>
  )
}

function RankBadge({ rank }: { rank: number | null }) {
  if (!rank) return <span className="text-gray-300">—</span>
  const color = rank <= 10 ? 'text-green-600 font-bold' : rank <= 50 ? 'text-amber-600 font-semibold' : 'text-gray-500'
  return <span className={color}>{rank}</span>
}

function TrendArrow({ delta }: { delta: number | null }) {
  if (delta === null || delta === undefined) return <span className="text-gray-300 text-xs">—</span>
  if (delta > 0) return (
    <span className="flex items-center gap-0.5 text-green-600 text-xs font-semibold">
      <ArrowUp className="h-3 w-3" />+{delta}
    </span>
  )
  if (delta < 0) return (
    <span className="flex items-center gap-0.5 text-red-500 text-xs font-semibold">
      <ArrowDown className="h-3 w-3" />{delta}
    </span>
  )
  return <span className="text-gray-400 text-xs"><Minus className="h-3 w-3 inline" /></span>
}

const TABS = [
  { id: 'overview',     label: 'Overview',     icon: Smartphone },
  { id: 'aso',          label: 'ASO',           icon: Search },
  { id: 'reviews',      label: 'Reviews',       icon: Star },
  { id: 'attribution',  label: 'Attribution',   icon: BarChart2 },
  { id: 'growth-plan',  label: 'Growth Plan',   icon: Zap },
] as const

type TabId = typeof TABS[number]['id']

// ─── Page shell ───────────────────────────────────────────────────────────────

export default function AppGrowthPage() {
  return (
    <Suspense fallback={<div className="flex h-64 items-center justify-center"><p className="text-sm text-gray-400">Loading...</p></div>}>
      <AppGrowthContent />
    </Suspense>
  )
}

function AppGrowthContent() {
  const searchParams = useSearchParams()
  const wsId = searchParams.get('ws') ?? searchParams.get('workspace_id') ?? ''
  const [tab, setTab] = useState<TabId>('overview')
  const [status, setStatus] = useState<AppStatus | null>(null)
  const [showConnect, setShowConnect] = useState(false)

  const loadStatus = useCallback(async () => {
    if (!wsId) return
    const r = await fetch(`/api/app-growth?workspace_id=${wsId}`)
    const d = await r.json()
    setStatus(d)
  }, [wsId])

  useEffect(() => { loadStatus() }, [loadStatus])

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b border-gray-100 px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-600">
              <Smartphone className="h-5 w-5 text-white" />
            </div>
            <div>
              <h1 className="text-base font-bold text-gray-900">
                {status?.app_name ?? 'App Growth'}
              </h1>
              <p className="text-xs text-gray-500">
                {status?.connected ? (status.category || 'App Store · Google Play') : 'Connect your app to get started'}
              </p>
            </div>
          </div>
          {status?.connected && (
            <button onClick={() => setShowConnect(true)}
              className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50">
              Edit App
            </button>
          )}
        </div>

        {/* Tabs */}
        <div className="flex gap-1 mt-4 -mb-px">
          {TABS.map(t => (
            <button key={t.id} onClick={() => setTab(t.id)}
              className={cn('flex items-center gap-1.5 px-3 py-2 text-xs font-medium border-b-2 transition-colors',
                tab === t.id
                  ? 'border-indigo-600 text-indigo-700'
                  : 'border-transparent text-gray-500 hover:text-gray-700')}>
              <t.icon className="h-3.5 w-3.5" />{t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      <div>
        {tab === 'overview'    && <OverviewTab wsId={wsId} status={status} onEdit={() => setShowConnect(true)} />}
        {tab === 'aso'         && <AsoTab wsId={wsId} status={status} />}
        {tab === 'reviews'     && <ReviewsTab wsId={wsId} status={status} />}
        {tab === 'attribution' && <AttributionTab wsId={wsId} />}
        {tab === 'growth-plan' && <GrowthPlanTab wsId={wsId} />}
      </div>

      {showConnect && (
        <ConnectModal
          wsId={wsId}
          existing={status}
          onClose={() => setShowConnect(false)}
          onSaved={() => { setShowConnect(false); loadStatus() }}
        />
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
// OVERVIEW TAB
// ═══════════════════════════════════════════════════════════════════════════════

function OverviewTab({ wsId, status, onEdit }: { wsId: string; status: AppStatus | null; onEdit: () => void }) {
  if (!status?.connected) {
    return (
      <div className="p-8">
        <div className="mx-auto max-w-lg rounded-2xl border-2 border-dashed border-gray-200 bg-white p-10 text-center">
          <Smartphone className="mx-auto h-12 w-12 text-gray-300 mb-4" />
          <h2 className="text-lg font-bold text-gray-800 mb-2">Connect your app</h2>
          <p className="text-sm text-gray-500 mb-6">
            Add your App Store & Google Play details to start tracking installs,
            reviews, and ASO performance across all your marketing channels.
          </p>
          <button onClick={onEdit}
            className="rounded-xl bg-indigo-600 px-6 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700">
            Get Started
          </button>
        </div>
      </div>
    )
  }

  const channelCards = [
    { icon: Megaphone, label: 'Meta Ads', desc: 'App Install campaigns', color: 'text-blue-600 bg-blue-50', href: `/campaigns?ws=${wsId}` },
    { icon: BarChart2, label: 'Google UAC', desc: 'Universal App Campaigns', color: 'text-green-600 bg-green-50', href: `/google-ads?ws=${wsId}` },
    { icon: PlayCircle, label: 'YouTube', desc: 'Demo & tutorial videos', color: 'text-red-600 bg-red-50', href: `/youtube?ws=${wsId}` },
    { icon: Mail, label: 'Email', desc: 'Install nudge campaigns', color: 'text-purple-600 bg-purple-50', href: `/email-intel?ws=${wsId}` },
    { icon: Search, label: 'ASO', desc: 'App store keywords', color: 'text-amber-600 bg-amber-50', href: `#` },
    { icon: Star, label: 'Reviews', desc: 'Ratings & sentiment', color: 'text-pink-600 bg-pink-50', href: `#` },
  ]

  return (
    <div className="p-6 space-y-6">
      {/* KPI row */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: 'Installs (30d)', value: status.installs_30d?.toLocaleString() ?? '0', icon: Download, color: 'text-indigo-600' },
          { label: 'Reviews', value: status.review_count?.toLocaleString() ?? '0', icon: Star, color: 'text-amber-600' },
          { label: 'ASO Keywords', value: status.kw_count?.toLocaleString() ?? '0', icon: Search, color: 'text-green-600' },
        ].map(k => (
          <div key={k.label} className="rounded-xl bg-white border border-gray-100 p-4 flex items-center gap-3">
            <div className={cn('flex h-10 w-10 items-center justify-center rounded-xl bg-gray-50', k.color)}>
              <k.icon className="h-5 w-5" />
            </div>
            <div>
              <p className="text-2xl font-bold text-gray-900">{k.value}</p>
              <p className="text-xs text-gray-500">{k.label}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Connection status */}
      <div className="grid grid-cols-2 gap-4">
        <div className={cn('rounded-xl border p-4 flex items-center gap-3',
          status.has_asc ? 'bg-green-50 border-green-200' : 'bg-gray-50 border-gray-200')}>
          <div className={cn('h-8 w-8 rounded-full flex items-center justify-center',
            status.has_asc ? 'bg-green-100' : 'bg-gray-200')}>
            <Smartphone className={cn('h-4 w-4', status.has_asc ? 'text-green-700' : 'text-gray-400')} />
          </div>
          <div>
            <p className="text-sm font-semibold text-gray-800">App Store Connect</p>
            <p className={cn('text-xs', status.has_asc ? 'text-green-700' : 'text-gray-400')}>
              {status.has_asc ? 'API connected — auto-sync enabled' : 'Not connected — manual reviews only'}
            </p>
          </div>
        </div>
        <div className={cn('rounded-xl border p-4 flex items-center gap-3',
          status.has_play ? 'bg-green-50 border-green-200' : 'bg-gray-50 border-gray-200')}>
          <div className={cn('h-8 w-8 rounded-full flex items-center justify-center',
            status.has_play ? 'bg-green-100' : 'bg-gray-200')}>
            <Download className={cn('h-4 w-4', status.has_play ? 'text-green-700' : 'text-gray-400')} />
          </div>
          <div>
            <p className="text-sm font-semibold text-gray-800">Google Play Developer</p>
            <p className={cn('text-xs', status.has_play ? 'text-green-700' : 'text-gray-400')}>
              {status.has_play ? 'Service account connected' : 'Not connected — manual reviews only'}
            </p>
          </div>
        </div>
      </div>

      {/* Channel grid */}
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-widest text-gray-400 mb-3">Growth Channels</h3>
        <div className="grid grid-cols-3 gap-3">
          {channelCards.map(c => (
            <a key={c.label} href={c.href}
              className="flex items-center gap-3 rounded-xl bg-white border border-gray-100 p-4 hover:border-indigo-200 transition-colors">
              <div className={cn('flex h-9 w-9 items-center justify-center rounded-lg', c.color)}>
                <c.icon className="h-4 w-4" />
              </div>
              <div>
                <p className="text-sm font-semibold text-gray-800">{c.label}</p>
                <p className="text-xs text-gray-500">{c.desc}</p>
              </div>
            </a>
          ))}
        </div>
      </div>

      {/* App store links */}
      <div className="rounded-xl bg-white border border-gray-100 p-4">
        <h3 className="text-sm font-semibold text-gray-800 mb-3">Store Listings</h3>
        <div className="flex gap-3">
          {status.app_store_url && (
            <a href={status.app_store_url} target="_blank" rel="noopener noreferrer"
              className="flex items-center gap-2 rounded-lg bg-black px-4 py-2 text-xs font-medium text-white hover:bg-gray-800">
              <Smartphone className="h-3.5 w-3.5" /> App Store <ExternalLink className="h-3 w-3 opacity-60" />
            </a>
          )}
          {status.play_store_url && (
            <a href={status.play_store_url} target="_blank" rel="noopener noreferrer"
              className="flex items-center gap-2 rounded-lg bg-green-600 px-4 py-2 text-xs font-medium text-white hover:bg-green-700">
              <Download className="h-3.5 w-3.5" /> Google Play <ExternalLink className="h-3 w-3 opacity-60" />
            </a>
          )}
        </div>
      </div>

      {/* Attribution webhook info */}
      <div className="rounded-xl bg-indigo-50 border border-indigo-100 p-4">
        <h3 className="text-sm font-semibold text-indigo-800 mb-1">Attribution Webhook</h3>
        <p className="text-xs text-indigo-600 mb-2">
          Point AppsFlyer / Adjust / Branch postback to this URL to track installs by channel:
        </p>
        <code className="block rounded bg-white border border-indigo-100 px-3 py-2 text-xs text-gray-700 break-all">
          {`https://agent-swarm-771420308292.asia-south1.run.app/app-growth/attribution/webhook?workspace_id=${wsId}`}
        </code>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
// ASO TAB — full keyword rank tracking + metadata optimizer
// ═══════════════════════════════════════════════════════════════════════════════

function AsoTab({ wsId, status }: { wsId: string; status: AppStatus | null }) {
  const [keywords, setKeywords] = useState<AsoKeyword[]>([])
  const [trends, setTrends] = useState<Record<string, RankTrend>>({})  // keyed by `${kwId}_${store}`
  const [newKw, setNewKw] = useState('')
  const [adding, setAdding] = useState(false)
  const [checkingRanks, setCheckingRanks] = useState(false)
  const [rankMsg, setRankMsg] = useState('')
  const [analyzeOpen, setAnalyzeOpen] = useState(false)
  const [analyzeForm, setAnalyzeForm] = useState({
    app_name: status?.app_name ?? '',
    subtitle: '', description: '', keywords_field: '',
    category: status?.category ?? '', store: 'appstore',
  })
  const [analyzing, setAnalyzing] = useState(false)
  const [asoResult, setAsoResult] = useState<any>(null)

  const loadKw = useCallback(async () => {
    const r = await fetch(`/api/app-growth/aso/keywords?workspace_id=${wsId}`)
    const d = await r.json()
    setKeywords(d.keywords ?? [])
  }, [wsId])

  const loadTrends = useCallback(async () => {
    const r = await fetch(`/api/app-growth/aso/rank-trend?workspace_id=${wsId}`)
    const d = await r.json()
    const map: Record<string, RankTrend> = {}
    for (const t of (d.trends ?? [])) {
      map[`${t.keyword_id}_${t.store}`] = t
    }
    setTrends(map)
  }, [wsId])

  useEffect(() => { loadKw(); loadTrends() }, [loadKw, loadTrends])

  const addKeyword = async () => {
    if (!newKw.trim()) return
    setAdding(true)
    await fetch('/api/app-growth/aso/keywords', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace_id: wsId, keyword: newKw.trim() }),
    })
    setNewKw('')
    await loadKw()
    setAdding(false)
  }

  const deleteKw = async (id: string) => {
    await fetch(`/api/app-growth/aso/keywords?id=${id}&workspace_id=${wsId}`, { method: 'DELETE' })
    setKeywords(prev => prev.filter(k => k.id !== id))
  }

  const checkAllRanks = async () => {
    setCheckingRanks(true)
    setRankMsg('')
    const r = await fetch('/api/app-growth/aso/check-ranks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace_id: wsId }),
    })
    const d = await r.json()
    setRankMsg(d.message ?? 'Check started')
    setCheckingRanks(false)
    // Reload after delay
    setTimeout(() => { loadKw(); loadTrends() }, 8000)
  }

  const runAnalysis = async () => {
    setAnalyzing(true)
    setAsoResult(null)
    const r = await fetch('/api/app-growth/aso/keywords', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...analyzeForm, workspace_id: wsId, action: 'analyze' }),
    })
    const d = await r.json()
    setAsoResult(d)
    setAnalyzing(false)
  }

  return (
    <div className="p-6 space-y-6">
      {/* Keyword tracker */}
      <div className="rounded-xl bg-white border border-gray-100 p-5">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-sm font-semibold text-gray-800">Keyword Rank Tracker</h3>
            <p className="text-xs text-gray-400 mt-0.5">
              App Store ranks via iTunes Search API (free) · Play Store via search scraper
            </p>
          </div>
          <div className="flex items-center gap-2">
            {rankMsg && (
              <span className="text-xs text-green-600 flex items-center gap-1">
                <CheckCircle className="h-3.5 w-3.5" />{rankMsg}
              </span>
            )}
            <button onClick={checkAllRanks} disabled={checkingRanks || keywords.length === 0}
              className="flex items-center gap-1.5 rounded-lg bg-amber-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-600 disabled:opacity-50">
              {checkingRanks ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Activity className="h-3.5 w-3.5" />}
              Check All Ranks
            </button>
          </div>
        </div>

        {/* Add input */}
        <div className="flex gap-2 mb-4">
          <input
            value={newKw}
            onChange={e => setNewKw(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && addKeyword()}
            placeholder="Add keyword (e.g. blood pressure monitor)"
            className="flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-indigo-400"
          />
          <button onClick={addKeyword} disabled={adding || !newKw.trim()}
            className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50">
            {adding ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
            Add
          </button>
        </div>

        {keywords.length === 0 ? (
          <p className="text-center text-sm text-gray-400 py-6">
            No keywords yet. Add keywords you want to rank for in the App Store / Play Store.
          </p>
        ) : (
          <div className="divide-y divide-gray-50">
            <div className="grid grid-cols-12 gap-2 pb-2 text-[10px] font-semibold uppercase tracking-wide text-gray-400">
              <span className="col-span-3">Keyword</span>
              <span className="col-span-2 text-center">App Store Rank</span>
              <span className="col-span-1 text-center">Trend</span>
              <span className="col-span-2 text-center">Play Store Rank</span>
              <span className="col-span-1 text-center">Trend</span>
              <span className="col-span-2 text-center text-gray-300">Last Checked</span>
              <span className="col-span-1"></span>
            </div>
            {keywords.map(kw => {
              const ascTrend = trends[`${kw.id}_appstore`]
              const gpTrend = trends[`${kw.id}_playstore`]
              return (
                <div key={kw.id} className="grid grid-cols-12 gap-2 items-center py-2.5 text-sm">
                  <span className="col-span-3 font-medium text-gray-800 truncate">{kw.keyword}</span>
                  <span className="col-span-2 text-center">
                    <RankBadge rank={kw.appstore_rank} />
                  </span>
                  <span className="col-span-1 flex justify-center">
                    <TrendArrow delta={ascTrend?.delta ?? null} />
                  </span>
                  <span className="col-span-2 text-center">
                    <RankBadge rank={kw.playstore_rank} />
                  </span>
                  <span className="col-span-1 flex justify-center">
                    <TrendArrow delta={gpTrend?.delta ?? null} />
                  </span>
                  <span className="col-span-2 text-center text-[10px] text-gray-300">
                    {kw.checked_at
                      ? new Date(kw.checked_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
                      : 'Never'}
                  </span>
                  <button onClick={() => deleteKw(kw.id)}
                    className="col-span-1 flex justify-end text-gray-300 hover:text-red-400">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              )
            })}
          </div>
        )}

        {/* Rank legend */}
        {keywords.length > 0 && (
          <div className="mt-3 pt-3 border-t border-gray-50 flex gap-4 text-[10px] text-gray-400">
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-green-500 inline-block" />Top 10</span>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-amber-400 inline-block" />Top 50</span>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-gray-300 inline-block" />Below 50</span>
            <span className="flex items-center gap-1 text-green-600"><ArrowUp className="h-3 w-3" />Improved</span>
            <span className="flex items-center gap-1 text-red-500"><ArrowDown className="h-3 w-3" />Dropped</span>
            <span className="ml-auto">Ranks checked via iTunes Search API (App Store) · Play Store search (Play)</span>
          </div>
        )}
      </div>

      {/* ASO Score info box */}
      <div className="rounded-xl bg-amber-50 border border-amber-100 p-4">
        <div className="flex items-start gap-3">
          <Search className="h-5 w-5 text-amber-600 mt-0.5 shrink-0" />
          <div>
            <p className="text-sm font-semibold text-amber-800 mb-1">How ASO Rank Checking Works</p>
            <ul className="text-xs text-amber-700 space-y-1">
              <li><strong>App Store:</strong> Uses Apple's free iTunes Search API — searches for your keyword and finds your app's position in the results (up to top 200).</li>
              <li><strong>Play Store:</strong> Scrapes Google Play search results for your keyword and finds your app's package name position.</li>
              <li><strong>Rank Trend:</strong> Arrows show change since last check. Green ↑ = moved up (better), Red ↓ = moved down.</li>
              <li><strong>Frequency:</strong> Click "Check All Ranks" manually or it runs automatically when you generate a Growth Plan.</li>
            </ul>
          </div>
        </div>
      </div>

      {/* Metadata Optimizer */}
      <div className="rounded-xl bg-white border border-gray-100 p-5">
        <button onClick={() => setAnalyzeOpen(p => !p)}
          className="flex w-full items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold text-gray-800">AI Metadata Optimizer</h3>
            <p className="text-xs text-gray-500 mt-0.5">
              Paste your current App Store / Play Store metadata — ARIA scores it and rewrites optimized title, subtitle, keywords, and description
            </p>
          </div>
          {analyzeOpen ? <ChevronUp className="h-4 w-4 text-gray-400" /> : <ChevronDown className="h-4 w-4 text-gray-400" />}
        </button>

        {analyzeOpen && (
          <div className="mt-4 space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Store</label>
                <select value={analyzeForm.store} onChange={e => setAnalyzeForm(p => ({...p, store: e.target.value}))}
                  className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none">
                  <option value="appstore">App Store (iOS)</option>
                  <option value="playstore">Play Store (Android)</option>
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">App Name</label>
                <input value={analyzeForm.app_name} onChange={e => setAnalyzeForm(p => ({...p, app_name: e.target.value}))}
                  className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-indigo-400" />
              </div>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Subtitle / Short Description</label>
              <input value={analyzeForm.subtitle} onChange={e => setAnalyzeForm(p => ({...p, subtitle: e.target.value}))}
                placeholder="Max 30 chars (iOS) / 80 chars (Android)"
                className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-indigo-400" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Description (paste full text)</label>
              <textarea value={analyzeForm.description} onChange={e => setAnalyzeForm(p => ({...p, description: e.target.value}))}
                rows={4} placeholder="Paste your current app description..."
                className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-indigo-400 resize-none" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Keywords Field (iOS only, comma-separated)</label>
                <input value={analyzeForm.keywords_field} onChange={e => setAnalyzeForm(p => ({...p, keywords_field: e.target.value}))}
                  placeholder="health,ecg,heart,monitor..."
                  className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-indigo-400" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Category</label>
                <input value={analyzeForm.category} onChange={e => setAnalyzeForm(p => ({...p, category: e.target.value}))}
                  placeholder="Health & Fitness"
                  className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-indigo-400" />
              </div>
            </div>
            <button onClick={runAnalysis} disabled={analyzing}
              className="flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50">
              {analyzing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
              {analyzing ? 'Analyzing...' : 'Analyze & Optimize with AI'}
            </button>

            {asoResult && <AsoResultPanel result={asoResult} />}
          </div>
        )}
      </div>
    </div>
  )
}

function AsoResultPanel({ result }: { result: any }) {
  const scoreColor = result.score >= 70 ? 'text-green-600' : result.score >= 40 ? 'text-amber-600' : 'text-red-600'
  const scoreBg = result.score >= 70 ? 'bg-green-50 border-green-200' : result.score >= 40 ? 'bg-amber-50 border-amber-200' : 'bg-red-50 border-red-200'
  return (
    <div className={cn('rounded-xl border p-4 space-y-4', scoreBg)}>
      {/* Score */}
      <div className="flex items-center gap-3">
        <div className="text-center">
          <span className={cn('text-4xl font-bold', scoreColor)}>{result.score}</span>
          <p className="text-[10px] text-gray-500 uppercase tracking-wide">ASO Score</p>
        </div>
        <div className="flex-1">
          <div className="h-3 rounded-full bg-white border border-gray-200 overflow-hidden">
            <div className={cn('h-full rounded-full', result.score >= 70 ? 'bg-green-500' : result.score >= 40 ? 'bg-amber-500' : 'bg-red-500')}
              style={{ width: `${result.score}%` }} />
          </div>
          <p className="text-xs text-gray-600 mt-1">{result.score >= 70 ? 'Good ASO health' : result.score >= 40 ? 'Room for improvement' : 'Needs significant work'}</p>
        </div>
      </div>

      {result.issues?.length > 0 && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">Issues Found ({result.issues.length})</p>
          <div className="space-y-2">
            {result.issues.map((iss: any, i: number) => (
              <div key={i} className="rounded-lg bg-white border border-gray-100 p-3">
                <div className="flex items-center gap-2 mb-1">
                  <span className={cn('rounded px-1.5 py-0.5 text-[10px] font-bold uppercase',
                    iss.severity === 'high' ? 'bg-red-100 text-red-600' : iss.severity === 'medium' ? 'bg-amber-100 text-amber-600' : 'bg-gray-100 text-gray-500')}>
                    {iss.severity}
                  </span>
                  <span className="text-xs font-medium text-gray-700 capitalize">{iss.field}</span>
                </div>
                <p className="text-xs text-gray-600">{iss.issue}</p>
                <p className="text-xs text-indigo-700 mt-1 font-medium">→ {iss.fix}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {result.optimized_subtitle && (
        <CopyBlock label="Optimized Subtitle" value={result.optimized_subtitle}
          note={`${result.optimized_subtitle.length} chars`} />
      )}
      {result.optimized_keywords && (
        <CopyBlock label="Optimized Keywords Field (iOS)" value={result.optimized_keywords}
          note={`${result.optimized_keywords.length}/100 chars`} />
      )}
      {result.optimized_description_opening && (
        <CopyBlock label="Optimized Opening (first 3 sentences)" value={result.optimized_description_opening} />
      )}

      {result.top_keywords_to_target?.length > 0 && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">Top Keywords to Target</p>
          <div className="flex flex-wrap gap-2">
            {result.top_keywords_to_target.map((kw: string, i: number) => (
              <span key={i} className="rounded-full bg-white border border-indigo-200 px-3 py-1 text-xs text-indigo-700 font-medium">
                {kw}
              </span>
            ))}
          </div>
        </div>
      )}

      {result.competitor_gap && (
        <div className="rounded-lg bg-white border border-gray-100 p-3">
          <p className="text-xs font-semibold text-gray-500 mb-1">Competitor Gap</p>
          <p className="text-xs text-gray-700">{result.competitor_gap}</p>
        </div>
      )}
    </div>
  )
}

function CopyBlock({ label, value, note }: { label: string; value: string; note?: string }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    navigator.clipboard.writeText(value)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">{label}</p>
        <div className="flex items-center gap-2">
          {note && <span className="text-[10px] text-gray-400">{note}</span>}
          <button onClick={copy} className="text-[10px] text-indigo-600 hover:underline">
            {copied ? '✓ Copied' : 'Copy'}
          </button>
        </div>
      </div>
      <p className="text-sm bg-white border border-gray-100 rounded-lg px-3 py-2 text-gray-800">{value}</p>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
// REVIEWS TAB — with sync from stores + live reply
// ═══════════════════════════════════════════════════════════════════════════════

function ReviewsTab({ wsId, status }: { wsId: string; status: AppStatus | null }) {
  const [reviews, setReviews] = useState<AppReview[]>([])
  const [ratingDist, setRatingDist] = useState<Record<string,number>>({})
  const [avgRating, setAvgRating] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [filterSentiment, setFilterSentiment] = useState('all')
  const [filterStore, setFilterStore] = useState('all')
  const [showAdd, setShowAdd] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [syncMsg, setSyncMsg] = useState('')
  const [lastSync, setLastSync] = useState<string | null>(null)

  // Reply state per review
  const [replyOpen, setReplyOpen] = useState<string | null>(null)
  const [replyText, setReplyText] = useState('')
  const [replying, setReplying] = useState<string | null>(null)

  // Add review form
  const [addForm, setAddForm] = useState({ store: 'appstore', author: '', rating: '5', title: '', body: '', version: '' })
  const [addLoading, setAddLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    const r = await fetch(`/api/app-growth/reviews?workspace_id=${wsId}&store=${filterStore}&sentiment=${filterSentiment}&limit=100`)
    const d = await r.json()
    setReviews(d.reviews ?? [])
    setRatingDist(d.rating_distribution ?? {})
    setAvgRating(d.avg_rating)
    setLoading(false)
  }, [wsId, filterStore, filterSentiment])

  const loadSyncStatus = useCallback(async () => {
    const r = await fetch(`/api/app-growth/sync-reviews?workspace_id=${wsId}`)
    const d = await r.json()
    if (d.syncs?.length > 0) {
      setLastSync(d.syncs[0].synced_at)
    }
  }, [wsId])

  useEffect(() => { load(); loadSyncStatus() }, [load, loadSyncStatus])

  const syncReviews = async () => {
    setSyncing(true)
    setSyncMsg('')
    const r = await fetch('/api/app-growth/sync-reviews', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace_id: wsId }),
    })
    const d = await r.json()
    setSyncMsg(d.message ?? 'Sync started')
    setSyncing(false)
    setTimeout(() => { load(); loadSyncStatus() }, 15000)
  }

  const openReply = (rv: AppReview) => {
    setReplyOpen(rv.id)
    setReplyText(rv.suggested_reply || '')
  }

  const submitReply = async (rv: AppReview) => {
    setReplying(rv.id)
    await fetch(`/api/app-growth/reviews/${rv.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        workspace_id: wsId,
        reply_text: replyText,
        store: rv.store,
        store_review_id: rv.review_id,
      }),
    })
    setReviews(prev => prev.map(r => r.id === rv.id ? {...r, replied: true, suggested_reply: replyText} : r))
    setReplyOpen(null)
    setReplying(null)
  }

  const addReview = async () => {
    setAddLoading(true)
    await fetch('/api/app-growth/reviews', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        workspace_id: wsId,
        reviews: [{ ...addForm, rating: parseInt(addForm.rating), review_id: `manual_${Date.now()}` }],
      }),
    })
    setShowAdd(false)
    setAddForm({ store: 'appstore', author: '', rating: '5', title: '', body: '', version: '' })
    await load()
    setAddLoading(false)
  }

  const totalReviews = Object.values(ratingDist).reduce((a,b) => a+b, 0)
  const hasApiCreds = status?.has_asc || status?.has_play

  return (
    <div className="p-6 space-y-4">
      {/* Sync bar */}
      <div className={cn('rounded-xl border p-4 flex items-center justify-between gap-3',
        hasApiCreds ? 'bg-green-50 border-green-200' : 'bg-gray-50 border-gray-200')}>
        <div className="flex items-center gap-2">
          <RotateCw className={cn('h-4 w-4', hasApiCreds ? 'text-green-600' : 'text-gray-400')} />
          <div>
            <p className="text-sm font-semibold text-gray-800">
              {hasApiCreds ? 'Auto-sync available' : 'Manual mode'}
            </p>
            <p className="text-xs text-gray-500">
              {hasApiCreds
                ? `Pulls reviews from ${status?.has_asc ? 'App Store Connect' : ''}${status?.has_asc && status?.has_play ? ' + ' : ''}${status?.has_play ? 'Google Play' : ''}.${lastSync ? ` Last sync: ${new Date(lastSync).toLocaleString('en-IN')}` : ''}`
                : 'Add App Store Connect API keys or Play Store service account to enable auto-sync.'}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {syncMsg && (
            <span className="text-xs text-green-700 bg-green-100 rounded px-2 py-1">{syncMsg}</span>
          )}
          <button onClick={syncReviews} disabled={syncing || !hasApiCreds}
            className="flex items-center gap-1.5 rounded-lg bg-green-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-40">
            {syncing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCw className="h-3.5 w-3.5" />}
            Sync Reviews
          </button>
        </div>
      </div>

      {/* Summary */}
      {avgRating !== null && (
        <div className="rounded-xl bg-white border border-gray-100 p-5 flex items-center gap-6">
          <div className="text-center">
            <p className="text-4xl font-bold text-gray-900">{avgRating}</p>
            <StarRow rating={Math.round(avgRating)} />
            <p className="text-xs text-gray-500 mt-1">{totalReviews} reviews</p>
          </div>
          <div className="flex-1 space-y-1">
            {[5,4,3,2,1].map(n => {
              const count = ratingDist[String(n)] ?? 0
              const pct = totalReviews > 0 ? (count / totalReviews) * 100 : 0
              return (
                <div key={n} className="flex items-center gap-2">
                  <span className="w-3 text-xs text-gray-500">{n}</span>
                  <div className="flex-1 h-2 rounded-full bg-gray-100 overflow-hidden">
                    <div className="h-full bg-amber-400 rounded-full" style={{ width: `${pct}%` }} />
                  </div>
                  <span className="w-8 text-right text-xs text-gray-400">{count}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Filters + Add */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex gap-2">
          <select value={filterStore} onChange={e => setFilterStore(e.target.value)}
            className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs outline-none">
            <option value="all">All Stores</option>
            <option value="appstore">App Store</option>
            <option value="playstore">Play Store</option>
          </select>
          <select value={filterSentiment} onChange={e => setFilterSentiment(e.target.value)}
            className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs outline-none">
            <option value="all">All Sentiment</option>
            <option value="negative">Negative</option>
            <option value="neutral">Neutral</option>
            <option value="positive">Positive</option>
          </select>
        </div>
        <button onClick={() => setShowAdd(true)}
          className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700">
          <Plus className="h-3.5 w-3.5" /> Add Review
        </button>
      </div>

      {/* Add form */}
      {showAdd && (
        <div className="rounded-xl bg-white border border-indigo-100 p-4 space-y-3">
          <h4 className="text-sm font-semibold text-gray-800">Add Review Manually</h4>
          <div className="grid grid-cols-3 gap-3">
            <select value={addForm.store} onChange={e => setAddForm(p=>({...p,store:e.target.value}))}
              className="rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none">
              <option value="appstore">App Store</option>
              <option value="playstore">Play Store</option>
            </select>
            <input value={addForm.author} onChange={e => setAddForm(p=>({...p,author:e.target.value}))}
              placeholder="Author name" className="rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none" />
            <select value={addForm.rating} onChange={e => setAddForm(p=>({...p,rating:e.target.value}))}
              className="rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none">
              {[5,4,3,2,1].map(n=><option key={n} value={n}>{n} stars</option>)}
            </select>
          </div>
          <input value={addForm.title} onChange={e => setAddForm(p=>({...p,title:e.target.value}))}
            placeholder="Review title" className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none" />
          <textarea value={addForm.body} onChange={e => setAddForm(p=>({...p,body:e.target.value}))}
            placeholder="Review body" rows={3}
            className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none resize-none" />
          <div className="flex gap-2">
            <button onClick={addReview} disabled={addLoading || !addForm.body}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50">
              {addLoading ? 'Saving...' : 'Save & Classify with AI'}
            </button>
            <button onClick={() => setShowAdd(false)} className="rounded-lg border border-gray-200 px-4 py-2 text-xs font-medium text-gray-600">Cancel</button>
          </div>
        </div>
      )}

      {/* Review list */}
      {loading ? (
        <div className="flex h-32 items-center justify-center"><Loader2 className="h-5 w-5 animate-spin text-gray-300" /></div>
      ) : reviews.length === 0 ? (
        <div className="rounded-xl bg-white border border-gray-100 p-10 text-center">
          <Star className="mx-auto h-8 w-8 text-gray-200 mb-3" />
          <p className="text-sm text-gray-400 mb-2">No reviews yet.</p>
          <p className="text-xs text-gray-400">
            {hasApiCreds ? 'Click "Sync Reviews" to pull from App Store / Play Store.' : 'Add App Store Connect keys in Edit App to enable auto-sync, or add reviews manually.'}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {reviews.map(rv => (
            <div key={rv.id} className={cn('rounded-xl bg-white border p-4',
              rv.sentiment === 'negative' ? 'border-red-100' : rv.sentiment === 'positive' ? 'border-green-100' : 'border-gray-100')}>
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap mb-1">
                    <StarRow rating={rv.rating} />
                    <span className="text-xs font-medium text-gray-700">{rv.author}</span>
                    <span className={cn('rounded px-1.5 py-0.5 text-[10px] font-bold uppercase',
                      rv.store === 'appstore' ? 'bg-gray-100 text-gray-600' : 'bg-green-100 text-green-700')}>
                      {rv.store === 'appstore' ? 'App Store' : 'Play Store'}
                    </span>
                    <span className={cn('rounded px-1.5 py-0.5 text-[10px] font-medium capitalize',
                      rv.sentiment === 'positive' ? 'bg-green-100 text-green-700' :
                      rv.sentiment === 'negative' ? 'bg-red-100 text-red-700' : 'bg-gray-100 text-gray-500')}>
                      {rv.sentiment}
                    </span>
                    {rv.category && rv.category !== 'general' && (
                      <span className="rounded px-1.5 py-0.5 text-[10px] bg-blue-50 text-blue-600 capitalize">
                        {rv.category.replace('_',' ')}
                      </span>
                    )}
                    {rv.review_date && (
                      <span className="text-[10px] text-gray-400 flex items-center gap-0.5">
                        <Clock className="h-3 w-3" />
                        {new Date(rv.review_date).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: '2-digit' })}
                      </span>
                    )}
                  </div>
                  {rv.title && <p className="text-sm font-semibold text-gray-800 mb-0.5">{rv.title}</p>}
                  <p className="text-sm text-gray-600">{rv.body}</p>
                </div>
                {rv.replied ? (
                  <span className="flex items-center gap-1 text-xs text-green-600 shrink-0">
                    <CheckCircle className="h-3.5 w-3.5" /> Replied
                  </span>
                ) : (
                  <button onClick={() => openReply(rv)}
                    className="shrink-0 flex items-center gap-1 rounded-lg border border-indigo-200 bg-indigo-50 px-2.5 py-1.5 text-xs font-medium text-indigo-700 hover:bg-indigo-100">
                    <Send className="h-3 w-3" /> Reply
                  </button>
                )}
              </div>

              {/* AI suggested reply (collapsed by default) */}
              {rv.suggested_reply && !rv.replied && replyOpen !== rv.id && (
                <div className="mt-3 rounded-lg bg-gray-50 border border-gray-100 px-3 py-2">
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-400 mb-1">AI Suggested Reply</p>
                  <p className="text-xs text-gray-600">{rv.suggested_reply}</p>
                </div>
              )}

              {/* Reply editor */}
              {replyOpen === rv.id && (
                <div className="mt-3 space-y-2">
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-500">
                    {hasApiCreds ? `Reply — will be posted live to ${rv.store === 'appstore' ? 'App Store' : 'Play Store'}` : 'Reply (saved locally — add API keys to post live)'}
                  </p>
                  <textarea
                    value={replyText}
                    onChange={e => setReplyText(e.target.value)}
                    rows={3}
                    placeholder="Type your reply..."
                    className="w-full rounded-lg border border-indigo-200 px-3 py-2 text-sm outline-none focus:border-indigo-400 resize-none"
                  />
                  <div className="flex gap-2 items-center">
                    <button onClick={() => submitReply(rv)} disabled={replying === rv.id || !replyText.trim()}
                      className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50">
                      {replying === rv.id ? <Loader2 className="h-3 w-3 animate-spin" /> : <Send className="h-3 w-3" />}
                      {hasApiCreds ? 'Post Reply to Store' : 'Save Reply'}
                    </button>
                    <button onClick={() => setReplyOpen(null)} className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600">Cancel</button>
                    <span className="ml-auto text-[10px] text-gray-400">{replyText.length} chars</span>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
// ATTRIBUTION TAB
// ═══════════════════════════════════════════════════════════════════════════════

function AttributionTab({ wsId }: { wsId: string }) {
  const [funnel, setFunnel] = useState<InstallFunnel | null>(null)
  const [days, setDays] = useState(30)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    const r = await fetch(`/api/app-growth/attribution?workspace_id=${wsId}&days=${days}`)
    const d = await r.json()
    setFunnel(d)
    setLoading(false)
  }, [wsId, days])

  useEffect(() => { load() }, [load])

  const SOURCE_COLOR: Record<string, string> = {
    organic: 'bg-green-100 text-green-700',
    meta: 'bg-blue-100 text-blue-700', facebook: 'bg-blue-100 text-blue-700',
    google: 'bg-amber-100 text-amber-700', google_uac: 'bg-amber-100 text-amber-700',
    youtube: 'bg-red-100 text-red-700', email: 'bg-purple-100 text-purple-700',
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-800">Install Attribution</h3>
        <select value={days} onChange={e => setDays(Number(e.target.value))}
          className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs outline-none">
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
        </select>
      </div>

      {loading ? (
        <div className="flex h-32 items-center justify-center"><Loader2 className="h-5 w-5 animate-spin text-gray-300" /></div>
      ) : !funnel || funnel.total_installs === 0 ? (
        <div className="rounded-xl bg-white border border-gray-100 p-10 text-center">
          <BarChart2 className="mx-auto h-8 w-8 text-gray-200 mb-3" />
          <p className="text-sm font-medium text-gray-600 mb-2">No attribution data yet</p>
          <p className="text-xs text-gray-400 max-w-sm mx-auto">
            Point your AppsFlyer / Adjust / Branch postback URL to the webhook shown in the Overview tab.
            Installs will appear here automatically.
          </p>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-4">
            {[
              { label: 'Total Installs', value: funnel.total_installs.toLocaleString(), icon: Download },
              { label: 'Total Spend', value: `₹${funnel.total_spend.toLocaleString()}`, icon: TrendingUp },
              { label: 'Avg CPI', value: `₹${funnel.cpi}`, icon: Zap },
            ].map(k => (
              <div key={k.label} className="rounded-xl bg-white border border-gray-100 p-4">
                <p className="text-2xl font-bold text-gray-900">{k.value}</p>
                <p className="text-xs text-gray-500">{k.label}</p>
              </div>
            ))}
          </div>

          <div className="rounded-xl bg-white border border-gray-100 p-5">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-3">Installs by Source</h4>
            <div className="space-y-2">
              {funnel.by_source.map(s => {
                const pct = Math.round((s.installs / funnel.total_installs) * 100)
                return (
                  <div key={s.source}>
                    <div className="flex items-center justify-between text-sm mb-1">
                      <span className={cn('rounded px-2 py-0.5 text-xs font-medium capitalize', SOURCE_COLOR[s.source] ?? 'bg-gray-100 text-gray-600')}>{s.source}</span>
                      <div className="flex items-center gap-3 text-xs text-gray-600">
                        <span>{s.installs.toLocaleString()} installs</span>
                        {s.spend > 0 && <span>₹{s.spend.toLocaleString()} spend</span>}
                        {s.cpi > 0 && <span className="font-medium text-gray-800">₹{s.cpi} CPI</span>}
                      </div>
                    </div>
                    <div className="h-2 rounded-full bg-gray-100 overflow-hidden">
                      <div className="h-full bg-indigo-500 rounded-full" style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          {funnel.by_campaign.length > 0 && (
            <div className="rounded-xl bg-white border border-gray-100 p-5">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-3">Top Campaigns</h4>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-[10px] uppercase tracking-wide text-gray-400 border-b border-gray-50">
                    <th className="text-left pb-2">Campaign</th>
                    <th className="text-left pb-2">Source</th>
                    <th className="text-right pb-2">Installs</th>
                    <th className="text-right pb-2">Spend</th>
                    <th className="text-right pb-2">CPI</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {funnel.by_campaign.map((c,i) => (
                    <tr key={i}>
                      <td className="py-2 pr-2 font-medium text-gray-800 truncate max-w-[160px]">{c.campaign}</td>
                      <td className="py-2 pr-2 text-gray-500 capitalize text-xs">{c.source}</td>
                      <td className="py-2 text-right">{c.installs.toLocaleString()}</td>
                      <td className="py-2 text-right text-gray-500">₹{c.spend.toLocaleString()}</td>
                      <td className="py-2 text-right font-medium">₹{c.cpi}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            {funnel.by_country.length > 0 && (
              <div className="rounded-xl bg-white border border-gray-100 p-5">
                <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-3">By Country</h4>
                <div className="space-y-1.5">
                  {funnel.by_country.slice(0,8).map(c => (
                    <div key={c.country} className="flex items-center justify-between text-xs">
                      <span className="text-gray-700 uppercase">{c.country}</span>
                      <span className="font-medium">{c.installs.toLocaleString()}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {funnel.by_platform.length > 0 && (
              <div className="rounded-xl bg-white border border-gray-100 p-5">
                <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-3">By Platform</h4>
                <div className="space-y-1.5">
                  {funnel.by_platform.map(p => (
                    <div key={p.platform} className="flex items-center justify-between text-xs">
                      <span className="text-gray-700 capitalize">{p.platform}</span>
                      <span className="font-medium">{p.installs.toLocaleString()}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
// GROWTH PLAN TAB
// ═══════════════════════════════════════════════════════════════════════════════

function GrowthPlanTab({ wsId }: { wsId: string }) {
  const [plan, setPlan] = useState<GrowthPlan | null>(null)
  const [generatedAt, setGeneratedAt] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    const r = await fetch(`/api/app-growth/growth-plan?workspace_id=${wsId}`)
    const d = await r.json()
    if (d.plan) { setPlan(d.plan); setGeneratedAt(d.generated_at) }
    setLoading(false)
  }, [wsId])

  useEffect(() => { load() }, [load])

  const generate = async () => {
    setGenerating(true)
    const r = await fetch('/api/app-growth/growth-plan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace_id: wsId }),
    })
    const d = await r.json()
    if (d.actions) { setPlan(d); setGeneratedAt(new Date().toISOString()) }
    setGenerating(false)
  }

  const grouped = {
    high: plan?.actions.filter(a => a.priority === 'high') ?? [],
    medium: plan?.actions.filter(a => a.priority === 'medium') ?? [],
    low: plan?.actions.filter(a => a.priority === 'low') ?? [],
  }

  const CHANNEL_COLORS: Record<string,string> = {
    meta: 'bg-blue-100 text-blue-700',
    google: 'bg-green-100 text-green-700', google_uac: 'bg-green-100 text-green-700',
    youtube: 'bg-red-100 text-red-700',
    email: 'bg-purple-100 text-purple-700',
    aso: 'bg-amber-100 text-amber-700',
    reviews: 'bg-pink-100 text-pink-700',
    organic: 'bg-gray-100 text-gray-700',
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-sm font-semibold text-gray-800">AI App Growth Plan</h3>
          <p className="text-xs text-gray-500 mt-0.5">
            {generatedAt
              ? `Generated ${new Date(generatedAt).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })}`
              : 'No plan generated yet'}
          </p>
        </div>
        <button onClick={generate} disabled={generating}
          className="flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50">
          {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />}
          {generating ? 'Generating...' : plan ? 'Regenerate' : 'Generate Growth Plan'}
        </button>
      </div>

      {loading ? (
        <div className="flex h-32 items-center justify-center"><Loader2 className="h-5 w-5 animate-spin text-gray-300" /></div>
      ) : !plan ? (
        <div className="rounded-2xl border-2 border-dashed border-gray-200 p-10 text-center">
          <Zap className="mx-auto h-8 w-8 text-gray-300 mb-3" />
          <p className="text-sm text-gray-500 mb-4">
            Generate a personalised cross-channel app growth plan based on your reviews, installs, ASO keywords, ad spend, and YouTube presence.
          </p>
          <button onClick={generate} disabled={generating}
            className="rounded-xl bg-indigo-600 px-6 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50">
            {generating ? 'Generating...' : 'Generate Plan'}
          </button>
        </div>
      ) : (
        <>
          {/* Headline */}
          <div className="rounded-xl bg-indigo-600 text-white p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-widest text-indigo-200 mb-1">30-Day Growth Strategy</p>
                <p className="text-base font-bold leading-snug">{plan.headline}</p>
                {plan['30_day_goal'] && (
                  <p className="text-sm text-indigo-200 mt-2">Goal: {plan['30_day_goal']}</p>
                )}
              </div>
              {plan.priority_score && (
                <div className="text-center shrink-0">
                  <p className="text-3xl font-bold">{plan.priority_score}</p>
                  <p className="text-[10px] text-indigo-300 uppercase">Priority</p>
                </div>
              )}
            </div>
          </div>

          {/* ASO quick wins */}
          {plan.aso_quick_wins?.length > 0 && (
            <div className="rounded-xl bg-amber-50 border border-amber-100 p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-amber-700 mb-2">ASO Quick Wins</p>
              <ul className="space-y-1">
                {plan.aso_quick_wins.map((win, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-amber-800">
                    <CheckCircle className="h-4 w-4 text-amber-500 mt-0.5 shrink-0" />
                    {win}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Action groups */}
          {(['high', 'medium', 'low'] as const).map(priority => (
            grouped[priority].length > 0 && (
              <div key={priority}>
                <h4 className={cn('text-xs font-bold uppercase tracking-widest mb-3',
                  priority === 'high' ? 'text-red-600' : priority === 'medium' ? 'text-amber-600' : 'text-gray-400')}>
                  {priority} priority ({grouped[priority].length})
                </h4>
                <div className="space-y-3">
                  {grouped[priority].map(action => {
                    const Icon = CHANNEL_ICON[action.channel] ?? CHANNEL_ICON.default
                    return (
                      <div key={action.id} className={cn('rounded-xl border p-4', PRIORITY_COLOR[priority])}>
                        <div className="flex items-start gap-3">
                          <div className={cn('flex h-8 w-8 items-center justify-center rounded-lg shrink-0',
                            CHANNEL_COLORS[action.channel] ?? 'bg-gray-100 text-gray-600')}>
                            <Icon className="h-4 w-4" />
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 flex-wrap mb-1">
                              <p className="text-sm font-semibold text-gray-900">{action.title}</p>
                              <span className={cn('rounded px-2 py-0.5 text-[10px] font-medium capitalize',
                                CHANNEL_COLORS[action.channel] ?? 'bg-gray-100 text-gray-600')}>
                                {action.channel.replace('_',' ')}
                              </span>
                            </div>
                            <p className="text-xs text-gray-600 mb-2">{action.description}</p>
                            <div className="flex items-center gap-3 flex-wrap text-[10px] text-gray-500">
                              <span className="flex items-center gap-1">
                                <TrendingUp className="h-3 w-3 text-green-500" />{action.expected_impact}
                              </span>
                              <span>Effort: <strong>{action.effort}</strong></span>
                              <span>Timeframe: <strong>{action.timeframe}</strong></span>
                            </div>
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )
          ))}

          {/* Channel recommendations */}
          {plan.channel_recommendations && Object.keys(plan.channel_recommendations).length > 0 && (
            <div className="rounded-xl bg-white border border-gray-100 p-5">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-3">Channel Strategy</h4>
              <div className="grid grid-cols-2 gap-3">
                {Object.entries(plan.channel_recommendations).map(([channel, rec]) => (
                  <div key={channel} className="rounded-lg bg-gray-50 p-3">
                    <p className="text-xs font-semibold text-gray-700 capitalize mb-1">{channel.replace('_',' ')}</p>
                    <p className="text-xs text-gray-600">{rec}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
// CONNECT MODAL
// ═══════════════════════════════════════════════════════════════════════════════

function ConnectModal({ wsId, existing, onClose, onSaved }: {
  wsId: string
  existing: AppStatus | null
  onClose: () => void
  onSaved: () => void
}) {
  const [form, setForm] = useState({
    app_name: existing?.app_name ?? '',
    bundle_id: existing?.bundle_id ?? '',
    app_store_url: existing?.app_store_url ?? '',
    play_store_url: existing?.play_store_url ?? '',
    app_store_id: '',
    play_package: '',
    category: existing?.category ?? '',
    asc_key_id: '',
    asc_issuer_id: '',
    asc_private_key: '',
  })
  const [saving, setSaving] = useState(false)

  const save = async () => {
    setSaving(true)
    await fetch('/api/app-growth', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...form, workspace_id: wsId, action: 'connect' }),
    })
    setSaving(false)
    onSaved()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-lg rounded-2xl bg-white shadow-2xl overflow-y-auto max-h-[90vh]">
        <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4">
          <h3 className="text-base font-bold text-gray-900">Connect App</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg">✕</button>
        </div>
        <div className="p-5 space-y-4">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">App Name *</label>
            <input value={form.app_name} onChange={e => setForm(p=>({...p,app_name:e.target.value}))}
              placeholder="e.g. SanketLife"
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-indigo-400" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">iOS Bundle ID</label>
              <input value={form.bundle_id} onChange={e => setForm(p=>({...p,bundle_id:e.target.value}))}
                placeholder="com.agatsa.sanketlife"
                className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-indigo-400" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Category</label>
              <input value={form.category} onChange={e => setForm(p=>({...p,category:e.target.value}))}
                placeholder="Health & Fitness"
                className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-indigo-400" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">App Store ID (numeric)</label>
              <input value={form.app_store_id} onChange={e => setForm(p=>({...p,app_store_id:e.target.value}))}
                placeholder="1234567890"
                className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-indigo-400" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Play Package Name</label>
              <input value={form.play_package} onChange={e => setForm(p=>({...p,play_package:e.target.value}))}
                placeholder="com.agatsa.sanketlife"
                className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-indigo-400" />
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">App Store URL</label>
            <input value={form.app_store_url} onChange={e => setForm(p=>({...p,app_store_url:e.target.value}))}
              placeholder="https://apps.apple.com/app/..."
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-indigo-400" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Google Play URL</label>
            <input value={form.play_store_url} onChange={e => setForm(p=>({...p,play_store_url:e.target.value}))}
              placeholder="https://play.google.com/store/apps/details?id=..."
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-indigo-400" />
          </div>

          {/* ASC API */}
          <div className="rounded-lg bg-gray-50 border border-gray-200 p-3 space-y-2">
            <div className="flex items-center gap-2 mb-1">
              <Smartphone className="h-4 w-4 text-gray-500" />
              <p className="text-xs font-semibold text-gray-700">App Store Connect API</p>
              <span className="rounded bg-gray-200 px-1.5 py-0.5 text-[10px] text-gray-500">Optional — enables auto review sync</span>
            </div>
            <p className="text-[10px] text-gray-500">
              In App Store Connect → Users & Access → Integrations → App Store Connect API → Generate key with "Customer Support" role.
            </p>
            <input value={form.asc_key_id} onChange={e => setForm(p=>({...p,asc_key_id:e.target.value}))}
              placeholder="Key ID (e.g. ABC123XYZ)"
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-xs outline-none focus:border-indigo-400" />
            <input value={form.asc_issuer_id} onChange={e => setForm(p=>({...p,asc_issuer_id:e.target.value}))}
              placeholder="Issuer ID (UUID format)"
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-xs outline-none focus:border-indigo-400" />
            <textarea value={form.asc_private_key} onChange={e => setForm(p=>({...p,asc_private_key:e.target.value}))}
              placeholder="Paste .p8 private key contents here (-----BEGIN PRIVATE KEY----- ...)"
              rows={3}
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-xs outline-none focus:border-indigo-400 resize-none font-mono" />
          </div>
        </div>
        <div className="border-t border-gray-100 px-5 py-4 flex gap-2 justify-end">
          <button onClick={onClose} className="rounded-lg border border-gray-200 px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50">Cancel</button>
          <button onClick={save} disabled={saving || !form.app_name}
            className="rounded-lg bg-indigo-600 px-5 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50">
            {saving ? 'Saving...' : 'Save App'}
          </button>
        </div>
      </div>
    </div>
  )
}
