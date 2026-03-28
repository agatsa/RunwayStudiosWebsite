'use client'

import { useState, useEffect, Suspense } from 'react'
import { useSearchParams } from 'next/navigation'
import { Crosshair, Search, PlayCircle, BarChart2, UploadCloud } from 'lucide-react'
import Link from 'next/link'
import BrandIntelPanel from '@/components/competitor-intel/BrandIntelPanel'
import YouTubeCompetitorIntel from '@/components/youtube/YouTubeCompetitorIntel'

type Tab = 'brand' | 'youtube' | 'auction'

export default function CompetitorIntelPage() {
  return (
    <Suspense fallback={<div className="flex h-64 items-center justify-center"><p className="text-sm text-gray-400">Loading...</p></div>}>
      <CompetitorIntelContent />
    </Suspense>
  )
}

function CompetitorIntelContent() {
  const searchParams  = useSearchParams()
  const workspaceId   = searchParams.get('ws') ?? ''
  const defaultTab    = (searchParams.get('tab') as Tab) ?? 'brand'
  const [activeTab, setActiveTab] = useState<Tab>(defaultTab)

  // Auction data — loaded client-side
  const [auctionData, setAuctionData] = useState<{
    has_data: boolean
    competitors: Array<{
      competitor_domain: string
      campaign_name: string
      impression_share: number | null
      overlap_rate: number | null
      position_above_rate: number | null
      top_of_page_rate: number | null
      outranking_share: number | null
    }>
  } | null>(null)

  useEffect(() => {
    if (!workspaceId) return
    fetch(`/api/competitor-intel?workspace_id=${workspaceId}`)
      .then(r => r.json())
      .then(d => setAuctionData(d))
      .catch(() => {})
  }, [workspaceId])

  function Pct({ v }: { v: number | null }) {
    if (v === null || v === undefined) return <span className="text-gray-300">—</span>
    return <span>{v.toFixed(1)}%</span>
  }

  const TABS = [
    { id: 'brand'   as const, label: 'Brand & Ad Intel',    icon: Search },
    { id: 'youtube' as const, label: 'YouTube Intel',        icon: PlayCircle },
    { id: 'auction' as const, label: 'Google Auction',       icon: BarChart2 },
  ]

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-red-600">
          <Crosshair className="h-5 w-5 text-white" />
        </div>
        <div>
          <h1 className="text-xl font-bold text-gray-900">Competitor Intelligence</h1>
          <p className="text-sm text-gray-500">Know every move your competitors make — before it affects your ROAS</p>
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 rounded-2xl border border-gray-200 bg-gray-50 p-1">
        {TABS.map(tab => {
          const Icon = tab.icon
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex flex-1 items-center justify-center gap-2 rounded-xl py-2.5 text-sm font-medium transition-all ${
                activeTab === tab.id
                  ? 'bg-white text-gray-900 shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              <Icon className="h-4 w-4" />
              {tab.label}
            </button>
          )
        })}
      </div>

      {/* Tab panels */}
      {activeTab === 'brand' && workspaceId && (
        <BrandIntelPanel workspaceId={workspaceId} />
      )}

      {activeTab === 'youtube' && workspaceId && (
        <YouTubeCompetitorIntel workspaceId={workspaceId} />
      )}

      {activeTab === 'auction' && (
        <div className="rounded-xl border border-gray-200 overflow-hidden">
          <div className="bg-gray-50 px-4 py-3 border-b border-gray-200 flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-yellow-100">
              <BarChart2 className="h-4 w-4 text-yellow-600" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-gray-900">Google Auction Insights</h3>
              <p className="text-xs text-gray-400">From uploaded Google Ads Auction Insights CSV</p>
            </div>
            {!auctionData?.has_data && (
              <Link
                href={workspaceId ? `/google-ads?ws=${workspaceId}` : '/google-ads'}
                className="ml-auto inline-flex items-center gap-1.5 rounded-lg bg-yellow-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-yellow-700"
              >
                <UploadCloud className="h-3.5 w-3.5" /> Upload CSV
              </Link>
            )}
          </div>

          {auctionData?.has_data ? (
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
                  {auctionData.competitors.map((c, i) => {
                    const isYou = c.competitor_domain?.toLowerCase().includes('you') || i === 0
                    return (
                      <tr key={i} className={`border-b border-gray-100 ${isYou ? 'bg-blue-50' : 'hover:bg-gray-50'}`}>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            {isYou && <span className="rounded bg-blue-100 px-1.5 py-0.5 text-[10px] font-bold text-blue-700">YOU</span>}
                            <span className={`font-medium ${isYou ? 'text-blue-900' : 'text-gray-800'}`}>{c.competitor_domain}</span>
                            {c.campaign_name && <span className="text-xs text-gray-400 truncate max-w-[120px]">{c.campaign_name}</span>}
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
                Upload a Google Ads Auction Insights CSV from the Google Ads page.
              </p>
            </div>
          )}
        </div>
      )}

      {!workspaceId && (
        <div className="rounded-xl border border-gray-200 bg-gray-50 p-8 text-center text-gray-400">
          <p className="text-sm">Select a workspace to view competitor intelligence.</p>
        </div>
      )}
    </div>
  )
}
