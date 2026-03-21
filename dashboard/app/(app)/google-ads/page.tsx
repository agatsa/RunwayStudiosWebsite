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
import { BarChart2, Clock, UploadCloud } from 'lucide-react'

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
          <p className="text-sm text-gray-500">Connect Google or upload CSV reports to get started</p>
        </div>

        {/* Two paths to get data */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {/* Path 1: Connect Google OAuth */}
          <div className="rounded-xl border border-green-100 bg-green-50 p-5">
            <div className="flex items-center gap-2.5 mb-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-gray-200 bg-white shrink-0">
                <svg viewBox="0 0 24 24" className="h-5 w-5">
                  <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                  <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                  <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
                  <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
                </svg>
              </div>
              <div>
                <p className="text-sm font-bold text-gray-900">Connect Google</p>
                <p className="text-xs text-green-700">Recommended · One-click OAuth</p>
              </div>
            </div>
            <p className="text-xs text-gray-600 mb-3 leading-relaxed">
              One click connects Google Ads + YouTube Analytics + GA4. Data syncs automatically every day.
            </p>
            <a
              href={workspaceId ? `/settings?ws=${workspaceId}` : '/settings'}
              className="inline-flex items-center gap-1.5 rounded-lg bg-green-600 px-3 py-2 text-xs font-semibold text-white hover:bg-green-700 transition-colors"
            >
              Connect in Settings →
            </a>
          </div>

          {/* Path 2: Upload CSV */}
          <div className="rounded-xl border border-amber-100 bg-amber-50 p-5">
            <div className="flex items-center gap-2.5 mb-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-amber-100 shrink-0">
                <UploadCloud className="h-5 w-5 text-amber-600" />
              </div>
              <div>
                <p className="text-sm font-bold text-gray-900">Upload CSV Reports</p>
                <p className="text-xs text-amber-700">Works now · No account needed</p>
              </div>
            </div>
            <p className="text-xs text-gray-600 mb-3 leading-relaxed">
              Export reports from Google Ads Manager and upload below. Campaign, Keywords, Search Terms, and Auction Insights all supported.
            </p>
            <p className="text-xs text-amber-700 font-medium">↓ Use the Report Center below</p>
          </div>
        </div>

        {/* Report Manager always shown — primary upload UX */}
        <GoogleAdsReportManager workspaceId={workspaceId} />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Coming soon banner */}
      <div className="flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
        <Clock className="h-4 w-4 text-amber-600 mt-0.5 shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-amber-800">Live Google Ads sync — Coming Soon</p>
          <p className="text-xs text-amber-700 mt-0.5">
            Live campaign sync is coming soon. <strong>Manual CSV upload below works now</strong> — export reports from Google Ads Manager and upload for full analysis.
          </p>
        </div>
        <span className="rounded-full bg-amber-100 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide text-amber-700 shrink-0">Coming Soon</span>
      </div>

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
