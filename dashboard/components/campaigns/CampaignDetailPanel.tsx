'use client'

import { useEffect, useState } from 'react'
import { X, Lightbulb, Loader2 } from 'lucide-react'
import { BarChart } from '@tremor/react'
import { formatINR, formatNumber, formatROAS, formatPercent } from '@/lib/utils'
import type { MetaCampaign, GoogleCampaign } from '@/lib/types'
import CampaignBreakdown from './CampaignBreakdown'

type Campaign = (MetaCampaign | GoogleCampaign) & { _platform: 'meta' | 'google'; _source?: 'excel_upload' }

interface KeywordRow {
  id: string
  keyword: string
  match_type: string
  ad_group_name: string
  quality_score: number | null
  spend: number
  clicks: number
  conversions: number
  impressions: number
  cpc: number
  ctr: number
}

interface SearchTermRow {
  id: string
  search_term: string
  keyword: string
  match_type: string
  spend: number
  clicks: number
  conversions: number
}

interface AdGroupRow {
  id: string
  name: string
  spend: number
  clicks: number
  conversions: number
  revenue: number
  roas: number
}

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
  ad_groups?: AdGroupRow[]
  keywords?: KeywordRow[]
  search_terms?: SearchTermRow[]
  has_keyword_data?: boolean
  has_search_term_data?: boolean
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

function QsBadge({ qs }: { qs: number | null }) {
  if (qs === null) return <span className="text-gray-400">—</span>
  const color = qs >= 7 ? 'text-green-700 bg-green-100' : qs >= 4 ? 'text-yellow-700 bg-yellow-100' : 'text-red-700 bg-red-100'
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-semibold ${color}`}>
      {qs}/10
    </span>
  )
}

function MatchBadge({ match }: { match: string }) {
  const label = match === 'EXACT' ? 'Exact' : match === 'PHRASE' ? 'Phrase' : 'Broad'
  const color = match === 'EXACT' ? 'bg-blue-100 text-blue-700' : match === 'PHRASE' ? 'bg-purple-100 text-purple-700' : 'bg-gray-100 text-gray-600'
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ${color}`}>
      {label}
    </span>
  )
}

type Tab = 'overview' | 'keywords' | 'search_terms' | 'breakdown'

