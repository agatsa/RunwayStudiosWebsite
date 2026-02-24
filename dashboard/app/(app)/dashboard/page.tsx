import { Suspense } from 'react'
import { Card } from '@tremor/react'
import { fetchFromFastAPI } from '@/lib/api'
import { fillDateRange } from '@/lib/utils'
import KpiSummaryCards from '@/components/dashboard/KpiSummaryCards'
import SpendChart from '@/components/dashboard/SpendChart'
import RoasChart from '@/components/dashboard/RoasChart'
import PlatformBreakdownTable from '@/components/dashboard/PlatformBreakdownTable'
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

export default async function DashboardPage({ searchParams }: PageProps) {
  const workspaceId = searchParams.ws ?? ''
  const days = parseInt(searchParams.days ?? '30', 10) || 30
  const kpi = await fetchKpi(workspaceId, days)

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
  const filledDaily = fillDateRange(data.daily, days, platforms.length > 0 ? platforms : ['meta'])

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Dashboard</h1>
          <p className="text-sm text-gray-500">{days === 1 ? 'Today' : `Last ${days} days`} · Meta</p>
        </div>
        {/* Day selector */}
        <div className="flex gap-1">
          {[
            { d: 1, label: 'Today' },
            { d: 7,  label: '7d' },
            { d: 14, label: '14d' },
            { d: 30, label: '30d' },
            { d: 60, label: '60d' },
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

      {/* KPI cards */}
      <KpiSummaryCards summary={data.summary} />

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
    </div>
  )
}
