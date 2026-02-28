import { Suspense } from 'react'
import { Card } from '@tremor/react'
import { fetchFromFastAPI } from '@/lib/api'
import { fillDateRange } from '@/lib/utils'
import KpiSummaryCards from '@/components/dashboard/KpiSummaryCards'
import SpendChart from '@/components/dashboard/SpendChart'
import RoasChart from '@/components/dashboard/RoasChart'
import PlatformBreakdownTable from '@/components/dashboard/PlatformBreakdownTable'
import ChannelHealthRow from '@/components/dashboard/ChannelHealthRow'
import AiOpportunities from '@/components/dashboard/AiOpportunities'
import type { KpiSummaryResponse } from '@/lib/types'

interface PageProps {
  searchParams: { ws?: string; days?: string }
}

async function fetchKpi(workspaceId: string, days: number): Promise<KpiSummaryResponse | null> {
  if (!workspaceId) return null
  try {
    const r = await fetchFromFastAPI(`/kpi/summary?workspace_id=${workspaceId}&days=${days}`)
    if (!r.ok) return null
    return r.json()
  } catch {
    return null
  }
}

async function fetchDailyBrief(workspaceId: string) {
  if (!workspaceId) return null
  try {
    const r = await fetchFromFastAPI(`/ai/daily-brief?workspace_id=${workspaceId}`)
    if (!r.ok) return null
    return r.json()
  } catch {
    return null
  }
}

// Brand Equity: GA4 organic signals + YouTube channel authority
// eslint-disable-next-line @typescript-eslint/no-explicit-any
async function fetchBrandEquity(workspaceId: string): Promise<{ ga4: any | null; youtube: any | null }> {
  const [ga4, youtube] = await Promise.all([
    fetchFromFastAPI(`/ga4/overview?workspace_id=${workspaceId}&days=30`)
      .then(r => (r.ok ? r.json() : null))
      .catch(() => null),
    fetchFromFastAPI(`/youtube/channel-stats?workspace_id=${workspaceId}&days=30`)
      .then(r => (r.ok ? r.json() : null))
      .catch(() => null),
  ])
  return { ga4, youtube }
}