export default function CampaignDetailPanel({ campaign, workspaceId, onClose }: Props) {
  const [insights, setInsights] = useState<Insights | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<Tab>('overview')

  useEffect(() => {
    setLoading(true)
    setError(null)
    setActiveTab('overview')
    const url = campaign._source === 'excel_upload'
      ? `/api/upload/campaign-insights/${campaign.id}?workspace_id=${workspaceId}&days=365`
      : `/api/campaigns/insights/${campaign.id}?workspace_id=${workspaceId}&days=7&platform=${campaign._platform}`
    fetch(url)
      .then(r => r.json())
      .then(d => {
        if (d.detail) throw new Error(d.detail)
        setInsights(d)
      })
      .catch(e => setError(e instanceof Error ? e.message : 'Failed to load'))
      .finally(() => setLoading(false))
  }, [campaign.id, workspaceId, campaign._platform, campaign._source])

  const isActive =
    campaign.status === 'ACTIVE' ||
    (campaign as MetaCampaign).effective_status === 'ACTIVE'

  const chartData = (insights?.daily ?? []).map(d => ({
    date: d.date.slice(5),
    'Spend (₹)': d.spend,
  }))

  const showTabs = (campaign._source === 'excel_upload' && insights?.has_keyword_data) || campaign._platform === 'meta'
  const showBreakdown = campaign._platform === 'meta' && campaign._source !== 'excel_upload'

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

        {/* Tab bar */}
        {showTabs && !loading && (
          <div className="flex border-b border-gray-200 bg-gray-50 overflow-x-auto">
            {([
              'overview',
              ...(campaign._source === 'excel_upload' && insights?.has_keyword_data ? ['keywords'] : []),
              ...(campaign._source === 'excel_upload' && insights?.has_search_term_data ? ['search_terms'] : []),
              ...(showBreakdown ? ['breakdown'] : []),
            ] as Tab[]).map(tab => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`shrink-0 px-5 py-2.5 text-sm font-medium transition-colors ${
                  activeTab === tab
                    ? 'border-b-2 border-blue-600 text-blue-600 bg-white'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                {tab === 'overview' ? 'Overview'
                  : tab === 'keywords' ? `Keywords (${insights?.keywords?.length ?? 0})`
                  : tab === 'search_terms' ? `Search Terms (${insights?.search_terms?.length ?? 0})`
                  : 'Breakdown'}
              </button>
            ))}
          </div>
        )}

        {/* Body */}
        {loading ? (
          <div className="flex flex-1 items-center justify-center gap-2 text-sm text-gray-400">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading insights…
          </div>
        ) : error ? (
          <div className="p-5 text-sm text-red-500">{error}</div>
        ) : activeTab === 'keywords' ? (
          <KeywordsTab keywords={insights?.keywords ?? []} />
        ) : activeTab === 'search_terms' ? (
          <SearchTermsTab searchTerms={insights?.search_terms ?? []} />
        ) : activeTab === 'breakdown' ? (
          <CampaignBreakdown campaignId={campaign.id} workspaceId={workspaceId} />
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
              <h3 className="mb-3 text-sm font-semibold text-gray-700">
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
                <h3 className="mb-3 text-sm font-semibold text-gray-700">
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
                <h3 className="text-sm font-semibold text-gray-700">
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

// ── Keywords tab ──────────────────────────────────────────────────────────────

function KeywordsTab({ keywords }: { keywords: KeywordRow[] }) {
  if (!keywords.length) {
    return <div className="p-8 text-center text-sm text-gray-400">No keyword data available.</div>
  }

  const sorted = [...keywords].sort((a, b) => b.spend - a.spend)

  return (
    <div className="flex-1 overflow-x-auto p-5">
      <p className="mb-3 text-xs text-gray-500">
        Rows in <span className="rounded bg-red-100 px-1 text-red-700">red</span> = spend &gt;₹1,000 with 0 conversions (wasted spend).
      </p>
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-gray-200 text-left text-gray-500">
            <th className="pb-2 pr-3 font-medium">Keyword</th>
            <th className="pb-2 pr-3 font-medium">Match</th>
            <th className="pb-2 pr-3 font-medium">QS</th>
            <th className="pb-2 pr-3 font-medium text-right">Spend</th>
            <th className="pb-2 pr-3 font-medium text-right">CPC</th>
            <th className="pb-2 pr-3 font-medium text-right">CTR</th>
            <th className="pb-2 font-medium text-right">Conv</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map(kw => {
            const isWasted = kw.spend > 1000 && kw.conversions === 0
            return (
              <tr
                key={kw.id}
                className={`border-b border-gray-100 ${isWasted ? 'bg-red-50' : 'hover:bg-gray-50'}`}
              >
                <td className="py-2 pr-3">
                  <span className={`font-medium ${isWasted ? 'text-red-800' : 'text-gray-800'}`}>
                    {kw.keyword}
                  </span>
                  {kw.ad_group_name && (
                    <p className="text-gray-400 truncate max-w-[140px]">{kw.ad_group_name}</p>
                  )}
                </td>
                <td className="py-2 pr-3">
                  <MatchBadge match={kw.match_type} />
                </td>
                <td className="py-2 pr-3">
                  <QsBadge qs={kw.quality_score} />
                </td>
                <td className={`py-2 pr-3 text-right font-medium ${isWasted ? 'text-red-700' : 'text-gray-900'}`}>
                  {formatINR(kw.spend)}
                </td>
                <td className="py-2 pr-3 text-right text-gray-700">{formatINR(kw.cpc)}</td>
                <td className="py-2 pr-3 text-right text-gray-700">{formatPercent(kw.ctr)}</td>
                <td className="py-2 text-right text-gray-700">{kw.conversions}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ── Search Terms tab ──────────────────────────────────────────────────────────

function SearchTermsTab({ searchTerms }: { searchTerms: SearchTermRow[] }) {
  if (!searchTerms.length) {
    return <div className="p-8 text-center text-sm text-gray-400">No search term data available.</div>
  }

  const sorted = [...searchTerms].sort((a, b) => b.spend - a.spend)

  return (
    <div className="flex-1 overflow-x-auto p-5">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-gray-200 text-left text-gray-500">
            <th className="pb-2 pr-3 font-medium">Search Term</th>
            <th className="pb-2 pr-3 font-medium">Keyword</th>
            <th className="pb-2 pr-3 font-medium text-right">Spend</th>
            <th className="pb-2 pr-3 font-medium text-right">Clicks</th>
            <th className="pb-2 font-medium text-right">Conv</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map(st => (
            <tr key={st.id} className="border-b border-gray-100 hover:bg-gray-50">
              <td className="py-2 pr-3 font-medium text-gray-800 max-w-[160px]">
                <span className="block truncate">{st.search_term}</span>
              </td>
              <td className="py-2 pr-3 text-gray-500 max-w-[120px]">
                {st.keyword ? (
                  <span className="block truncate">
                    {st.keyword}
                    {st.match_type && (
                      <span className="ml-1 text-gray-400">[{st.match_type.toLowerCase()}]</span>
                    )}
                  </span>
                ) : (
                  <span className="text-gray-300">—</span>
                )}
              </td>
              <td className="py-2 pr-3 text-right font-medium text-gray-900">{formatINR(st.spend)}</td>
              <td className="py-2 pr-3 text-right text-gray-700">{formatNumber(st.clicks)}</td>
              <td className="py-2 text-right text-gray-700">{st.conversions}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
