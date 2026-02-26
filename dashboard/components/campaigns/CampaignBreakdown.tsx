'use client'

import { useEffect, useState } from 'react'
import { Loader2, AlertTriangle } from 'lucide-react'

interface FrequencyItem {
  adset_name?: string
  adset_id?: string
  frequency?: number
  [key: string]: unknown
}

interface PlacementItem {
  placement?: string
  publisher_platform?: string
  spend?: number
  impressions?: number
  clicks?: number
  actions?: number
  purchase_roas?: number
  [key: string]: unknown
}

interface AgeGenderItem {
  age?: string
  gender?: string
  impressions?: number
  clicks?: number
  conversions?: number
  ctr?: number
  [key: string]: unknown
}

interface BreakdownData {
  has_data: boolean
  analysis_date: string | null
  frequency: FrequencyItem[]
  placement: PlacementItem[]
  age_gender: AgeGenderItem[]
}

interface Props {
  campaignId: string
  workspaceId: string
}

function FreqBar({ value, label }: { value: number; label: string }) {
  const pct = Math.min(value / 8 * 100, 100)
  const color = value < 2.5 ? 'bg-green-400' : value < 4 ? 'bg-amber-400' : 'bg-red-500'
  return (
    <div className="flex items-center gap-3 text-xs">
      <span className="w-32 truncate text-gray-600">{label}</span>
      <div className="flex-1 h-3 rounded-full bg-gray-100 overflow-hidden">
        <div className={`h-full rounded-full ${color} transition-all`} style={{ width: `${pct}%` }} />
      </div>
      <span className={`w-10 text-right font-semibold ${value >= 4 ? 'text-red-600' : value >= 2.5 ? 'text-amber-600' : 'text-green-600'}`}>
        {typeof value === 'number' ? value.toFixed(1) : value}
      </span>
    </div>
  )
}

const PLACEMENT_ICONS: Record<string, string> = {
  feed: '📰',
  reels: '🎬',
  stories: '⭕',
  audience_network: '🌐',
  marketplace: '🛒',
  video_feeds: '▶️',
  search: '🔍',
}

export default function CampaignBreakdown({ campaignId, workspaceId }: Props) {
  const [data, setData] = useState<BreakdownData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    fetch(`/api/campaigns/breakdown/${campaignId}?workspace_id=${workspaceId}`)
      .then(r => r.json())
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [campaignId, workspaceId])

  if (loading) {
    return (
      <div className="flex items-center justify-center gap-2 py-10 text-sm text-gray-400">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading breakdown…
      </div>
    )
  }

  if (!data?.has_data) {
    return (
      <div className="py-10 text-center text-sm text-gray-400">
        <p className="font-medium mb-1">No breakdown data yet</p>
        <p className="text-xs">Run the daily analysis (fb_analyst agent) to see frequency, placement, and age/gender breakdowns.</p>
      </div>
    )
  }

  const highFreq = data.frequency.filter(f => {
    const v = typeof f.frequency === 'number' ? f.frequency : parseFloat(String(f.frequency ?? 0))
    return v > 4
  })

  return (
    <div className="space-y-6 p-5">
      {data.analysis_date && (
        <p className="text-xs text-gray-400">Data from: {data.analysis_date}</p>
      )}

      {/* Frequency */}
      {data.frequency.length > 0 && (
        <div>
          <h3 className="mb-1 text-sm font-semibold text-gray-700">
            Ad Frequency by Ad Set
          </h3>
          <p className="mb-3 text-[10px] text-gray-400">
            Green &lt;2.5 · Amber 2.5–4 · Red &gt;4 (fatigue risk)
          </p>
          {highFreq.length > 0 && (
            <div className="mb-3 flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
              Ad fatigue detected — refresh creatives for {highFreq.length} ad set{highFreq.length > 1 ? 's' : ''}
            </div>
          )}
          <div className="space-y-2">
            {data.frequency.map((f, i) => {
              const val = typeof f.frequency === 'number' ? f.frequency : parseFloat(String(f.frequency ?? 0))
              const label = f.adset_name ?? f.adset_id ?? `Ad Set ${i + 1}`
              return <FreqBar key={i} value={val} label={label} />
            })}
          </div>
        </div>
      )}

      {/* Placement */}
      {data.placement.length > 0 && (
        <div>
          <h3 className="mb-3 text-sm font-semibold text-gray-700">
            Placement Performance
          </h3>
          <div className="grid grid-cols-2 gap-2">
            {data.placement.map((p, i) => {
              const name = p.placement ?? p.publisher_platform ?? `Placement ${i + 1}`
              const key = name.toLowerCase().replace(/\s+/g, '_')
              const icon = PLACEMENT_ICONS[key] ?? '📍'
              const spend = typeof p.spend === 'number' ? p.spend : parseFloat(String(p.spend ?? 0))
              const roas = typeof p.purchase_roas === 'number' ? p.purchase_roas : parseFloat(String(p.purchase_roas ?? 0))

              return (
                <div key={i} className="rounded-xl border border-gray-100 bg-gray-50 p-3">
                  <div className="flex items-center gap-1.5 mb-1.5">
                    <span className="text-base">{icon}</span>
                    <span className="text-xs font-semibold text-gray-700 capitalize">
                      {name.replace(/_/g, ' ')}
                    </span>
                  </div>
                  <p className="text-xs text-gray-500">
                    Spend: <span className="font-medium text-gray-800">
                      ₹{spend.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                    </span>
                  </p>
                  {roas > 0 && (
                    <p className="text-xs text-gray-500">
                      ROAS: <span className={`font-medium ${roas >= 2.5 ? 'text-green-700' : 'text-red-600'}`}>
                        {roas.toFixed(2)}x
                      </span>
                    </p>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Age / Gender grid */}
      {data.age_gender.length > 0 && (
        <div>
          <h3 className="mb-3 text-sm font-semibold text-gray-700">
            Age / Gender Breakdown
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-200 text-left text-gray-500">
                  <th className="pb-2 pr-3 font-medium">Age</th>
                  <th className="pb-2 pr-3 font-medium">Gender</th>
                  <th className="pb-2 pr-3 font-medium text-right">Impr.</th>
                  <th className="pb-2 pr-3 font-medium text-right">Clicks</th>
                  <th className="pb-2 font-medium text-right">Conv.</th>
                </tr>
              </thead>
              <tbody>
                {data.age_gender.map((row, i) => {
                  const impressions = typeof row.impressions === 'number' ? row.impressions : parseInt(String(row.impressions ?? 0))
                  const clicks = typeof row.clicks === 'number' ? row.clicks : parseInt(String(row.clicks ?? 0))
                  const conversions = typeof row.conversions === 'number' ? row.conversions : parseInt(String(row.conversions ?? 0))
                  const hasConv = conversions > 0
                  return (
                    <tr
                      key={i}
                      className={`border-b border-gray-100 ${hasConv ? 'bg-green-50' : ''}`}
                    >
                      <td className="py-2 pr-3 font-medium text-gray-800">{row.age ?? '—'}</td>
                      <td className="py-2 pr-3 text-gray-600 capitalize">{row.gender ?? '—'}</td>
                      <td className="py-2 pr-3 text-right text-gray-700">{impressions.toLocaleString()}</td>
                      <td className="py-2 pr-3 text-right text-gray-700">{clicks.toLocaleString()}</td>
                      <td className={`py-2 text-right font-medium ${hasConv ? 'text-green-700' : 'text-gray-400'}`}>
                        {conversions || '—'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
