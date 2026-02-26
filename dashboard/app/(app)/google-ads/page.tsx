import { fetchFromFastAPI } from '@/lib/api'
import GoogleAdsOverview from '@/components/google-ads/GoogleAdsOverview'
import GoogleAdsActionPlan from '@/components/google-ads/GoogleAdsActionPlan'
import GoogleAdsCampaignTable from '@/components/google-ads/GoogleAdsCampaignTable'
import GoogleAdsKeywords from '@/components/google-ads/GoogleAdsKeywords'
import GoogleAdsReportManager from '@/components/google-ads/GoogleAdsReportManager'
import GoogleAdsGeo from '@/components/google-ads/GoogleAdsGeo'
import GoogleAdsDevices from '@/components/google-ads/GoogleAdsDevices'
import GoogleAdsTimeHeatmap from '@/components/google-ads/GoogleAdsTimeHeatmap'
import GoogleAdsAssets from '@/components/google-ads/GoogleAdsAssets'
import GoogleAdsAuction from '@/components/google-ads/GoogleAdsAuction'
import { BarChart2 } from 'lucide-react'

interface PageProps {
  searchParams: { ws?: string }
}

export interface GoogleIntelligenceData {
  has_data: boolean
  last_upload_date: string | null
  total_spend: number
  total_revenue: number
  total_conversions: number
  total_clicks: number
  avg_roas: number
  wasted_spend_total: number
  campaigns: GoogleAdsCampaign[]
  keywords: GoogleAdsKeyword[]
  search_terms: GoogleAdsSearchTerm[]
  action_plan: string[]
}

export interface GoogleAdsCampaign {
  id: string
  name: string
  spend: number
  roas: number
  conversions: number
  clicks: number
  ctr: number
  cpc: number
  health: 'good' | 'warning' | 'critical'
  health_reason: string
}

export interface GoogleAdsKeyword {
  keyword: string
  campaign_name: string
  ad_group_name: string
  match_type: string
  quality_score: number | null
  spend: number
  clicks: number
  conversions: number
  cpc: number
  ctr: number
  is_wasted: boolean
}

export interface GoogleAdsSearchTerm {
  search_term: string
  keyword: string
  match_type: string
  spend: number
  conversions: number
  is_negative_candidate: boolean
}

async function fetchIntelligence(workspaceId: string): Promise<GoogleIntelligenceData | null> {
  try {
    const r = await fetchFromFastAPI(`/upload/google-intelligence?workspace_id=${workspaceId}`)
    if (!r.ok) return null
    return r.json()
  } catch {
    return null
  }
}

function formatMonth(isoDate: string | null): string {
  if (!isoDate) return ''
  return new Date(isoDate).toLocaleDateString('en-IN', { month: 'short', year: 'numeric' })
}

export default async function GoogleAdsPage({ searchParams }: PageProps) {
  const workspaceId = searchParams.ws ?? ''

  if (!workspaceId) {
    return (
      <div className="flex h-64 items-center justify-center rounded-xl border-2 border-dashed border-gray-200">
        <p className="text-gray-500">Select a workspace to view Google Ads intelligence</p>
      </div>
    )
  }

  const data = await fetchIntelligence(workspaceId)

  // Empty state — still show Report Manager so user can upload
  if (!data || !data.has_data) {
    return (
      <div className="space-y-4">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Google Ads Intelligence</h1>
          <p className="text-sm text-gray-500">AI-powered analysis of your Google Ads performance</p>
        </div>

        {/* Report Manager always shown — primary upload UX */}
        <GoogleAdsReportManager workspaceId={workspaceId} />

        <div className="flex flex-col items-center gap-5 rounded-xl border-2 border-dashed border-blue-100 bg-blue-50/40 p-10 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-blue-600">
            <BarChart2 className="h-7 w-7 text-white" />
          </div>
          <div className="max-w-md">
            <p className="text-base font-semibold text-gray-900">No data yet</p>
            <p className="mt-2 text-sm text-gray-500">
              Use the Report Center above to upload your Google Ads exports.
              Start with the Campaign Report, then add Keywords and Search Terms for a full picture.
            </p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-blue-600">
          <BarChart2 className="h-5 w-5 text-white" />
        </div>
        <div>
          <h1 className="text-xl font-bold text-gray-900">Google Ads Intelligence</h1>
          <p className="text-sm text-gray-500">
            {data.last_upload_date ? `Last data: ${formatMonth(data.last_upload_date)}` : 'Historical data'}
            {' · '}
            {data.campaigns.length} campaign{data.campaigns.length !== 1 ? 's' : ''}
            {data.keywords.length > 0 && `, ${data.keywords.length} keywords`}
          </p>
        </div>
      </div>

      {/* ── Report Center (top of page, primary upload UX) ── */}
      <GoogleAdsReportManager workspaceId={workspaceId} />

      {/* KPI Overview */}
      <GoogleAdsOverview data={data} />

      {/* AI Action Plan */}
      <GoogleAdsActionPlan workspaceId={workspaceId} />

      {/* Campaign Table */}
      <GoogleAdsCampaignTable campaigns={data.campaigns} workspaceId={workspaceId} />

      {/* Keywords + Search Terms */}
      {(data.keywords.length > 0 || data.search_terms.length > 0) && (
        <GoogleAdsKeywords
          keywords={data.keywords}
          searchTerms={data.search_terms}
          wastedTotal={data.wasted_spend_total}
        />
      )}

      {/* ── Auction Insights (real data via client component) ── */}
      <GoogleAdsAuction workspaceId={workspaceId} />

      {/* ── Geographic + Device + Time of Day ── */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <GoogleAdsGeo workspaceId={workspaceId} />
        <GoogleAdsDevices workspaceId={workspaceId} />
        <GoogleAdsTimeHeatmap workspaceId={workspaceId} />
      </div>

      {/* ── Ad Asset Performance ── */}
      <GoogleAdsAssets workspaceId={workspaceId} />
    </div>
  )
}