export default async function DashboardPage({ searchParams }: PageProps) {
  const workspaceId = searchParams.ws ?? ''
  const days = parseInt(searchParams.days ?? '365', 10) || 365
  const [kpi, brief, brandEquity] = await Promise.all([
    fetchKpi(workspaceId, days),
    fetchDailyBrief(workspaceId),
    workspaceId ? fetchBrandEquity(workspaceId) : Promise.resolve({ ga4: null, youtube: null }),
  ])

  const emptyKpi: KpiSummaryResponse = {
    summary: {
      spend: 0, roas: 0, impressions: 0, clicks: 0, conversions: 0, revenue: 0, ctr: 0,
      platform_breakdown: {},
    },
    daily: [],
    workspace_id: workspaceId,
    days,
  }

  const data = kpi ?? emptyKpi

  if (!workspaceId) {
    return (
      <div className="flex h-64 items-center justify-center rounded-xl border-2 border-dashed border-gray-200">
        <p className="text-gray-500">Select a workspace to view your dashboard</p>
      </div>
    )
  }

  const platforms = Array.from(new Set(data.daily.map(r => r.platform)))
  // Cap chart points at 180 to keep rendering snappy (for "All" / 365d view sample weekly)
  const chartDays = Math.min(days, 180)
  const filledDaily = fillDateRange(data.daily, chartDays, platforms.length > 0 ? platforms : ['meta'])

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Dashboard</h1>
          <p className="text-sm text-gray-500">{days === 1 ? 'Today' : days === 365 ? 'All time' : `Last ${days} days`} · All platforms</p>
        </div>
        {/* Day selector */}
        <div className="flex gap-1">
          {[
            { d: 1,   label: 'Today' },
            { d: 7,   label: '7d' },
            { d: 30,  label: '30d' },
            { d: 90,  label: '90d' },
            { d: 365, label: 'All' },
          ].map(({ d, label }) => (
            <a
              key={d}
              href={`/dashboard?ws=${workspaceId}&days=${d}`}
              className={`rounded px-3 py-1 text-sm font-medium transition-colors ${
                days === d
                  ? 'bg-brand-600 text-white'
                  : 'bg-white text-gray-600 border border-gray-200 hover:bg-gray-50'
              }`}
            >
              {label}
            </a>
          ))}
        </div>
      </div>

      {/* ── TODAY'S GROWTH ACTIONS — top of page, collapsible ── */}
      <AiOpportunities
        opportunities={brief?.opportunities ?? []}
        workspaceId={workspaceId}
        generatedAt={brief?.generated_at ?? null}
        cached={brief?.cached ?? false}
      />

      {/* KPI cards */}
      <KpiSummaryCards summary={data.summary} />

      {/* All channels at a glance */}
      <ChannelHealthRow workspaceId={workspaceId} summary={data.summary} days={days} />

      {/* Charts */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <h2 className="mb-4 text-sm font-semibold text-gray-700">Daily Spend</h2>
          <Suspense fallback={<div className="h-48 animate-pulse rounded bg-gray-100" />}>
            <SpendChart daily={filledDaily} />
          </Suspense>
        </Card>
        <Card>
          <h2 className="mb-4 text-sm font-semibold text-gray-700">Daily ROAS</h2>
          <Suspense fallback={<div className="h-48 animate-pulse rounded bg-gray-100" />}>
            <RoasChart daily={filledDaily} />
          </Suspense>
        </Card>
      </div>

      {/* Platform breakdown */}
      <Card>
        <h2 className="mb-4 text-sm font-semibold text-gray-700">Platform Breakdown</h2>
        <PlatformBreakdownTable summary={data.summary} />
      </Card>

      {/* ── INTELLIGENCE WIDGETS — real data ── */}

      {/* Conversion Funnel — impressions → clicks → conversions with per-platform efficiency */}
      {(() => {
        const s = data.summary
        const breakdown = data.summary.platform_breakdown
        const hasData = s.impressions > 0 || s.clicks > 0

        // Per-platform funnel rows — sorted by spend desc
        const PSTYLE: Record<string, { label: string; bar: string; text: string }> = {
          meta:   { label: 'Meta',   bar: 'bg-blue-400',   text: 'text-blue-700' },
          google: { label: 'Google', bar: 'bg-emerald-400', text: 'text-emerald-700' },
          amazon: { label: 'Amazon', bar: 'bg-orange-400',  text: 'text-orange-700' },
        }
        const platforms = Object.entries(breakdown)
          .filter(([, v]) => v.impressions > 0 || v.clicks > 0)
          .sort((a, b) => b[1].spend - a[1].spend)

        const fmtN = (n: number) =>
          n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1000 ? `${(n / 1000).toFixed(1)}K` : String(Math.round(n))

        return (
          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-sm font-semibold text-gray-900">Conversion Funnel</h2>
                <p className="text-xs text-gray-400">
                  Impression → Click → Conversion efficiency · {days === 1 ? 'Today' : days === 365 ? 'All time' : `Last ${days} days`}
                </p>
              </div>
              <a href={`/awareness?ws=${workspaceId}`} className="text-xs text-violet-600 hover:underline">
                Full funnel →
              </a>
            </div>

            {!hasData ? (
              <p className="text-sm text-gray-400 text-center py-4">
                No impression data for this period. Try &quot;All&quot; or upload reports.
              </p>
            ) : (
              <div className="space-y-4">
                {/* Blended funnel */}
                <div className="grid grid-cols-3 gap-2 text-center">
                  {[
                    { label: 'Impressions', value: fmtN(s.impressions), sub: 'reach', color: 'text-gray-800', bg: 'bg-gray-50' },
                    { label: 'Clicks',      value: fmtN(s.clicks),      sub: `${s.ctr > 0 ? s.ctr.toFixed(2) : '—'}% CTR`, color: 'text-blue-700', bg: 'bg-blue-50' },
                    { label: 'Conversions', value: s.conversions > 0 ? fmtN(s.conversions) : '—',
                      sub: s.conversions > 0 && s.clicks > 0
                        ? `${((s.conversions / s.clicks) * 100).toFixed(1)}% CVR`
                        : 'no data',
                      color: 'text-green-700', bg: 'bg-green-50' },
                  ].map(t => (
                    <div key={t.label} className={`rounded-lg ${t.bg} p-2.5`}>
                      <p className="text-[10px] text-gray-400">{t.label}</p>
                      <p className={`text-base font-bold ${t.color}`}>{t.value}</p>
                      <p className="text-[10px] text-gray-500">{t.sub}</p>
                    </div>
                  ))}
                </div>

                {/* Funnel arrow */}
                {s.impressions > 0 && s.clicks > 0 && (
                  <div className="flex items-center gap-1 text-[10px] text-gray-400 justify-center">
                    <span className="font-medium text-gray-600">{fmtN(s.impressions)}</span>
                    <span>→ {s.ctr.toFixed(2)}% CTR →</span>
                    <span className="font-medium text-blue-600">{fmtN(s.clicks)}</span>
                    {s.conversions > 0 && (
                      <>
                        <span>→ {((s.conversions / s.clicks) * 100).toFixed(1)}% CVR →</span>
                        <span className="font-medium text-green-600">{fmtN(s.conversions)}</span>
                      </>
                    )}
                  </div>
                )}

                {/* Per-platform efficiency bars */}
                {platforms.length > 1 && (
                  <div className="space-y-2 pt-2 border-t border-gray-100">
                    <p className="text-[10px] text-gray-400 font-medium uppercase tracking-wide">Per Platform CTR</p>
                    {platforms.map(([platform, v]) => {
                      const style = PSTYLE[platform] ?? { label: platform, bar: 'bg-gray-300', text: 'text-gray-700' }
                      const ctr = v.impressions > 0 ? (v.clicks / v.impressions) * 100 : 0
                      const maxCtr = Math.max(...platforms.map(([, p]) => p.impressions > 0 ? (p.clicks / p.impressions) * 100 : 0), 1)
                      return (
                        <div key={platform} className="flex items-center gap-2 text-xs">
                          <span className={`w-12 shrink-0 font-medium ${style.text}`}>{style.label}</span>
                          <div className="flex-1 h-1.5 rounded-full bg-gray-100">
                            <div className={`h-1.5 rounded-full ${style.bar}`} style={{ width: `${Math.max((ctr / maxCtr) * 100, 2)}%` }} />
                          </div>
                          <span className="w-14 text-right font-mono text-gray-700">{ctr.toFixed(2)}% CTR</span>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )}
          </div>
        )
      })()}

      {/* Cross-Channel ROAS + Blended Performance row */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Cross-Channel ROAS — real data */}
        {(() => {
          const breakdown = data.summary.platform_breakdown
          const PLATFORM_STYLE: Record<string, { label: string; dot: string; bar: string; text: string }> = {
            meta:   { label: 'Meta Ads',    dot: 'bg-blue-500',   bar: 'bg-blue-400',   text: 'text-blue-700' },
            google: { label: 'Google Ads',  dot: 'bg-green-500',  bar: 'bg-green-400',  text: 'text-green-700' },
            amazon: { label: 'Amazon Ads',  dot: 'bg-orange-500', bar: 'bg-orange-400', text: 'text-orange-700' },
          }
          const entries = Object.entries(breakdown)
            .filter(([, v]) => v.spend > 0)
            .sort((a, b) => b[1].roas - a[1].roas)
          const maxRoas = Math.max(...entries.map(([, v]) => v.roas), data.summary.roas, 1)
          return (
            <div className="rounded-xl border border-gray-200 bg-white p-5">
              <div className="mb-4">
                <h2 className="text-sm font-semibold text-gray-900">Cross-Channel ROAS</h2>
                <p className="text-xs text-gray-400">
                  {days === 1 ? 'Today' : days === 365 ? 'All time' : `Last ${days} days`} · higher is better · target 2.5×
                </p>
              </div>
              {entries.length === 0 ? (
                <p className="text-sm text-gray-400 text-center py-4">
                  No spend data. Connect platforms or upload reports.
                </p>
              ) : (
                <div className="space-y-3">
                  {entries.map(([platform, v]) => {
                    const style = PLATFORM_STYLE[platform] ?? { label: platform, dot: 'bg-gray-400', bar: 'bg-gray-300', text: 'text-gray-700' }
                    const spendFmt = v.spend >= 1e5
                      ? `₹${(v.spend / 1e5).toFixed(1)}L`
                      : `₹${(v.spend / 1000).toFixed(1)}K`
                    return (
                      <div key={platform} className="flex items-center gap-3 text-xs">
                        <div className={`h-2.5 w-2.5 rounded-full ${style.dot} shrink-0`} />
                        <span className="w-22 font-medium text-gray-700 shrink-0">{style.label}</span>
                        <div className="flex-1 h-1.5 rounded-full bg-gray-100">
                          <div
                            className={`h-1.5 rounded-full ${style.bar}`}
                            style={{ width: `${Math.max((v.roas / maxRoas) * 100, 2)}%` }}
                          />
                        </div>
                        <span className={`font-bold ${style.text} shrink-0`}>
                          {v.roas > 0 ? `${v.roas.toFixed(2)}×` : '—'}
                        </span>
                        <span className="text-gray-400 shrink-0">{spendFmt}</span>
                      </div>
                    )
                  })}
                  {/* Blended row */}
                  {data.summary.spend > 0 && (
                    <div className="flex items-center gap-3 text-xs border-t border-gray-100 pt-2">
                      <div className="h-2.5 w-2.5 rounded-full bg-violet-600 shrink-0" />
                      <span className="w-22 font-semibold text-gray-800 shrink-0">Blended</span>
                      <div className="flex-1 h-1.5 rounded-full bg-gray-100">
                        <div
                          className="h-1.5 rounded-full bg-violet-500"
                          style={{ width: `${Math.max((data.summary.roas / maxRoas) * 100, 2)}%` }}
                        />
                      </div>
                      <span className="font-bold text-violet-700 shrink-0">
                        {data.summary.roas > 0 ? `${data.summary.roas.toFixed(2)}×` : '—'}
                      </span>
                      <span className="text-gray-400 shrink-0">
                        {data.summary.spend >= 1e5
                          ? `₹${(data.summary.spend / 1e5).toFixed(1)}L`
                          : `₹${(data.summary.spend / 1000).toFixed(1)}K`}
                      </span>
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })()}

        {/* Brand Equity — derived from GA4 organic signals + YouTube authority */}
        {(() => {
          const ga4 = brandEquity.ga4
          const yt  = brandEquity.youtube

          // GA4 signals
          const sessions      = ga4?.current?.sessions ?? 0
          const users         = ga4?.current?.users ?? 0
          const newUsers      = ga4?.current?.new_users ?? 0
          const bounceRate    = ga4?.current?.bounce_rate ?? null   // e.g. 42.3
          const avgDuration   = ga4?.current?.avg_session_duration ?? null // seconds
          const returningUsers = users > 0 ? users - newUsers : 0
          const returningRate  = users > 0 ? Math.round((returningUsers / users) * 100) : null
          const engagement     = bounceRate !== null ? Math.round(100 - bounceRate) : null

          // YouTube signals
          const subs    = yt?.channel?.subscriber_count ?? null
          const ytViews = yt?.channel?.view_count ?? null
          const daily: Array<{ subscribers_gained: number; subscribers_lost: number }> = yt?.daily ?? []
          const netSubs = daily.reduce((acc, d) => acc + (d.subscribers_gained ?? 0) - (d.subscribers_lost ?? 0), 0)

          // Composite Brand Equity Score (0-100)
          const scores: number[] = []
          if (engagement !== null) scores.push(Math.min(engagement, 100))
          if (returningRate !== null) scores.push(Math.min(returningRate, 100))
          if (subs !== null) scores.push(Math.min(subs / 200, 100))   // 20K subs = 100 pts
          const equityScore = scores.length > 0
            ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length)
            : null

          const hasData = ga4 !== null || yt !== null
          const fmtSubs = (n: number) =>
            n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1000 ? `${(n / 1000).toFixed(1)}K` : String(n)
          const fmtDuration = (s: number) => {
            const m = Math.floor(s / 60), sec = Math.round(s % 60)
            return m > 0 ? `${m}m ${sec}s` : `${sec}s`
          }

          return (
            <div className="rounded-xl border border-gray-200 bg-white p-5">
              <div className="flex items-start justify-between mb-4">
                <div>
                  <h2 className="text-sm font-semibold text-gray-900">Brand Equity</h2>
                  <p className="text-xs text-gray-400">Organic strength · GA4 + YouTube · Last 30 days</p>
                </div>
                {equityScore !== null && (
                  <div className="text-right shrink-0">
                    <p className={`text-2xl font-bold ${equityScore >= 70 ? 'text-green-600' : equityScore >= 45 ? 'text-amber-600' : 'text-red-500'}`}>
                      {equityScore}<span className="text-sm font-normal text-gray-400">/100</span>
                    </p>
                    <p className="text-[10px] text-gray-400">equity score</p>
                  </div>
                )}
              </div>

              {!hasData ? (
                <div className="space-y-2 text-xs text-gray-500">
                  <p className="text-center py-2">Connect GA4 + YouTube for organic brand intelligence</p>
                  <div className="flex gap-2 justify-center">
                    <a href={`/settings?ws=${workspaceId}`} className="rounded-lg bg-violet-50 border border-violet-200 px-3 py-1.5 text-violet-700 font-medium hover:bg-violet-100">
                      Connect GA4
                    </a>
                    <a href={`/settings?ws=${workspaceId}`} className="rounded-lg bg-red-50 border border-red-200 px-3 py-1.5 text-red-700 font-medium hover:bg-red-100">
                      Connect YouTube
                    </a>
                  </div>
                </div>
              ) : (
                <div className="space-y-2.5">
                  {/* Score bar */}
                  {equityScore !== null && (
                    <div className="mb-3">
                      <div className="h-1.5 w-full rounded-full bg-gray-100">
                        <div
                          className={`h-1.5 rounded-full transition-all ${equityScore >= 70 ? 'bg-green-500' : equityScore >= 45 ? 'bg-amber-400' : 'bg-red-400'}`}
                          style={{ width: `${equityScore}%` }}
                        />
                      </div>
                      <div className="mt-1 flex justify-between text-[10px] text-gray-400">
                        <span>0</span><span>target 70+</span><span>100</span>
                      </div>
                    </div>
                  )}

                  {/* GA4 signals */}
                  {ga4 && (
                    <>
                      {returningRate !== null && (
                        <div className="flex items-center justify-between text-xs">
                          <span className="text-gray-500">🔄 Return Visitor Rate</span>
                          <span className="font-semibold text-gray-800">
                            {returningRate}%
                            <span className="ml-1 text-gray-400 font-normal">({returningUsers.toLocaleString()} of {users.toLocaleString()})</span>
                          </span>
                        </div>
                      )}
                      {engagement !== null && (
                        <div className="flex items-center justify-between text-xs">
                          <span className="text-gray-500">⚡ Engagement Score</span>
                          <span className={`font-semibold ${engagement >= 65 ? 'text-green-700' : engagement >= 45 ? 'text-amber-600' : 'text-red-600'}`}>
                            {engagement}%
                            <span className="ml-1 text-gray-400 font-normal">(100 − bounce rate)</span>
                          </span>
                        </div>
                      )}
                      {avgDuration !== null && (
                        <div className="flex items-center justify-between text-xs">
                          <span className="text-gray-500">⏱ Avg. Session Duration</span>
                          <span className="font-semibold text-gray-800">{fmtDuration(avgDuration)}</span>
                        </div>
                      )}
                      {sessions > 0 && (
                        <div className="flex items-center justify-between text-xs">
                          <span className="text-gray-500">🌐 Total Web Sessions</span>
                          <span className="font-semibold text-gray-800">{sessions.toLocaleString()}</span>
                        </div>
                      )}
                    </>
                  )}

                  {/* YouTube signals */}
                  {yt && subs !== null && (
                    <>
                      <div className="flex items-center justify-between text-xs">
                        <span className="text-gray-500">📺 YouTube Subscribers</span>
                        <span className="font-semibold text-gray-800">
                          {fmtSubs(subs)}
                          {netSubs !== 0 && (
                            <span className={`ml-1 font-normal ${netSubs > 0 ? 'text-green-600' : 'text-red-500'}`}>
                              {netSubs > 0 ? `+${netSubs}` : netSubs} this period
                            </span>
                          )}
                        </span>
                      </div>
                      {ytViews !== null && (
                        <div className="flex items-center justify-between text-xs">
                          <span className="text-gray-500">👁 Total Channel Views</span>
                          <span className="font-semibold text-gray-800">{fmtSubs(ytViews)}</span>
                        </div>
                      )}
                    </>
                  )}

                  {/* Connect prompts for missing signals */}
                  {!ga4 && (
                    <a href={`/settings?ws=${workspaceId}`} className="block text-[10px] text-violet-500 hover:underline">
                      + Connect GA4 for web engagement signals →
                    </a>
                  )}
                  {!yt && (
                    <a href={`/settings?ws=${workspaceId}`} className="block text-[10px] text-red-400 hover:underline">
                      + Connect YouTube for audience authority signals →
                    </a>
                  )}
                </div>
              )}
            </div>
          )
        })()}
      </div>

    </div>
  )
}
