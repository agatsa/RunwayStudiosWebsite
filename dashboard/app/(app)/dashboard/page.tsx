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

export default async function DashboardPage({ searchParams }: PageProps) {
  const workspaceId = searchParams.ws ?? ''
  const days = parseInt(searchParams.days ?? '30', 10) || 30
  const [kpi, brief] = await Promise.all([
    fetchKpi(workspaceId, days),
    fetchDailyBrief(workspaceId),
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

      {/* Info banner: Google excel data is outside selected window */}
      {days < 90 && data.summary.platform_breakdown['google'] === undefined && (
        <div className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2.5 text-xs text-amber-700">
          <svg className="h-3.5 w-3.5 shrink-0" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
          </svg>
          <span>
            Your uploaded Google Ads report data is from an earlier period.
            {' '}<a href={`/dashboard?ws=${workspaceId}&days=90`} className="font-semibold underline">Switch to 90d</a>
            {' '}or{' '}
            <a href={`/dashboard?ws=${workspaceId}&days=365`} className="font-semibold underline">All</a>
            {' '}to include it.
          </span>
        </div>
      )}

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

      {/* ── INTELLIGENCE PREVIEW WIDGETS ── */}

      {/* Awareness Funnel Mini Widget */}
      <div className="rounded-xl border border-gray-200 bg-white p-5">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-sm font-semibold text-gray-900">Awareness Funnel Health</h2>
            <p className="text-xs text-gray-400">Which stages of the buyer journey are you investing in?</p>
          </div>
          <a href={`/awareness?ws=${workspaceId}`} className="text-xs text-violet-600 hover:underline">View full funnel →</a>
        </div>
        <div className="space-y-2">
          {[
            { stage: 'UNAWARE', pct: 15, color: 'bg-gray-300', desc: 'YouTube reach, Meta awareness' },
            { stage: 'PROBLEM AWARE', pct: 20, color: 'bg-blue-300', desc: 'Educational content, SEO' },
            { stage: 'SOLUTION AWARE', pct: 25, color: 'bg-indigo-400', desc: 'Generic search, YouTube ads' },
            { stage: 'PRODUCT AWARE', pct: 22, color: 'bg-purple-400', desc: 'Brand search, remarketing' },
            { stage: 'MOST AWARE', pct: 18, color: 'bg-green-500', desc: 'Intent search, cart abandon' },
          ].map(s => (
            <div key={s.stage} className="flex items-center gap-3 text-xs">
              <span className="w-32 shrink-0 font-medium text-gray-600">{s.stage}</span>
              <div className="flex-1 h-2 rounded-full bg-gray-100">
                <div className={`h-2 rounded-full ${s.color} opacity-40`} style={{ width: `${s.pct * 4}%` }} />
              </div>
              <span className="w-40 text-gray-400 text-[10px]">{s.desc}</span>
            </div>
          ))}
        </div>
        <p className="mt-3 text-[10px] text-gray-400">Connect all channels to see real spend allocation per funnel stage</p>
      </div>

      {/* Cross-channel ROAS + Brand Equity row */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Cross-channel ROAS */}
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-sm font-semibold text-gray-900">Cross-Channel ROAS</h2>
              <p className="text-xs text-gray-400">Meta vs Google vs YouTube — blended view</p>
            </div>
            <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-medium text-gray-500">Preview</span>
          </div>
          <div className="space-y-3 opacity-50">
            {[
              { platform: 'Meta Ads', roas: 3.2, spend: '₹45,000', color: 'bg-blue-500' },
              { platform: 'Google Ads', roas: 4.8, spend: '₹28,000', color: 'bg-green-500' },
              { platform: 'YouTube Ads', roas: 1.4, spend: '₹12,000', color: 'bg-red-500', note: '+ brand lift' },
              { platform: 'Blended', roas: 3.6, spend: '₹85,000', color: 'bg-violet-600' },
            ].map(p => (
              <div key={p.platform} className="flex items-center gap-3 text-xs">
                <div className={`h-2.5 w-2.5 rounded-full ${p.color} shrink-0`} />
                <span className="w-24 font-medium text-gray-700">{p.platform}</span>
                <div className="flex-1 h-1.5 rounded-full bg-gray-100">
                  <div className={`h-1.5 rounded-full ${p.color}`} style={{ width: `${p.roas * 15}%` }} />
                </div>
                <span className="font-bold text-gray-800">{p.roas}x</span>
                <span className="text-gray-400">{p.spend}</span>
              </div>
            ))}
          </div>
          <p className="mt-3 text-[10px] text-gray-400">Connect all ad platforms for live cross-channel ROAS</p>
        </div>

        {/* Brand Equity Score */}
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-sm font-semibold text-gray-900">Brand Equity Score</h2>
              <p className="text-xs text-gray-400">Computed from brand search lift + YouTube subscriber velocity</p>
            </div>
            <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-medium text-gray-500">Preview</span>
          </div>
          <div className="flex items-center justify-center opacity-40">
            <div className="text-center">
              <div className="relative flex h-24 w-24 items-center justify-center rounded-full border-8 border-violet-200 mx-auto">
                <div className="absolute inset-0 rounded-full border-8 border-violet-500" style={{ clipPath: 'polygon(0 0, 68% 0, 68% 100%, 0 100%)' }} />
                <span className="text-2xl font-bold text-gray-800">68</span>
              </div>
              <p className="mt-2 text-xs font-medium text-gray-600">Brand Equity: 68/100</p>
              <div className="mt-2 grid grid-cols-3 gap-2 text-[10px] text-gray-500">
                <div className="text-center"><p className="font-bold text-gray-700">+340%</p><p>Brand searches</p></div>
                <div className="text-center"><p className="font-bold text-gray-700">2.3K</p><p>New subs/mo</p></div>
                <div className="text-center"><p className="font-bold text-gray-700">4.2★</p><p>Review rating</p></div>
              </div>
            </div>
          </div>
          <p className="mt-3 text-[10px] text-gray-400 text-center">Connect Search Console + YouTube for live brand equity tracking</p>
        </div>
      </div>

      {/* AI Growth Opportunities — real Claude analysis */}
      <div className="rounded-xl border border-amber-200 bg-amber-50/40 p-5">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-sm font-semibold text-gray-900">Today&apos;s Growth Actions</h2>
            <p className="text-xs text-gray-400">AI-analysed from your real campaign data · click &quot;Create Task&quot; to add to Approvals queue</p>
          </div>
          <a href={`/approvals?ws=${workspaceId}`} className="text-xs text-amber-600 hover:underline">View queue →</a>
        </div>
        <AiOpportunities
          opportunities={brief?.opportunities ?? []}
          workspaceId={workspaceId}
          generatedAt={brief?.generated_at ?? null}
          cached={brief?.cached ?? false}
        />
      </div>
    </div>
  )
}
