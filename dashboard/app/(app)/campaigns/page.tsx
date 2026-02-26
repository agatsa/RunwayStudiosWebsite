import { fetchFromFastAPI } from '@/lib/api'
import CampaignSection from '@/components/campaigns/CampaignSection'
import type { MetaCampaignsResponse, MetaCampaign } from '@/lib/types'
import { formatINR } from '@/lib/utils'
import { TrendingUp, MousePointer, ShoppingCart, DollarSign } from 'lucide-react'

interface PageProps {
  searchParams: { ws?: string }
}

interface UploadedCampaign {
  id: string
  name: string
  status: string
  effective_status: string
  platform: string
  _source: 'excel_upload'
}

async function fetchMeta(wsId: string): Promise<MetaCampaignsResponse | null> {
  try {
    const r = await fetchFromFastAPI(`/meta/campaigns?workspace_id=${wsId}`)
    if (!r.ok) return null
    return r.json()
  } catch { return null }
}

async function fetchUploaded(wsId: string): Promise<{ campaigns: UploadedCampaign[]; platforms: string[] } | null> {
  try {
    const r = await fetchFromFastAPI(`/upload/campaigns?workspace_id=${wsId}&days=365`)
    if (!r.ok) return null
    return r.json()
  } catch { return null }
}

async function fetchKpiSummary(wsId: string) {
  try {
    const r = await fetchFromFastAPI(`/kpi/summary?workspace_id=${wsId}&days=30`)
    if (!r.ok) return null
    return r.json()
  } catch { return null }
}

export default async function CampaignsPage({ searchParams }: PageProps) {
  const workspaceId = searchParams.ws ?? ''

  if (!workspaceId) {
    return (
      <div className="flex h-64 items-center justify-center rounded-xl border-2 border-dashed border-gray-200">
        <p className="text-gray-500">Select a workspace to view campaigns</p>
      </div>
    )
  }

  const [metaData, uploadedData, kpi] = await Promise.all([
    fetchMeta(workspaceId),
    fetchUploaded(workspaceId),
    fetchKpiSummary(workspaceId),
  ])

  const liveMeta: (MetaCampaign & { _platform: 'meta' })[] = (metaData?.campaigns ?? []).map(c => ({ ...c, _platform: 'meta' as const }))
  const uploadedMeta = (uploadedData?.campaigns ?? [])
    .filter(c => c.platform === 'meta')
    .map(c => ({ ...c, _platform: 'meta' as const }))
  const metaCampaigns = liveMeta.length > 0 ? liveMeta : (uploadedMeta as unknown as (MetaCampaign & { _platform: 'meta'; _source?: 'excel_upload' })[])

  const totalCount = metaCampaigns.length
  const hasUploadedMeta = liveMeta.length === 0 && uploadedMeta.length > 0

  // KPI summary (last 30 days) — Meta only
  const summary = kpi?.summary ?? kpi
  const metaBreakdown = summary?.platform_breakdown?.meta
  const spend = metaBreakdown?.spend ?? summary?.spend ?? null
  const clicks = metaBreakdown?.clicks ?? summary?.clicks ?? null
  const impressions = metaBreakdown?.impressions ?? summary?.impressions ?? null
  const conversions = metaBreakdown?.conversions ?? summary?.conversions ?? null
  const revenue = metaBreakdown?.revenue ?? summary?.revenue ?? null
  const roas = metaBreakdown?.roas ?? ((spend && revenue && spend > 0) ? (revenue / spend) : null)
  const ctr = (impressions && clicks && impressions > 0) ? (clicks / impressions * 100) : null

  const kpiCards = [
    {
      label: 'Meta Spend', value: spend != null ? formatINR(spend) : '—',
      sub: 'Last 30 days', icon: DollarSign, color: 'text-blue-600', bg: 'bg-blue-50',
    },
    {
      label: 'ROAS', value: roas != null ? `${roas.toFixed(2)}x` : '—',
      sub: `Revenue ${revenue != null ? formatINR(revenue) : '—'}`, icon: TrendingUp, color: 'text-green-600', bg: 'bg-green-50',
    },
    {
      label: 'Clicks', value: clicks != null ? clicks.toLocaleString('en-IN') : '—',
      sub: ctr != null ? `CTR ${ctr.toFixed(2)}%` : `${impressions != null ? impressions.toLocaleString('en-IN') : '—'} impressions`, icon: MousePointer, color: 'text-violet-600', bg: 'bg-violet-50',
    },
    {
      label: 'Conversions', value: conversions != null ? conversions.toLocaleString('en-IN') : '—',
      sub: spend && conversions && conversions > 0 ? `CPA ${formatINR(spend / conversions)}` : 'purchases / leads', icon: ShoppingCart, color: 'text-orange-600', bg: 'bg-orange-50',
    },
  ]

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-gray-900">Meta Ads</h1>
        <p className="text-sm text-gray-500">
          {totalCount} campaign{totalCount !== 1 ? 's' : ''}{hasUploadedMeta ? ' · uploaded data' : ''}
          {' · '}Last 30 days
        </p>
      </div>

      {/* KPI Summary Cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {kpiCards.map(card => (
          <div key={card.label} className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs text-gray-500">{card.label}</p>
              <div className={`flex h-7 w-7 items-center justify-center rounded-lg ${card.bg}`}>
                <card.icon className={`h-3.5 w-3.5 ${card.color}`} />
              </div>
            </div>
            <p className={`text-xl font-bold ${card.value === '—' ? 'text-gray-300' : card.color}`}>
              {card.value}
            </p>
            <p className="text-[10px] text-gray-400 mt-0.5">{card.sub}</p>
          </div>
        ))}
      </div>

      <CampaignSection
        title="Meta Campaigns"
        campaigns={metaCampaigns}
        workspaceId={workspaceId}
        emptyMessage={metaData?.error ?? 'No Meta campaigns found — connect your account or upload an Excel export from Settings'}
      />
    </div>
  )
}
