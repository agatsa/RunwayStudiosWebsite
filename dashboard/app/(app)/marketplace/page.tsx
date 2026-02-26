import { fetchFromFastAPI } from '@/lib/api'
import AmazonCampaignTable, { AmazonCampaign } from '@/components/marketplace/AmazonCampaignTable'
import AmazonUploadManager from '@/components/marketplace/AmazonUploadManager'
import CrossPlatformROAS from '@/components/marketplace/CrossPlatformROAS'
import { ShoppingBag, TrendingUp, TrendingDown, Minus } from 'lucide-react'

interface PageProps {
  searchParams: { ws?: string }
}

interface MarketplaceData {
  campaigns: AmazonCampaign[]
  summary: {
    total_spend: number
    total_sales: number
    total_orders: number
    avg_roas: number
    avg_acos: number
  }
}

async function fetchMarketplaceData(workspaceId: string): Promise<MarketplaceData | null> {
  try {
    const r = await fetchFromFastAPI(`/marketplace/campaigns?workspace_id=${workspaceId}&days=365`)
    if (!r.ok) return null
    return r.json()
  } catch {
    return null
  }
}

function fmtINR(n: number) {
  if (n >= 1_00_00_000) return `₹${(n / 1_00_00_000).toFixed(2)}Cr`
  if (n >= 1_00_000)    return `₹${(n / 1_00_000).toFixed(2)}L`
  if (n >= 1_000)       return `₹${(n / 1_000).toFixed(1)}K`
  return `₹${n.toFixed(0)}`
}

function acosColor(acos: number) {
  if (acos === 0)  return 'text-gray-400'
  if (acos <= 20)  return 'text-green-600'
  if (acos <= 35)  return 'text-yellow-600'
  return 'text-red-600'
}

function roasIcon(roas: number) {
  if (roas >= 4)   return <TrendingUp className="h-3.5 w-3.5 text-green-500" />
  if (roas >= 2)   return <Minus className="h-3.5 w-3.5 text-yellow-500" />
  return <TrendingDown className="h-3.5 w-3.5 text-red-500" />
}

export default async function MarketplacePage({ searchParams }: PageProps) {
  const workspaceId = searchParams.ws ?? ''

  if (!workspaceId) {
    return (
      <div className="flex h-64 items-center justify-center rounded-xl border-2 border-dashed border-gray-200">
        <p className="text-gray-500">Select a workspace to view Marketplace intelligence</p>
      </div>
    )
  }

  const data = await fetchMarketplaceData(workspaceId)
  const hasData = !!(data && data.campaigns.length > 0)
  const s = data?.summary

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-orange-500">
          <ShoppingBag className="h-5 w-5 text-white" />
        </div>
        <div>
          <h1 className="text-xl font-bold text-gray-900">Amazon Marketplace</h1>
          <p className="text-sm text-gray-500">
            {hasData
              ? `${data!.campaigns.length} campaign${data!.campaigns.length !== 1 ? 's' : ''} · Upload new reports below`
              : 'Upload Sponsored Products, Brands, and Display reports'}
          </p>
        </div>
      </div>

      {/* Upload Manager — always shown */}
      <AmazonUploadManager workspaceId={workspaceId} />

      {/* KPI Summary Cards */}
      {hasData && s && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          <div className="rounded-xl border border-gray-100 bg-white p-4">
            <p className="text-[11px] font-medium text-gray-500">Total Spend</p>
            <p className="mt-1 text-xl font-bold text-gray-900">{fmtINR(s.total_spend)}</p>
          </div>
          <div className="rounded-xl border border-gray-100 bg-white p-4">
            <p className="text-[11px] font-medium text-gray-500">Total Sales</p>
            <p className="mt-1 text-xl font-bold text-green-700">{fmtINR(s.total_sales)}</p>
          </div>
          <div className="rounded-xl border border-gray-100 bg-white p-4">
            <p className="text-[11px] font-medium text-gray-500">Avg ROAS</p>
            <div className="mt-1 flex items-center gap-1.5">
              {roasIcon(s.avg_roas)}
              <p className="text-xl font-bold text-gray-900">
                {s.avg_roas > 0 ? `${s.avg_roas.toFixed(2)}x` : '—'}
              </p>
            </div>
          </div>
          <div className="rounded-xl border border-gray-100 bg-white p-4">
            <p className="text-[11px] font-medium text-gray-500">Avg ACoS</p>
            <p className={`mt-1 text-xl font-bold ${acosColor(s.avg_acos)}`}>
              {s.avg_acos > 0 ? `${s.avg_acos.toFixed(1)}%` : '—'}
            </p>
          </div>
          <div className="rounded-xl border border-gray-100 bg-white p-4">
            <p className="text-[11px] font-medium text-gray-500">Total Orders</p>
            <p className="mt-1 text-xl font-bold text-gray-900">
              {s.total_orders > 0 ? s.total_orders.toLocaleString('en-IN') : '—'}
            </p>
          </div>
        </div>
      )}

      {/* Campaign Table */}
      {hasData ? (
        <div className="rounded-xl border border-gray-100 bg-white p-5">
          <h2 className="text-sm font-semibold text-gray-900 mb-4">Campaign Performance</h2>
          <AmazonCampaignTable campaigns={data!.campaigns} />
        </div>
      ) : (
        <div className="flex flex-col items-center gap-5 rounded-xl border-2 border-dashed border-orange-100 bg-orange-50/30 p-12 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-orange-500">
            <ShoppingBag className="h-7 w-7 text-white" />
          </div>
          <div className="max-w-md">
            <p className="text-base font-semibold text-gray-900">No Amazon Ads data yet</p>
            <p className="mt-2 text-sm text-gray-500">
              Use the Report Center above to upload your Amazon Advertising exports.
              Download Campaign reports from <strong>Amazon Ads → Reports</strong> for each ad type.
            </p>
          </div>
        </div>
      )}

      {/* Cross-Platform ROAS Comparison */}
      <CrossPlatformROAS workspaceId={workspaceId} />
    </div>
  )
}
