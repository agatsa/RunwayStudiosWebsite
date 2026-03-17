'use client'

import { useState, useEffect, useCallback } from 'react'
import { useSearchParams } from 'next/navigation'
import {
  Smartphone, Star, Search, TrendingUp, Zap, BarChart2,
  Mail, PlayCircle, Megaphone, Plus, Trash2, RefreshCw,
  CheckCircle, AlertCircle, ExternalLink, ChevronDown, ChevronUp,
  Download, Globe, Loader2, Send,
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

const TABS = [
  { id: 'overview',     label: 'Overview',     icon: Smartphone },
  { id: 'aso',          label: 'ASO',           icon: Search },
  { id: 'reviews',      label: 'Reviews',       icon: Star },
  { id: 'attribution',  label: 'Attribution',   icon: BarChart2 },
  { id: 'growth-plan',  label: 'Growth Plan',   icon: Zap },
] as const

type TabId = typeof TABS[number]['id']

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN PAGE
// ═══════════════════════════════════════════════════════════════════════════════

export default function AppGrowthPage() {
  const searchParams = useSearchParams()
  const wsId = searchParams.get('ws') ?? ''
  const [tab, setTab] = useState<TabId>('overview')
  const [status, setStatus] = useState<AppStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [showConnect, setShowConnect] = useState(false)

  const loadStatus = useCallback(async () => {
    if (!wsId) return
    setLoading(true)
    try {
      const r = await fetch(`/api/app-growth?action=status&workspace_id=${wsId}`)
      const d = await r.json()
      setStatus(d)
      if (!d.connected) setShowConnect(true)
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [wsId])

  useEffect(() => { loadStatus() }, [loadStatus])

  if (!wsId) return (
    <div className="p-8 text-center text-gray-500 text-sm">No workspace selected.</div>
  )

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="border-b border-gray-200 bg-white px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500 to-indigo-600">
              <Smartphone className="h-5 w-5 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-gray-900">App Growth</h1>
              <p className="text-xs text-gray-500">
                {status?.connected ? status.app_name : 'Connect your app to get started'}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {status?.connected && (
              <div className="flex items-center gap-3 text-xs text-gray-500">
                <span className="flex items-center gap-1">
                  <Download className="h-3.5 w-3.5" />
                  <strong className="text-gray-900">{status.installs_30d?.toLocaleString()}</strong> installs/30d
                </span>
                <span className="flex items-center gap-1">
                  <Star className="h-3.5 w-3.5 text-amber-400" />
                  <strong className="text-gray-900">{status.review_count}</strong> reviews
                </span>
              </div>
            )}
            <button
              onClick={() => setShowConnect(true)}
              className="flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
            >
              <Plus className="h-3.5 w-3.5" />
              {status?.connected ? 'Edit App' : 'Connect App'}
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="mt-4 flex gap-1 overflow-x-auto">
          {TABS.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={cn(
                'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium whitespace-nowrap transition-colors',
                tab === t.id
                  ? 'bg-indigo-50 text-indigo-700'
                  : 'text-gray-500 hover:bg-gray-50 hover:text-gray-700'
              )}
            >
              <t.icon className="h-3.5 w-3.5" />
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto bg-gray-50">
        {loading ? (
          <div className="flex h-40 items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
          </div>
        ) : (
          <>
            {tab === 'overview'    && <OverviewTab wsId={wsId} status={status} onEdit={() => setShowConnect(true)} />}
            {tab === 'aso'         && <AsoTab wsId={wsId} status={status} />}
            {tab === 'reviews'     && <ReviewsTab wsId={wsId} />}
            {tab === 'attribution' && <AttributionTab wsId={wsId} />}
            {tab === 'growth-plan' && <GrowthPlanTab wsId={wsId} />}
          </>
        )}
      </div>

      {/* Connect Modal */}
      {showConnect && (
        <ConnectModal
          wsId={wsId}
          existing={status?.connected ? status : null}
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

      {/* Channel grid */}
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-widest text-gray-400 mb-3">
          Growth Channels
        </h3>
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
              <Smartphone className="h-3.5 w-3.5" /> App Store
              <ExternalLink className="h-3 w-3 opacity-60" />
            </a>
          )}
          {status.play_store_url && (
            <a href={status.play_store_url} target="_blank" rel="noopener noreferrer"
              className="flex items-center gap-2 rounded-lg bg-green-600 px-4 py-2 text-xs font-medium text-white hover:bg-green-700">
              <Download className="h-3.5 w-3.5" /> Google Play
              <ExternalLink className="h-3 w-3 opacity-60" />
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
// ASO TAB
// ═══════════════════════════════════════════════════════════════════════════════

function AsoTab({ wsId, status }: { wsId: string; status: AppStatus | null }) {
  const [keywords, setKeywords] = useState<AsoKeyword[]>([])
  const [newKw, setNewKw] = useState('')
  const [adding, setAdding] = useState(false)
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

  useEffect(() => { loadKw() }, [loadKw])

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
          <h3 className="text-sm font-semibold text-gray-800">Keyword Tracker</h3>
          <span className="text-xs text-gray-500">{keywords.length} keywords</span>
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
            <div className="grid grid-cols-5 gap-2 pb-2 text-[10px] font-semibold uppercase tracking-wide text-gray-400">
              <span className="col-span-2">Keyword</span>
              <span className="text-center">App Store Rank</span>
              <span className="text-center">Play Store Rank</span>
              <span></span>
            </div>
            {keywords.map(kw => (
              <div key={kw.id} className="grid grid-cols-5 gap-2 items-center py-2.5 text-sm">
                <span className="col-span-2 font-medium text-gray-800">{kw.keyword}</span>
                <span className="text-center">
                  {kw.appstore_rank
                    ? <span className={cn('font-bold', kw.appstore_rank <= 10 ? 'text-green-600' : kw.appstore_rank <= 50 ? 'text-amber-600' : 'text-gray-500')}>{kw.appstore_rank}</span>
                    : <span className="text-gray-300">—</span>}
                </span>
                <span className="text-center">
                  {kw.playstore_rank
                    ? <span className={cn('font-bold', kw.playstore_rank <= 10 ? 'text-green-600' : kw.playstore_rank <= 50 ? 'text-amber-600' : 'text-gray-500')}>{kw.playstore_rank}</span>
                    : <span className="text-gray-300">—</span>}
                </span>
                <button onClick={() => deleteKw(kw.id)}
                  className="flex justify-end text-gray-300 hover:text-red-400">
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Metadata Analyzer */}
      <div className="rounded-xl bg-white border border-gray-100 p-5">
        <button onClick={() => setAnalyzeOpen(p => !p)}
          className="flex w-full items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold text-gray-800">Metadata Optimizer</h3>
            <p className="text-xs text-gray-500 mt-0.5">Paste your current App Store / Play Store metadata — Claude scores and rewrites it</p>
          </div>
          {analyzeOpen ? <ChevronUp className="h-4 w-4 text-gray-400" /> : <ChevronDown className="h-4 w-4 text-gray-400" />}
        </button>

        {analyzeOpen && (
          <div className="mt-4 space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">App Name</label>
                <input value={analyzeForm.app_name} onChange={e => setAnalyzeForm(p => ({...p, app_name: e.target.value}))}
                  className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-indigo-400" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Subtitle / Short Description</label>
                <input value={analyzeForm.subtitle} onChange={e => setAnalyzeForm(p => ({...p, subtitle: e.target.value}))}
                  placeholder="Max 30 chars (iOS) / 80 chars (Android)"
                  className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-indigo-400" />
              </div>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Description (paste full text)</label>
              <textarea value={analyzeForm.description} onChange={e => setAnalyzeForm(p => ({...p, description: e.target.value}))}
                rows={4} placeholder="Paste your current app description..."
                className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-indigo-400 resize-none" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Keywords Field (iOS only)</label>
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
              {analyzing ? 'Analyzing...' : 'Analyze & Optimize'}
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
  return (
    <div className="rounded-xl border border-indigo-100 bg-indigo-50 p-4 space-y-4">
      <div className="flex items-center gap-3">
        <span className={cn('text-3xl font-bold', scoreColor)}>{result.score}</span>
        <span className="text-sm text-gray-600">ASO Score / 100</span>
      </div>

      {result.issues?.length > 0 && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">Issues</p>
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
                <p className="text-xs text-indigo-700 mt-1">Fix: {iss.fix}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {result.optimized_subtitle && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1">Optimized Subtitle</p>
          <p className="text-sm bg-white border border-gray-100 rounded-lg px-3 py-2 text-gray-800">{result.optimized_subtitle}</p>
        </div>
      )}

      {result.optimized_keywords && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1">Optimized Keywords Field</p>
          <p className="text-sm bg-white border border-gray-100 rounded-lg px-3 py-2 text-gray-800 font-mono">{result.optimized_keywords}</p>
        </div>
      )}

      {result.top_keywords_to_target?.length > 0 && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">Top Keywords to Target</p>
          <div className="flex flex-wrap gap-1.5">
            {result.top_keywords_to_target.map((kw: string, i: number) => (
              <span key={i} className="rounded-full bg-white border border-indigo-200 px-2.5 py-0.5 text-xs font-medium text-indigo-700">{kw}</span>
            ))}
          </div>
        </div>
      )}

      {result.competitor_gap && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1">Competitor Gap</p>
          <p className="text-xs text-gray-600 bg-white border border-gray-100 rounded-lg px-3 py-2">{result.competitor_gap}</p>
        </div>
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
// REVIEWS TAB
// ═══════════════════════════════════════════════════════════════════════════════

function ReviewsTab({ wsId }: { wsId: string }) {
  const [reviews, setReviews] = useState<AppReview[]>([])
  const [ratingDist, setRatingDist] = useState<Record<string,number>>({})
  const [avgRating, setAvgRating] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [filterSentiment, setFilterSentiment] = useState('all')
  const [filterStore, setFilterStore] = useState('all')
  const [showAdd, setShowAdd] = useState(false)
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

  useEffect(() => { load() }, [load])

  const markReplied = async (id: string) => {
    setReplying(id)
    await fetch(`/api/app-growth/reviews`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace_id: wsId, reviews: [], _patch_id: id }),
    })
    // optimistic
    setReviews(prev => prev.map(r => r.id === id ? {...r, replied: true} : r))
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

  return (
    <div className="p-6 space-y-4">
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
          <h4 className="text-sm font-semibold text-gray-800">Add Review</h4>
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
              {addLoading ? 'Saving...' : 'Save & Classify'}
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
          <p className="text-sm text-gray-400">No reviews yet. Add reviews manually or connect App Store Connect for automatic import.</p>
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
                  </div>
                  {rv.title && <p className="text-sm font-semibold text-gray-800 mb-0.5">{rv.title}</p>}
                  <p className="text-sm text-gray-600">{rv.body}</p>
                </div>
                {rv.replied ? (
                  <span className="flex items-center gap-1 text-xs text-green-600 shrink-0">
                    <CheckCircle className="h-3.5 w-3.5" /> Replied
                  </span>
                ) : (
                  <button onClick={() => markReplied(rv.id)} disabled={replying === rv.id}
                    className="shrink-0 flex items-center gap-1 rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50">
                    {replying === rv.id ? <Loader2 className="h-3 w-3 animate-spin" /> : <Send className="h-3 w-3" />}
                    Mark Replied
                  </button>
                )}
              </div>
              {rv.suggested_reply && !rv.replied && (
                <div className="mt-3 rounded-lg bg-gray-50 border border-gray-100 px-3 py-2">
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-400 mb-1">Suggested Reply</p>
                  <p className="text-xs text-gray-600">{rv.suggested_reply}</p>
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
          {/* KPIs */}
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

          {/* By source */}
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

          {/* By campaign */}
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

          {/* By country + platform side by side */}
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
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-gray-800">AI App Growth Plan</h3>
          {generatedAt && (
            <p className="text-xs text-gray-400">Generated {new Date(generatedAt).toLocaleDateString()}</p>
          )}
        </div>
        <button onClick={generate} disabled={generating}
          className="flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
          style={{ background: 'linear-gradient(135deg, #7c3aed, #4f46e5)' }}>
          {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />}
          {generating ? 'Generating...' : plan ? 'Regenerate' : 'Generate Plan'}
        </button>
      </div>

      {loading ? (
        <div className="flex h-32 items-center justify-center"><Loader2 className="h-5 w-5 animate-spin text-gray-300" /></div>
      ) : !plan ? (
        <div className="rounded-xl bg-white border border-dashed border-gray-200 p-10 text-center">
          <Zap className="mx-auto h-10 w-10 text-gray-200 mb-4" />
          <p className="text-sm font-medium text-gray-600 mb-2">No growth plan yet</p>
          <p className="text-xs text-gray-400 mb-6 max-w-sm mx-auto">
            Claude analyses your installs, reviews, ASO keywords, ad spend, YouTube content, and email list
            to generate a cross-channel 30-day action plan.
          </p>
          <button onClick={generate} disabled={generating}
            className="rounded-xl px-6 py-2.5 text-sm font-semibold text-white"
            style={{ background: 'linear-gradient(135deg, #7c3aed, #4f46e5)' }}>
            {generating ? 'Generating...' : 'Generate Now'}
          </button>
        </div>
      ) : (
        <>
          {/* Headline */}
          <div className="rounded-xl bg-gradient-to-r from-violet-50 to-indigo-50 border border-indigo-100 p-4">
            <p className="text-sm font-semibold text-indigo-800">{plan.headline}</p>
            {plan['30_day_goal'] && (
              <p className="text-xs text-indigo-600 mt-1">
                30-day goal: <strong>{plan['30_day_goal']}</strong>
              </p>
            )}
          </div>

          {/* Actions by priority */}
          {(['high','medium','low'] as const).map(pri => grouped[pri].length > 0 && (
            <div key={pri}>
              <h4 className="text-xs font-semibold uppercase tracking-widest text-gray-400 mb-2">
                {pri === 'high' ? '🔴 High Priority' : pri === 'medium' ? '🟡 Medium Priority' : '⚪ Low Priority'}
              </h4>
              <div className="space-y-2">
                {grouped[pri].map(action => {
                  const Icon = CHANNEL_ICON[action.channel] ?? CHANNEL_ICON.default
                  return (
                    <div key={action.id} className={cn('rounded-xl bg-white border p-4', PRIORITY_COLOR[action.priority])}>
                      <div className="flex items-start gap-3">
                        <div className={cn('flex h-8 w-8 shrink-0 items-center justify-center rounded-lg',
                          CHANNEL_COLORS[action.channel] ?? 'bg-gray-100 text-gray-600')}>
                          <Icon className="h-4 w-4" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap mb-1">
                            <span className="text-sm font-semibold text-gray-800">{action.title}</span>
                            <span className={cn('rounded px-1.5 py-0.5 text-[10px] font-bold uppercase',
                              CHANNEL_COLORS[action.channel] ?? 'bg-gray-100 text-gray-600')}>
                              {action.channel.replace('_',' ')}
                            </span>
                          </div>
                          <p className="text-xs text-gray-600 mb-2">{action.description}</p>
                          <div className="flex items-center gap-3 text-xs text-gray-500">
                            <span className="text-green-700 font-medium">{action.expected_impact}</span>
                            <span>·</span>
                            <span>{action.timeframe}</span>
                            <span>·</span>
                            <span>Effort: {action.effort}</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          ))}

          {/* ASO quick wins */}
          {plan.aso_quick_wins?.length > 0 && (
            <div className="rounded-xl bg-white border border-amber-100 p-4">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-amber-700 mb-2">ASO Quick Wins</h4>
              <ul className="space-y-1">
                {plan.aso_quick_wins.map((w,i) => (
                  <li key={i} className="flex items-start gap-2 text-xs text-gray-600">
                    <CheckCircle className="h-3.5 w-3.5 text-amber-500 shrink-0 mt-0.5" />
                    {w}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Review action */}
          {plan.review_action && (
            <div className="rounded-xl bg-white border border-pink-100 p-4">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-pink-700 mb-1">Reviews This Week</h4>
              <p className="text-xs text-gray-600">{plan.review_action}</p>
            </div>
          )}

          {/* Channel recs */}
          {plan.channel_recommendations && (
            <div className="rounded-xl bg-white border border-gray-100 p-4">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-3">Channel Recommendations</h4>
              <div className="grid grid-cols-2 gap-3">
                {Object.entries(plan.channel_recommendations).map(([ch, rec]) => {
                  const Icon = CHANNEL_ICON[ch] ?? CHANNEL_ICON.default
                  return (
                    <div key={ch} className="flex items-start gap-2">
                      <div className={cn('flex h-7 w-7 shrink-0 items-center justify-center rounded-lg mt-0.5',
                        CHANNEL_COLORS[ch] ?? 'bg-gray-100 text-gray-600')}>
                        <Icon className="h-3.5 w-3.5" />
                      </div>
                      <div>
                        <p className="text-xs font-medium text-gray-700 capitalize mb-0.5">{ch.replace('_',' ')}</p>
                        <p className="text-xs text-gray-500">{rec}</p>
                      </div>
                    </div>
                  )
                })}
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
              <label className="block text-xs font-medium text-gray-600 mb-1">Bundle ID / Package</label>
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

          {/* ASO — optional */}
          <div className="rounded-lg bg-gray-50 border border-gray-100 p-3">
            <p className="text-xs font-semibold text-gray-600 mb-2">App Store Connect API (optional — for auto review import)</p>
            <div className="space-y-2">
              <input value={form.asc_key_id} onChange={e => setForm(p=>({...p,asc_key_id:e.target.value}))}
                placeholder="Key ID (e.g. ABC123XYZ)"
                className="w-full rounded-lg border border-gray-200 px-3 py-2 text-xs outline-none focus:border-indigo-400" />
              <input value={form.asc_issuer_id} onChange={e => setForm(p=>({...p,asc_issuer_id:e.target.value}))}
                placeholder="Issuer ID (UUID)"
                className="w-full rounded-lg border border-gray-200 px-3 py-2 text-xs outline-none focus:border-indigo-400" />
              <textarea value={form.asc_private_key} onChange={e => setForm(p=>({...p,asc_private_key:e.target.value}))}
                placeholder="Private Key (.p8 contents — paste here)"
                rows={3}
                className="w-full rounded-lg border border-gray-200 px-3 py-2 text-xs outline-none focus:border-indigo-400 resize-none font-mono" />
            </div>
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
