'use client'

import { useEffect, useState } from 'react'
import { Swords, Loader2 } from 'lucide-react'

interface AuctionRow {
  competitor_domain: string
  campaign_name: string
  impression_share: number | null
  overlap_rate: number | null
  position_above_rate: number | null
  top_of_page_rate: number | null
  abs_top_impression_pct: number | null
  outranking_share: number | null
}

interface AuctionData {
  has_data: boolean
  last_upload_date: string | null
  competitors: AuctionRow[]
}

function pct(v: number | null) {
  if (v === null || v === undefined) return '—'
  return `${v.toFixed(1)}%`
}

function overlapColor(v: number | null) {
  if (v === null) return ''
  if (v >= 60) return 'text-red-600 font-semibold'
  if (v >= 30) return 'text-yellow-600'
  return 'text-gray-600'
}

export default function GoogleAdsAuction({ workspaceId }: { workspaceId: string }) {
  const [data, setData] = useState<AuctionData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch(`/api/google-ads/auction?workspace_id=${workspaceId}`)
      .then(r => r.json())
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [workspaceId])

  return (
    <div className="rounded-xl border border-gray-200 overflow-hidden">
      <div className="bg-gray-50 px-4 py-3 border-b border-gray-200 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-gray-700 flex items-center gap-1.5">
            <Swords className="h-3.5 w-3.5 text-purple-600" />
            Auction Insights
          </h2>
          <p className="text-xs text-gray-600">Impression share and overlap vs competitors</p>
        </div>
        {data?.last_upload_date && (
          <span className="text-[10px] text-gray-400">
            {new Date(data.last_upload_date).toLocaleDateString('en-IN', { month: 'short', year: 'numeric' })}
          </span>
        )}
      </div>

      {loading ? (
        <div className="flex items-center justify-center p-8">
          <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
        </div>
      ) : !data?.has_data ? (
        <div className="p-4 text-center text-xs text-gray-400">
          No auction insights yet — upload an Auction Insights report
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50/50 text-left text-[10px] text-gray-500 uppercase tracking-wide">
                <th className="px-4 py-2 font-medium">Competitor</th>
                <th className="px-3 py-2 font-medium text-right">Impr. Share</th>
                <th className="px-3 py-2 font-medium text-right">Overlap</th>
                <th className="px-3 py-2 font-medium text-right">Pos. Above</th>
                <th className="px-3 py-2 font-medium text-right">Top of Page</th>
                <th className="px-3 py-2 font-medium text-right">Abs. Top</th>
                <th className="px-3 py-2 font-medium text-right">Outranking</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {data.competitors.map((c, i) => (
                <tr key={i} className="hover:bg-gray-50/50">
                  <td className="px-4 py-2.5">
                    <p className="font-medium text-gray-800">{c.competitor_domain}</p>
                    {c.campaign_name && (
                      <p className="text-[10px] text-gray-400 truncate max-w-[160px]">{c.campaign_name}</p>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-right text-gray-600">{pct(c.impression_share)}</td>
                  <td className={`px-3 py-2.5 text-right ${overlapColor(c.overlap_rate)}`}>{pct(c.overlap_rate)}</td>
                  <td className="px-3 py-2.5 text-right text-gray-600">{pct(c.position_above_rate)}</td>
                  <td className="px-3 py-2.5 text-right text-gray-600">{pct(c.top_of_page_rate)}</td>
                  <td className="px-3 py-2.5 text-right text-gray-600">{pct(c.abs_top_impression_pct)}</td>
                  <td className="px-3 py-2.5 text-right text-gray-600">{pct(c.outranking_share)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
