'use client'

import { useState, useEffect, useCallback, Suspense } from 'react'
import { useSearchParams } from 'next/navigation'
import Link from 'next/link'
import {
  MessageSquare, Youtube, ThumbsUp, RefreshCw, Loader2, ArrowUpRight,
  ShoppingCart, Star, CheckCircle2, HelpCircle, DollarSign, Shield,
  Truck, AlertCircle, ChevronDown, ChevronUp, TrendingUp, TrendingDown,
} from 'lucide-react'
import { toast } from 'sonner'

// ─── Types ───────────────────────────────────────────────────────────────────

interface Comment {
  id: string
  source: 'meta' | 'youtube'
  source_name: string
  author_name: string
  comment_text: string
  category: string
  sentiment: string
  like_count: number
  suggested_reply: string | null
  status: string
  published_at: string | null
}

interface CategoryStat {
  category: string
  label: string
  color: string
  count: number
  pct: number
}

interface SentimentData {
  has_data: boolean
  total: number
  positive_pct: number
  top_concern: string | null
  top_concern_label: string
  unread: number
  by_category: CategoryStat[]
  by_source: {
    meta:    { total: number; positive_pct: number }
    youtube: { total: number; positive_pct: number }
    amazon:  { total: number }
  }
}

interface FeedData {
  comments: Comment[]
  total: number
  has_more: boolean
}

interface TrendDay {
  date: string
  label: string
  total: number
  by_category: Record<string, number>
}

interface PeriodChange {
  first_half: number
  second_half: number
  change_pct: number
}

interface TrendData {
  days: number
  chart_data: TrendDay[]
  period_change: Record<string, PeriodChange>
  categories: { category: string; label: string; color: string }[]
  total: number
}

// ─── Config ───────────────────────────────────────────────────────────────────

const CAT: Record<string, { label: string; bg: string; text: string; Icon: any }> = {
  positive:          { label: 'Praise',           bg: 'bg-green-100',  text: 'text-green-700',  Icon: Star },
  purchase_intent:   { label: 'Purchase Intent',  bg: 'bg-blue-100',   text: 'text-blue-700',   Icon: CheckCircle2 },
  price:             { label: 'Price Concern',     bg: 'bg-orange-100', text: 'text-orange-700', Icon: DollarSign },
  trust:             { label: 'Trust Issue',       bg: 'bg-red-100',    text: 'text-red-700',    Icon: Shield },
  scam:              { label: 'Spam / Scam',       bg: 'bg-red-100',    text: 'text-red-700',    Icon: AlertCircle },
  feature_confusion: { label: 'Feature Question',  bg: 'bg-purple-100', text: 'text-purple-700', Icon: HelpCircle },
  delivery:          { label: 'Delivery',          bg: 'bg-amber-100',  text: 'text-amber-700',  Icon: Truck },
  support:           { label: 'Support Needed',    bg: 'bg-amber-100',  text: 'text-amber-700',  Icon: AlertCircle },
  other:             { label: 'Other',             bg: 'bg-gray-100',   text: 'text-gray-500',   Icon: MessageSquare },
}

// Explicit hex colors for inline styles (Tailwind purges dynamic classes)
const CAT_HEX: Record<string, string> = {
  positive:          '#4ade80',  // green-400
  purchase_intent:   '#60a5fa',  // blue-400
  price:             '#fb923c',  // orange-400
  trust:             '#f87171',  // red-400
  scam:              '#f87171',
  feature_confusion: '#c084fc',  // purple-400
  delivery:          '#fbbf24',  // amber-400
  support:           '#fbbf24',
  other:             '#d1d5db',  // gray-300
}

