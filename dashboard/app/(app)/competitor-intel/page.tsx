import Link from 'next/link'
import { Crosshair, BarChart2, UploadCloud, Lock } from 'lucide-react'
import { fetchFromFastAPI, fetchBillingPlan } from '@/lib/api'
import YouTubeCompetitorIntel from '@/components/youtube/YouTubeCompetitorIntel'
import { Megaphone } from 'lucide-react'
import PlanGateBanner from '@/components/billing/PlanGateBanner'

interface PageProps { searchParams: { ws?: string } }

interface Competitor {
  competitor_domain: string
  campaign_name: string
  impression_share: number | null
  overlap_rate: number | null
  position_above_rate: number | null
  top_of_page_rate: number | null
  outranking_share: number | null
}

interface AuctionData {
  has_data: boolean
  competitors: Competitor[]
}

async function getAuctionData(workspaceId: string): Promise<AuctionData | null> {
  try {
    const r = await fetchFromFastAPI(`/competitor-intel?workspace_id=${workspaceId}`)
    if (!r.ok) return null
    return r.json()
  } catch {
    return null
  }
}

function Pct({ v }: { v: number | null }) {
  if (v === null || v === undefined) return <span className="text-gray-300">—</span>
  return <span>{v.toFixed(1)}%</span>
}

const PLAN_RANK: Record<string, number> = { free: 0, starter: 1, growth: 2, agency: 3 }

export default async function CompetitorIntelPage({ searchParams }: PageProps) {
  const workspaceId = searchParams.ws ?? ''
  const [auctionData, plan] = await Promise.all([
    workspaceId ? getAuctionData(workspaceId) : Promise.resolve(null),
    workspaceId ? fetchBillingPlan(workspaceId) : Promise.resolve('free'),
  ])
  const hasAuction = auctionData?.has_data === true
  const planRank = PLAN_RANK[plan] ?? 0
  const isStarterPlus = planRank >= 1  // Starter+: Meta competitor AI
  const isGrowthPlus  = planRank >= 2  // Growth+: YouTube Competitor Intel (20 credits)

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-red-600">
            <Crosshair className="h-5 w-5 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-gray-900">Competitor Intelligence</h1>
            <p className="text-sm text-gray-500">Know every move your competitors make — before it affects your ROAS</p>
          </div>
        </div>
      </div>

      {/* Meta Competitor AI — Starter+ required */}
      <PlanGateBanner
        requiredPlan="Starter"
        feature="Competitor AI Analysis"
        creditCost={5}
        wsId={workspaceId}
        currentPlan={plan as 'free' | 'starter' | 'growth' | 'agency'}
      />

      {/* YouTube Competitor Intelligence — Growth+ required (20 credits/run) */}
      {isGrowthPlus ? (
        workspaceId && <YouTubeCompetitorIntel workspaceId={workspaceId} />
      ) : (
        <div className="flex items-center gap-4 rounded-xl border border-amber-200 bg-amber-50 px-5 py-4">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-amber-100">
            <Lock className="h-5 w-5 text-amber-600" />
          </div>
          <div className="flex-1">
            <p className="text-sm font-semibold text-amber-800">YouTube Competitor Intelligence — Growth Plan Required</p>
            <p className="text-xs text-amber-700 mt-0.5">
              9-layer AI analysis of competitor channels costs 20 credits/run and requires Growth or higher.
              You&apos;re on <strong className="capitalize">{plan}</strong>.
            </p>
          </div>
          <Link
            href={`/billing?ws=${workspaceId}`}
            className="shrink-0 rounded-lg bg-amber-500 px-4 py-2 text-xs font-semibold text-white hover:bg-amber-600"
          >
            Upgrade
          </Link>
        </div>
      )}

      {/* Google Auction Insights — real data */}
      <div className="rounded-xl border border-gray-200 overflow-hidden">
        <div className="bg-gray-50 px-4 py-3 border-b border-gray-200 flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-yellow-100">
            <BarChart2 className="h-4 w-4 text-yellow-600" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-gray-900">Google Auction Insights</h3>
            <p className="text-xs text-gray-400">From uploaded Google Ads Auction Insights CSV</p>
          </div>
          {!hasAuction && (
            <Link
              href={workspaceId ? `/google-ads?ws=${workspaceId}` : '/google-ads'}
              className="ml-auto inline-flex items-center gap-1.5 rounded-lg bg-yellow-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-yellow-700"
            >
              <UploadCloud className="h-3.5 w-3.5" /> Upload CSV
            </Link>
          )}
        </div>

        {hasAuction ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 text-left text-xs font-medium text-gray-500">
                  <th className="px-4 py-3">Competitor</th>
                  <th className="px-4 py-3 text-right">Imp. Share</th>
                  <th className="px-4 py-3 text-right">Overlap Rate</th>
                  <th className="px-4 py-3 text-right">Position Above</th>
                  <th className="px-4 py-3 text-right">Top of Page</th>
                  <th className="px-4 py-3 text-right">Outranking</th>
                </tr>
              </thead>
              <tbody>
                {auctionData!.competitors.map((c, i) => {
                  const isYou = c.competitor_domain?.toLowerCase().includes('you') || i === 0
                  return (
                    <tr
                      key={i}
                      className={`border-b border-gray-100 ${isYou ? 'bg-blue-50' : 'hover:bg-gray-50'}`}
                    >
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          {isYou && (
                            <span className="rounded bg-blue-100 px-1.5 py-0.5 text-[10px] font-bold text-blue-700">YOU</span>
                          )}
                          <span className={`font-medium ${isYou ? 'text-blue-900' : 'text-gray-800'}`}>
                            {c.competitor_domain}
                          </span>
                          {c.campaign_name && (
                            <span className="text-xs text-gray-400 truncate max-w-[120px]">{c.campaign_name}</span>
                          )}
                        </div>
                      </td>
                      <td className={`px-4 py-3 text-right font-semibold ${isYou ? 'text-blue-700' : 'text-gray-700'}`}>
                        <Pct v={c.impression_share} />
                      </td>
                      <td className="px-4 py-3 text-right text-gray-600"><Pct v={c.overlap_rate} /></td>
                      <td className="px-4 py-3 text-right text-gray-600"><Pct v={c.position_above_rate} /></td>
                      <td className="px-4 py-3 text-right text-gray-600"><Pct v={c.top_of_page_rate} /></td>
                      <td className="px-4 py-3 text-right text-gray-600"><Pct v={c.outranking_share} /></td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="p-8 text-center">
            <BarChart2 className="h-8 w-8 text-yellow-500 mx-auto mb-3" />
            <p className="text-sm font-semibold text-gray-900">No auction insights data yet</p>
            <p className="text-xs text-gray-500 mt-1 max-w-xs mx-auto">
              Upload a Google Ads Auction Insights CSV from the Google Ads page to see competitor overlap and position data.
            </p>
          </div>
        )}
      </div>

      {/* Meta Ad Library Monitor — coming soon */}
      <div className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-5 flex items-center gap-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-100">
          <Megaphone className="h-4 w-4 text-blue-500" />
        </div>
        <div>
          <p className="text-sm font-semibold text-gray-700">Meta Ad Library Monitor</p>
          <p className="text-xs text-gray-400 mt-0.5">Competitor ads on Facebook &amp; Instagram — coming soon</p>
        </div>
        <span className="ml-auto rounded-full bg-blue-100 px-2.5 py-0.5 text-[10px] font-semibold text-blue-600 uppercase tracking-wide">Soon</span>
      </div>
    </div>
  )
}
