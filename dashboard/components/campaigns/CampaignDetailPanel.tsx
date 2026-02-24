'use client'

import { useEffect, useState } from 'react'
import { X, Lightbulb, Loader2 } from 'lucide-react'
import { BarChart } from '@tremor/react'
import { formatINR, formatNumber, formatROAS, formatPercent } from '@/lib/utils'
import type { MetaCampaign, GoogleCampaign } from '@/lib/types'

type Campaign = (MetaCampaign | GoogleCampaign) & { _platform: 'meta' | 'google' }

interface Insights {
  campaign_id: string
  spend_today: number
  spend_total: number
  impressions_total: number
  clicks_total: number
  conversions_total: number
  revenue_total: number
  roas_total: number
  ctr_total: number
  daily: { date: string; spend: number }[]
  suggestions: string[]
}

interface Props {
  campaign: Campaign
  workspaceId: string
  onClose: () => void
}

function MetricTile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border border-gray-100 bg-gray-50 p-3">
      <p className="text-xs text-gray-500">{label}</p>
      <p className="mt-1 text-lg font-bold text-gray-900">{value}</p>
      {sub && <p className="text-xs text-gray-400">{sub}</p>}
    </div>
  )
}

export default function CampaignDetailPanel({ campaign, workspaceId, onClose }: Props) {
  const [insights, setInsights] = useState<Insights | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetch(`/api/campaigns/insights/${campaign.id}?workspace_id=${workspaceId}&days=7&platform=${campaign._platform}`)
      .then(r => r.json())
      .then(d => {
        if (d.detail) throw new Error(d.detail)
        setInsights(d)
      })
      .catch(e => setError(e instanceof Error ? e.message : 'Failed to load'))
      .finally(() => setLoading(false))
  }, [campaign.id, workspaceId, campaign._platform])

  const isActive =
    campaign.status === 'ACTIVE' ||
    (campaign as MetaCampaign).effective_status === 'ACTIVE'

  const chartData = (insights?.daily ?? []).map(d => ({
    date: d.date.slice(5),
    'Spend (₹)': d.spend,
  }))

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/20 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Slide panel */}
      <div className="fixed right-0 top-0 z-50 flex h-full w-full max-w-lg flex-col overflow-y-auto bg-white shadow-2xl">
        {/* Header */}
        <div className="flex items-start justify-between border-b border-gray-200 p-5">
          <div className="min-w-0 flex-1 pr-3">
            <div className="flex items-center gap-2">
              <span
                className={`h-2 w-2 shrink-0 rounded-full ${
                  isActive ? 'bg-green-500' : 'bg-yellow-400'
                }`}
              />
              <p className="truncate text-base font-semibold text-gray-900">
                {campaign.name}
              </p>
            </div>
            <p className="mt-0.5 text-xs text-gray-400">
              {(campaign as MetaCampaign).objective ??
               (campaign as GoogleCampaign).channel_type ??
               campaign._platform.toUpperCase()} ·{' '}
              {campaign.id}
            </p>
          </div>
          <button
            onClick={onClose}
            className="shrink-0 rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Body */}
        {loading ? (
          <div className="flex flex-1 items-center justify-center gap-2 text-sm text-gray-400">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading insights…
          </div>
        ) : error ? (
          <div className="p-5 text-sm text-red-500">{error}</div>
        ) : (
          <div className="flex-1 space-y-6 p-5">
            {/* Today's spend */}
            <div className="rounded-xl bg-blue-50 p-4">
              <p className="text-xs font-medium text-blue-600">Today&apos;s Spend</p>
              <p className="mt-1 text-3xl font-bold text-blue-700">
                {formatINR(insights?.spend_today ?? 0)}
              </p>
              <p className="mt-1 text-xs text-blue-500">
                Daily budget:{' '}
                {formatINR(
                  (campaign as MetaCampaign).daily_budget_inr ??
                  (campaign as GoogleCampaign).daily_budget_inr ??
                  null
                )}
              </p>
            </div>

            {/* 7-day metrics grid */}
            <div>
              <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-500">
                Last 7 Days
              </h3>
              <div className="grid grid-cols-2 gap-2">
                <MetricTile
                  label="Total Spend"
                  value={formatINR(insights?.spend_total ?? 0)}
                />
                <MetricTile
                  label="ROAS"
                  value={formatROAS(insights?.roas_total ?? 0)}
                  sub="target 2.5x"
                />
                <MetricTile
                  label="Impressions"
                  value={formatNumber(insights?.impressions_total ?? 0)}
                />
                <MetricTile
                  label="Clicks"
                  value={formatNumber(insights?.clicks_total ?? 0)}
                  sub={`CTR ${formatPercent(insights?.ctr_total ?? 0)}`}
                />
                <MetricTile
                  label="Conversions"
                  value={formatNumber(insights?.conversions_total ?? 0)}
                />
                <MetricTile
                  label="Revenue"
                  value={formatINR(insights?.revenue_total ?? 0)}
                />
              </div>
            </div>

            {/* Spend trend chart */}
            {chartData.length > 0 && (
              <div>
                <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-500">
                  Daily Spend Trend
                </h3>
                <BarChart
                  data={chartData}
                  index="date"
                  categories={['Spend (₹)']}
                  colors={['blue']}
                  valueFormatter={(v: number) => formatINR(v)}
                  showLegend={false}
                  yAxisWidth={72}
                  className="h-36"
                />
              </div>
            )}

            {/* AI suggestions */}
            <div>
              <div className="mb-3 flex items-center gap-1.5">
                <Lightbulb className="h-3.5 w-3.5 text-yellow-500" />
                <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                  AI Suggestions
                </h3>
              </div>
              <ul className="space-y-2">
                {(insights?.suggestions ?? []).map((s, i) => (
                  <li
                    key={i}
                    className="flex items-start gap-2 rounded-lg bg-yellow-50 px-3 py-2.5 text-sm text-gray-700"
                  >
                    <span className="mt-0.5 shrink-0 text-xs font-bold text-yellow-600">
                      {i + 1}
                    </span>
                    {s}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </div>
    </>
  )
}