const BAR_CLR: Record<string, string> = {
  positive: 'bg-green-400', purchase_intent: 'bg-blue-400',
  price: 'bg-orange-400', trust: 'bg-red-400', scam: 'bg-red-400',
  feature_confusion: 'bg-purple-400', delivery: 'bg-amber-400',
  support: 'bg-amber-400', other: 'bg-gray-300',
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function timeAgo(iso: string | null): string {
  if (!iso) return ''
  const diff = Date.now() - new Date(iso).getTime()
  const m = Math.floor(diff / 60000)
  if (m < 2)  return 'just now'
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

// Group daily bars into weeks for 30d/90d views
function groupByWeek(data: TrendDay[]): TrendDay[] {
  const weeks: TrendDay[] = []
  for (let i = 0; i < data.length; i += 7) {
    const chunk = data.slice(i, i + 7)
    const by_category: Record<string, number> = {}
    for (const day of chunk) {
      for (const [cat, cnt] of Object.entries(day.by_category)) {
        by_category[cat] = (by_category[cat] ?? 0) + cnt
      }
    }
    const total = Object.values(by_category).reduce((a, b) => a + b, 0)
    const d = new Date(chunk[0].date + 'T00:00:00')
    const label = d.toLocaleDateString('en-IN', { month: 'short', day: 'numeric' })
    weeks.push({ date: chunk[0].date, label, total, by_category })
  }
  return weeks
}

// ─── Trend Chart ─────────────────────────────────────────────────────────────

function TrendChart({
  trends,
  trendDays,
  onChangeDays,
}: {
  trends: TrendData
  trendDays: number
  onChangeDays: (d: number) => void
}) {
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null)

  const grouped = trendDays <= 14
    ? trends.chart_data
    : groupByWeek(trends.chart_data)

  const maxTotal = Math.max(...grouped.map(d => d.total), 1)
  const hasAnyData = grouped.some(d => d.total > 0)

  // Notable changes — categories that moved ≥10% and have enough data
  const notableChanges = Object.entries(trends.period_change)
    .filter(([cat, d]) =>
      Math.abs(d.change_pct) >= 10 &&
      (d.first_half + d.second_half) >= 2 &&
      cat in CAT
    )
    .sort(([, a], [, b]) => Math.abs(b.change_pct) - Math.abs(a.change_pct))
    .slice(0, 6)

  // Show every Nth label to avoid crowding
  const labelStep = Math.max(1, Math.ceil(grouped.length / 8))

  return (
    <div>
      {/* Period toggles */}
      <div className="flex items-center gap-2 mb-5">
        <span className="text-xs text-gray-500 font-medium">Show:</span>
        {([7, 30, 90] as const).map(d => (
          <button
            key={d}
            onClick={() => onChangeDays(d)}
            className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
              trendDays === d
                ? 'bg-pink-600 text-white'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            {d === 7 ? 'Last 7 days' : d === 30 ? 'Last 30 days' : 'Last 90 days'}
          </button>
        ))}
      </div>

      {!hasAnyData ? (
        <div className="flex items-center justify-center h-36 rounded-lg bg-gray-50 border border-dashed border-gray-200">
          <p className="text-sm text-gray-400">No comment data in this period yet</p>
        </div>
      ) : (
        <>
          {/* Stacked bar chart */}
          <div className="flex items-end gap-px h-36 mb-1">
            {grouped.map((item, i) => {
              const heightPct = (item.total / maxTotal) * 100
              const isHovered = hoveredIdx === i
              // Stable category order (use trends.categories)
              const catOrder = trends.categories.map(c => c.category)
              const segments = catOrder
                .filter(cat => (item.by_category[cat] ?? 0) > 0)
              return (
                <div
                  key={i}
                  className="relative flex-1 flex flex-col-reverse rounded-t overflow-hidden cursor-pointer transition-opacity"
                  style={{ height: `${heightPct}%`, minHeight: item.total > 0 ? '4px' : '0' }}
                  onMouseEnter={() => setHoveredIdx(i)}
                  onMouseLeave={() => setHoveredIdx(null)}
                >
                  {segments.map(cat => (
                    <div
                      key={cat}
                      style={{
                        height: `${(item.by_category[cat] / item.total) * 100}%`,
                        backgroundColor: CAT_HEX[cat] ?? '#d1d5db',
                        opacity: isHovered ? 1 : 0.82,
                      }}
                    />
                  ))}

                  {/* Hover tooltip */}
                  {isHovered && item.total > 0 && (
                    <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 z-10 w-max max-w-[160px] rounded-lg bg-gray-900 px-2.5 py-2 text-xs text-white shadow-lg pointer-events-none">
                      <p className="font-semibold mb-1">{item.label}</p>
                      <p className="text-gray-300 mb-1">{item.total} comment{item.total !== 1 ? 's' : ''}</p>
                      {catOrder
                        .filter(cat => (item.by_category[cat] ?? 0) > 0)
                        .map(cat => (
                          <div key={cat} className="flex items-center gap-1.5">
                            <div className="h-2 w-2 rounded-full shrink-0" style={{ backgroundColor: CAT_HEX[cat] }} />
                            <span className="text-gray-300">{CAT[cat]?.label ?? cat}: {item.by_category[cat]}</span>
                          </div>
                        ))}
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          {/* X-axis labels */}
          <div className="flex gap-px">
            {grouped.map((item, i) => (
              <div key={i} className="flex-1 text-center">
                {i % labelStep === 0 && (
                  <span className="text-[10px] text-gray-400 block truncate">{item.label}</span>
                )}
              </div>
            ))}
          </div>

          {/* Legend */}
          <div className="flex flex-wrap gap-3 mt-4">
            {trends.categories.map(cat => (
              <div key={cat.category} className="flex items-center gap-1.5">
                <div className="h-3 w-3 rounded-sm shrink-0" style={{ backgroundColor: CAT_HEX[cat.category] }} />
                <span className="text-xs text-gray-600">{cat.label}</span>
              </div>
            ))}
          </div>
        </>
      )}

      {/* Period-over-period change signals */}
      {notableChanges.length > 0 && (
        <div className="mt-5 rounded-lg bg-gray-50 border border-gray-100 p-4">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
            Period Change — second half vs first half of selected window
          </p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {notableChanges.map(([cat, d]) => {
              const isUp = d.change_pct > 0
              const cfg  = CAT[cat]
              return (
                <div key={cat} className="flex items-center gap-2 rounded-lg border border-gray-100 bg-white px-3 py-2">
                  <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold ${cfg?.bg} ${cfg?.text}`}>
                    {cfg?.label ?? cat}
                  </span>
                  <span className={`flex items-center gap-0.5 text-xs font-bold ${isUp ? 'text-red-600' : 'text-green-600'}`}>
                    {isUp
                      ? <TrendingUp className="h-3 w-3" />
                      : <TrendingDown className="h-3 w-3" />}
                    {Math.abs(d.change_pct)}%
                  </span>
                  <span className="text-[10px] text-gray-400">{d.second_half} vs {d.first_half}</span>
                </div>
              )
            })}
          </div>
          <p className="text-[10px] text-gray-400 mt-2">
            Red ↑ = concern is rising (action needed). Green ↓ = concern is falling (good sign).
            Praise rising is always positive.
          </p>
        </div>
      )}
    </div>
  )
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function StatCard({ label, value, sub, color }: { label: string; value: string; sub: string; color: string }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">{label}</p>
      <p className={`text-2xl font-bold mt-1 ${color}`}>{value}</p>
      <p className="text-xs text-gray-400 mt-0.5">{sub}</p>
    </div>
  )
}

function CommentCard({ comment }: { comment: Comment }) {
  const [open, setOpen] = useState(false)
  const cfg = CAT[comment.category] ?? CAT.other

  return (
    <div className="px-5 py-4 hover:bg-gray-50 transition-colors">
      <div className="flex items-start gap-3">
        <div className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${
          comment.source === 'youtube' ? 'bg-red-100' : 'bg-blue-100'
        }`}>
          {comment.source === 'youtube'
            ? <Youtube className="h-4 w-4 text-red-600" />
            : <MessageSquare className="h-4 w-4 text-blue-600" />}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className="text-sm font-semibold text-gray-800">{comment.author_name}</span>
            <span className="text-xs text-gray-400">
              {comment.source === 'youtube'
                ? (comment.source_name ? `on "${comment.source_name}"` : 'YouTube')
                : 'Meta Ads'}
            </span>
            {comment.published_at && (
              <span className="text-xs text-gray-400">{timeAgo(comment.published_at)}</span>
            )}
          </div>
          <p className="text-sm text-gray-700 leading-relaxed">{comment.comment_text}</p>
          <div className="flex items-center gap-2 mt-2 flex-wrap">
            <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold ${cfg.bg} ${cfg.text}`}>
              <cfg.Icon className="h-3 w-3" />
              {cfg.label}
            </span>
            {comment.like_count > 0 && (
              <span className="flex items-center gap-1 text-xs text-gray-400">
                <ThumbsUp className="h-3 w-3" /> {comment.like_count}
              </span>
            )}
            {comment.suggested_reply && (
              <button
                onClick={() => setOpen(v => !v)}
                className="flex items-center gap-0.5 text-xs text-pink-600 hover:text-pink-700"
              >
                {open ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                {open ? 'Hide reply' : 'AI reply'}
              </button>
            )}
          </div>
          {open && comment.suggested_reply && (
            <div className="mt-2 rounded-lg bg-pink-50 border border-pink-100 px-3 py-2">
              <p className="text-[10px] text-gray-400 font-semibold uppercase tracking-wide mb-0.5">AI-suggested reply</p>
              <p className="text-sm text-gray-700">{comment.suggested_reply}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Search-term signals ─────────────────────────────────────────────────────

function SearchTermSignals({ workspaceId }: { workspaceId: string }) {
  const [data, setData] = useState<{ has_data: boolean; pain_terms: any[]; winning_terms: any[] } | null>(null)

  useEffect(() => {
    if (!workspaceId) return
    fetch(`/api/comments/insights?workspace_id=${workspaceId}`)
      .then(r => r.ok ? r.json() : null)
      .then(setData)
  }, [workspaceId])

  if (!data?.has_data) return null

  return (
    <div className="space-y-4">
      {data.winning_terms.length > 0 && (
        <div className="rounded-xl border border-green-200 overflow-hidden">
          <div className="bg-green-50 px-5 py-4 border-b border-green-200">
            <h2 className="text-base font-bold text-gray-900">Resonating Search Terms</h2>
            <p className="text-sm text-gray-500 mt-0.5">Paid search terms converting — what buyers actually want</p>
          </div>
          <div className="divide-y divide-gray-100">
            {data.winning_terms.slice(0, 8).map((item: any, i: number) => (
              <div key={i} className="px-5 py-3 flex items-center gap-3">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-800 truncate">{item.term}</p>
                  <p className="text-xs text-gray-400">{item.insight}</p>
                </div>
                <span className="shrink-0 text-sm font-bold text-green-700">{item.conv_rate?.toFixed(1)}% CVR</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {data.pain_terms.length > 0 && (
        <div className="rounded-xl border border-red-200 overflow-hidden">
          <div className="bg-red-50 px-5 py-4 border-b border-red-200">
            <h2 className="text-base font-bold text-gray-900">Customer Barriers — Search</h2>
            <p className="text-sm text-gray-500 mt-0.5">High spend, zero conversions — objections or irrelevant intent</p>
          </div>
          <div className="divide-y divide-gray-100">
            {data.pain_terms.slice(0, 8).map((item: any, i: number) => (
              <div key={i} className="px-5 py-3 flex items-center gap-3 bg-red-50/30">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-red-800 truncate">{item.term}</p>
                  <p className="text-xs text-gray-400">{item.insight}</p>
                </div>
                <span className="shrink-0 text-sm font-bold text-red-700">₹{item.spend?.toLocaleString('en-IN')}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

type SourceTab = 'all' | 'meta' | 'youtube' | 'amazon'

function CommentsPageInner() {
  const searchParams = useSearchParams()
  const workspaceId = searchParams.get('ws') ?? ''

  const [sentiment,  setSentiment]  = useState<SentimentData | null>(null)
  const [feed,       setFeed]       = useState<FeedData | null>(null)
  const [trends,     setTrends]     = useState<TrendData | null>(null)
  const [source,     setSource]     = useState<SourceTab>('all')
  const [trendDays,  setTrendDays]  = useState(30)
  const [feedDays,   setFeedDays]   = useState(0)    // 0 = all time
  const [loading,    setLoading]    = useState(true)
  const [trendLoad,  setTrendLoad]  = useState(false)
  const [syncing,    setSyncing]    = useState(false)
  const [syncDetail, setSyncDetail] = useState<string | null>(null)

  const loadFeed = useCallback(async (src: SourceTab, fd: number) => {
    if (!workspaceId) return
    setLoading(true)
    try {
      const [sRes, fRes] = await Promise.all([
        fetch(`/api/comments/sentiment?workspace_id=${workspaceId}`),
        fetch(`/api/comments/feed?workspace_id=${workspaceId}&source=${src}&limit=60&days=${fd}`),
      ])
      if (sRes.ok) setSentiment(await sRes.json())
      if (fRes.ok) setFeed(await fRes.json())
    } finally {
      setLoading(false)
    }
  }, [workspaceId])

  const loadTrends = useCallback(async (d: number) => {
    if (!workspaceId) return
    setTrendLoad(true)
    try {
      const r = await fetch(`/api/comments/trends?workspace_id=${workspaceId}&days=${d}&source=all`)
      if (r.ok) setTrends(await r.json())
    } finally {
      setTrendLoad(false)
    }
  }, [workspaceId])

  useEffect(() => {
    if (!workspaceId) { setLoading(false); return }
    loadFeed(source, feedDays)
    loadTrends(trendDays)
  }, [workspaceId]) // eslint-disable-line

  useEffect(() => { if (workspaceId) loadFeed(source, feedDays) }, [source, feedDays]) // eslint-disable-line
  useEffect(() => { if (workspaceId) loadTrends(trendDays) }, [trendDays])             // eslint-disable-line

  const handleSync = async () => {
    if (!workspaceId) return
    setSyncing(true)
    setSyncDetail(null)
    try {
      const r = await fetch('/api/comments/sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: workspaceId }),
      })
      const d = await r.json()
      if (!r.ok) throw new Error(d.error ?? 'Sync failed')
      if (d.synced > 0) {
        toast.success(`Synced ${d.synced} new YouTube comments`)
        loadFeed(source, feedDays)
        loadTrends(trendDays)
      } else {
        const msg = d.message ?? 'Already up to date'
        toast.info(msg)
        setSyncDetail(msg)
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Sync failed')
    } finally {
      setSyncing(false)
    }
  }

  const tabs: { id: SourceTab; label: string; count?: number; soon?: boolean }[] = [
    { id: 'all',     label: 'All',      count: sentiment?.total ?? 0 },
    { id: 'meta',    label: 'Meta Ads', count: sentiment?.by_source?.meta?.total ?? 0 },
    { id: 'youtube', label: 'YouTube',  count: sentiment?.by_source?.youtube?.total ?? 0 },
    { id: 'amazon',  label: 'Amazon',   soon: true },
  ]

  const hasData = sentiment?.has_data === true

  return (
    <div className="space-y-6">

      {/* ── Header ── */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-pink-600">
            <MessageSquare className="h-5 w-5 text-white" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Comments &amp; Reviews</h1>
            <p className="text-sm text-gray-500">
              Customer voice across Meta ads, YouTube &amp; Amazon — classified, trended, and ready to act on
            </p>
          </div>
        </div>
        <button
          onClick={handleSync}
          disabled={syncing || !workspaceId}
          className="inline-flex items-center gap-2 rounded-lg bg-pink-600 px-4 py-2 text-sm font-medium text-white hover:bg-pink-700 disabled:opacity-50 transition-colors"
        >
          {syncing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          {syncing ? 'Syncing…' : 'Sync Now'}
        </button>
      </div>

      {/* Sync detail message */}
      {syncDetail && (
        <div className="rounded-lg bg-amber-50 border border-amber-200 px-4 py-3 text-sm text-amber-800">
          <strong>Sync result:</strong> {syncDetail}
          {syncDetail.includes('disabled') && (
            <span className="block text-xs text-amber-700 mt-1">
              YouTube may have comments disabled on these videos. Check your YouTube Studio → each video → Comments setting.
            </span>
          )}
        </div>
      )}

      {/* ── Stats bar ── */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="Total Comments" value={loading ? '…' : (sentiment?.total ?? 0).toLocaleString('en-IN')} sub="Meta + YouTube + Amazon" color="text-gray-900" />
        <StatCard label="Positive / Praise" value={loading ? '…' : `${sentiment?.positive_pct ?? 0}%`} sub="Praise + purchase intent" color="text-green-700" />
        <StatCard label="Top Concern" value={loading ? '…' : (sentiment?.top_concern_label || '—')} sub="Most common objection" color="text-orange-600" />
        <StatCard label="Need Reply" value={loading ? '…' : (sentiment?.unread ?? 0).toLocaleString('en-IN')} sub="Pending response" color="text-pink-600" />
      </div>

      {/* ── Sentiment Trend Chart ── */}
      <div className="rounded-xl border border-gray-200 overflow-hidden">
        <div className="bg-gray-50 px-5 py-4 border-b border-gray-200 flex items-center justify-between">
          <div>
            <h2 className="text-base font-bold text-gray-900">Comment Sentiment Over Time</h2>
            <p className="text-sm text-gray-500 mt-0.5">
              Track how praise, concerns, and questions rise or fall — spot the impact of product/marketing changes
            </p>
          </div>
          {trendLoad && <Loader2 className="h-4 w-4 animate-spin text-gray-400" />}
        </div>
        <div className="p-5">
          {trends ? (
            <TrendChart trends={trends} trendDays={trendDays} onChangeDays={setTrendDays} />
          ) : (
            <div className="flex items-center justify-center h-36 gap-2 text-gray-400">
              <Loader2 className="h-5 w-5 animate-spin" />
            </div>
          )}
        </div>
      </div>

      {/* ── Sentiment Breakdown ── */}
      {hasData && (sentiment?.by_category?.length ?? 0) > 0 && (
        <div className="rounded-xl border border-gray-200 overflow-hidden">
          <div className="bg-gray-50 px-5 py-4 border-b border-gray-200">
            <h2 className="text-base font-bold text-gray-900">Sentiment Breakdown — All Time</h2>
            <p className="text-sm text-gray-500 mt-0.5">Overall distribution of comment themes across all sources</p>
          </div>
          <div className="p-5 space-y-3">
            {sentiment!.by_category.map(cat => (
              <div key={cat.category} className="flex items-center gap-3">
                <div className="w-40 shrink-0">
                  <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold ${CAT[cat.category]?.bg ?? 'bg-gray-100'} ${CAT[cat.category]?.text ?? 'text-gray-600'}`}>
                    {cat.label}
                  </span>
                </div>
                <div className="flex-1 h-3 rounded-full bg-gray-100 overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${BAR_CLR[cat.category] ?? 'bg-gray-300'}`}
                    style={{ width: `${cat.pct}%` }}
                  />
                </div>
                <div className="w-24 text-right shrink-0">
                  <span className="text-sm font-bold text-gray-700">{cat.pct}%</span>
                  <span className="text-xs text-gray-400 ml-1">({cat.count})</span>
                </div>
              </div>
            ))}
          </div>
          {sentiment && (sentiment.by_source.meta.total > 0 || sentiment.by_source.youtube.total > 0) && (
            <div className="border-t border-gray-100 px-5 py-3 flex flex-wrap gap-4">
              {sentiment.by_source.meta.total > 0 && (
                <div className="flex items-center gap-1.5 text-xs text-gray-500">
                  <MessageSquare className="h-3.5 w-3.5 text-blue-500" />
                  <strong className="text-gray-700">Meta Ads:</strong>
                  {sentiment.by_source.meta.total} comments · <span className="text-green-600 font-semibold">{sentiment.by_source.meta.positive_pct}% positive</span>
                </div>
              )}
              {sentiment.by_source.youtube.total > 0 && (
                <div className="flex items-center gap-1.5 text-xs text-gray-500">
                  <Youtube className="h-3.5 w-3.5 text-red-500" />
                  <strong className="text-gray-700">YouTube:</strong>
                  {sentiment.by_source.youtube.total} comments · <span className="text-green-600 font-semibold">{sentiment.by_source.youtube.positive_pct}% positive</span>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Source tabs + date filter ── */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex gap-1 rounded-xl border border-gray-200 bg-gray-50 p-1">
          {tabs.map(tab => (
            <button
              key={tab.id}
              disabled={!!tab.soon}
              onClick={() => !tab.soon && setSource(tab.id)}
              className={`flex items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                source === tab.id ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
              } ${tab.soon ? 'cursor-not-allowed opacity-50' : ''}`}
            >
              {tab.id === 'youtube' && <Youtube className="h-3.5 w-3.5 text-red-500" />}
              {tab.id === 'amazon'  && <ShoppingCart className="h-3.5 w-3.5" />}
              {tab.label}
              {tab.soon ? (
                <span className="rounded bg-gray-200 px-1 py-0.5 text-[9px] font-semibold text-gray-500">SOON</span>
              ) : (tab.count ?? 0) > 0 ? (
                <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-semibold ${source === tab.id ? 'bg-pink-100 text-pink-700' : 'bg-gray-200 text-gray-600'}`}>
                  {tab.count}
                </span>
              ) : null}
            </button>
          ))}
        </div>

        {/* Date range filter for feed */}
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-gray-500">Show:</span>
          {([
            { val: 7,  label: '7d' },
            { val: 30, label: '30d' },
            { val: 90, label: '90d' },
            { val: 0,  label: 'All' },
          ] as const).map(({ val, label }) => (
            <button
              key={val}
              onClick={() => setFeedDays(val)}
              className={`rounded-lg px-2.5 py-1 text-xs font-semibold transition-colors ${
                feedDays === val ? 'bg-gray-800 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* ── Comment Feed ── */}
      <div className="rounded-xl border border-gray-200 overflow-hidden">
        <div className="bg-gray-50 px-5 py-4 border-b border-gray-200 flex items-center justify-between">
          <div>
            <h2 className="text-base font-bold text-gray-900">Comment Feed</h2>
            <p className="text-sm text-gray-500 mt-0.5">
              {feed?.total
                ? `${feed.total} comments${feedDays > 0 ? ` in last ${feedDays} days` : ''} · sorted by newest`
                : 'All comments from connected channels'}
            </p>
          </div>
          {source === 'amazon' && (
            <span className="rounded-full bg-gray-100 px-3 py-1 text-xs font-semibold text-gray-500">Coming Soon</span>
          )}
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16 gap-2 text-gray-400">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span className="text-sm">Loading comments…</span>
          </div>
        ) : source === 'amazon' ? (
          <div className="px-5 py-14 text-center">
            <ShoppingCart className="h-10 w-10 text-gray-200 mx-auto mb-3" />
            <p className="text-base font-semibold text-gray-600">Amazon Reviews — Coming Soon</p>
            <p className="text-sm text-gray-400 mt-1.5 max-w-xs mx-auto">Connect your Amazon Seller account to pull product reviews and classify them automatically.</p>
          </div>
        ) : !hasData || !feed?.comments?.length ? (
          <div className="px-5 py-14 text-center">
            <MessageSquare className="h-10 w-10 text-gray-200 mx-auto mb-3" />
            <p className="text-base font-semibold text-gray-600">No comments in this period</p>
            <p className="text-sm text-gray-400 mt-1.5 max-w-sm mx-auto">
              {feedDays > 0
                ? `No comments found in the last ${feedDays} days. Try "All" to see everything.`
                : source === 'youtube'
                  ? 'Click "Sync Now" to fetch and classify comments from your YouTube videos.'
                  : 'Connect Meta or YouTube, then click "Sync Now" to pull your first comments.'}
            </p>
            {source === 'youtube' && workspaceId && (
              <button onClick={handleSync} disabled={syncing}
                className="mt-4 inline-flex items-center gap-2 rounded-lg bg-pink-600 px-4 py-2 text-sm font-medium text-white hover:bg-pink-700 disabled:opacity-50">
                {syncing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                Sync YouTube Comments
              </button>
            )}
            {!workspaceId && (
              <Link href="/settings" className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-pink-600 px-4 py-2 text-sm font-medium text-white hover:bg-pink-700">
                Connect Channels <ArrowUpRight className="h-3.5 w-3.5" />
              </Link>
            )}
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {feed.comments.map(c => <CommentCard key={c.id} comment={c} />)}
          </div>
        )}
      </div>

      {/* ── Search Term Signals ── */}
      <SearchTermSignals workspaceId={workspaceId} />

    </div>
  )
}

export default function CommentsPage() {
  return (
    <Suspense>
      <CommentsPageInner />
    </Suspense>
  )
}
