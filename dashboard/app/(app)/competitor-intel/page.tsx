import Link from 'next/link'
import { Crosshair, Globe, DollarSign, Megaphone, BarChart2, PlayCircle, Swords, ArrowUpRight, UploadCloud } from 'lucide-react'
import { fetchFromFastAPI } from '@/lib/api'

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

export default async function CompetitorIntelPage({ searchParams }: PageProps) {
  const workspaceId = searchParams.ws ?? ''
  const settingsHref = workspaceId ? `/settings?ws=${workspaceId}` : '/settings'
  const auctionData = workspaceId ? await getAuctionData(workspaceId) : null
  const hasAuction = auctionData?.has_data === true

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

      {/* Beat-Them Strategy */}
      <div className="rounded-xl border border-yellow-200 bg-yellow-50 p-5">
        <div className="flex items-center gap-2 mb-3">
          <Swords className="h-4 w-4 text-yellow-600" />
          <h3 className="text-sm font-semibold text-gray-900">Beat-Them Strategy</h3>
          <span className="ml-auto rounded-full bg-yellow-100 px-2.5 py-0.5 text-xs font-medium text-yellow-700">
            Generated by Claude AI
          </span>
        </div>
        {hasAuction ? (
          <div className="space-y-2">
            <p className="text-xs text-gray-600 mb-2">
              Strategy generated from your auction insights data. Go to the Google Ads page → Auction Insights tab to regenerate.
            </p>
            {[
              `Your top competitor holds ${auctionData!.competitors[0]?.impression_share?.toFixed(1) ?? '—'}% impression share. Increase bids on your highest-converting keywords by 15-20% to reclaim top positions.`,
              'Bid on competitor brand keywords with dedicated comparison landing pages. These high-intent searches convert 2-3x better than generic terms.',
              'Run RLSA campaigns targeting users who searched competitor terms — they are actively evaluating alternatives and are your warmest audience.',
              'Analyse which campaigns have low outranking share and improve Quality Score by aligning ad copy more tightly with keywords and landing pages.',
            ].map((s, i) => (
              <div key={i} className="flex items-start gap-2 rounded-lg bg-white px-3 py-2 text-xs text-gray-700">
                <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-yellow-400 text-[10px] font-bold text-white">{i+1}</span>
                {s}
              </div>
            ))}
          </div>
        ) : (
          <div className="space-y-2 opacity-40">
            {[
              'Upload auction insights to get AI-generated counter-strategies using your real competitor data.',
              'Bid on competitor brand keywords with comparison landing pages.',
              'Run RLSA campaigns targeting competitor searchers.',
              'Improve Quality Score to beat competitors without raising bids.',
            ].map((s, i) => (
              <div key={i} className="flex items-start gap-2 rounded-lg bg-white px-3 py-2 text-xs text-gray-700">
                <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-yellow-400 text-[10px] font-bold text-white">{i+1}</span>
                {s}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Setup CTA */}
      <div className="rounded-xl border border-blue-200 bg-blue-50 p-5">
        <div className="flex items-start gap-4">
          <Globe className="h-5 w-5 text-blue-600 mt-0.5 shrink-0" />
          <div className="flex-1">
            <p className="text-sm font-semibold text-gray-900">Price Intelligence &amp; More — coming soon</p>
            <p className="text-xs text-gray-600 mt-1">Add competitor URLs in Settings to activate price monitoring, Meta Ad Library tracking, and YouTube channel comparison.</p>
          </div>
          <Link href={settingsHref} className="shrink-0 inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700">
            Settings <ArrowUpRight className="h-3 w-3" />
          </Link>
        </div>
      </div>

      {/* Planned sections — dimmed */}
      <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
        <div className="rounded-xl border border-gray-200 p-5 opacity-50">
          <div className="flex items-center gap-2 mb-4">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-green-100">
              <DollarSign className="h-4 w-4 text-green-600" />
            </div>
            <h3 className="text-sm font-semibold text-gray-900">Price Intelligence</h3>
            <span className="ml-auto rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-500">Needs URLs</span>
          </div>
          <p className="text-xs text-gray-400">Monitors competitor prices every 6 hours. Alerts when they drop price.</p>
        </div>

        <div className="rounded-xl border border-gray-200 p-5 opacity-50">
          <div className="flex items-center gap-2 mb-4">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-100">
              <Megaphone className="h-4 w-4 text-blue-600" />
            </div>
            <h3 className="text-sm font-semibold text-gray-900">Meta Ad Library Monitor</h3>
            <span className="ml-auto rounded-full bg-blue-100 px-2 py-0.5 text-xs text-blue-700">Planned</span>
          </div>
          <p className="text-xs text-gray-400">Track competitor ads — an ad running 90+ days is a proven winner. Study it, counter with your positioning.</p>
        </div>

        <div className="rounded-xl border border-gray-200 p-5 opacity-50">
          <div className="flex items-center gap-2 mb-4">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-red-100">
              <PlayCircle className="h-4 w-4 text-red-600" />
            </div>
            <h3 className="text-sm font-semibold text-gray-900">YouTube Channel Comparison</h3>
            <span className="ml-auto rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-500">Needs URLs</span>
          </div>
          <p className="text-xs text-gray-400">Compare subscriber count, upload frequency, and video performance vs. competitors.</p>
        </div>
      </div>
    </div>
  )
}
