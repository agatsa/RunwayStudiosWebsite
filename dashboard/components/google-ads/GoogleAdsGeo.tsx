'use client'

import { useEffect, useState } from 'react'
import { MapPin, Loader2 } from 'lucide-react'

interface GeoRow {
  region: string
  campaign_name: string
  spend: number
  impressions: number
  clicks: number
  conversions: number
  revenue: number
  roas: number
  cpa: number | null
}

interface GeoData {
  has_data: boolean
  last_upload_date: string | null
  geos: GeoRow[]
}

function roasBadge(roas: number) {
  if (roas >= 4) return 'bg-green-100 text-green-700'
  if (roas >= 2.5) return 'bg-yellow-100 text-yellow-700'
  return 'bg-red-100 text-red-700'
}

function fmt(n: number) {
  return n.toLocaleString('en-IN', { maximumFractionDigits: 0 })
}

export default function GoogleAdsGeo({ workspaceId }: { workspaceId: string }) {
  const [data, setData] = useState<GeoData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch(`/api/google-ads/geo?workspace_id=${workspaceId}`)
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
            <MapPin className="h-3.5 w-3.5 text-green-600" />
            Geographic Breakdown
          </h2>
          <p className="text-xs text-gray-600">CPA and ROAS by region</p>
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
          No geographic data yet — upload a Geo report
        </div>
      ) : (
        <div className="divide-y divide-gray-50">
          {data.geos.slice(0, 12).map((geo, i) => (
            <div key={i} className="flex items-center justify-between px-4 py-2.5">
              <div className="min-w-0">
                <p className="text-xs font-medium text-gray-800 truncate">{geo.region}</p>
                {geo.campaign_name && (
                  <p className="text-[10px] text-gray-400 truncate">{geo.campaign_name}</p>
                )}
              </div>
              <div className="flex items-center gap-3 shrink-0 ml-2">
                <div className="text-right">
                  <p className="text-[10px] text-gray-400">Spend</p>
                  <p className="text-xs font-medium text-gray-700">₹{fmt(geo.spend)}</p>
                </div>
                {geo.cpa !== null && (
                  <div className="text-right">
                    <p className="text-[10px] text-gray-400">CPA</p>
                    <p className="text-xs font-medium text-gray-700">₹{fmt(geo.cpa)}</p>
                  </div>
                )}
                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${roasBadge(geo.roas)}`}>
                  {geo.roas.toFixed(1)}x
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
