'use client'

import { useEffect, useState } from 'react'
import { Type, Loader2 } from 'lucide-react'

interface AssetRow {
  asset_text: string
  asset_type: string
  performance_label: string
  campaign_name: string
  ad_group_name: string
  impressions: number
  clicks: number
}

interface AssetsData {
  has_data: boolean
  last_upload_date: string | null
  assets: AssetRow[]
}

function labelBadge(label: string) {
  switch (label.toUpperCase()) {
    case 'BEST': return 'bg-green-100 text-green-700 border-green-200'
    case 'GOOD': return 'bg-yellow-100 text-yellow-700 border-yellow-200'
    case 'LOW':  return 'bg-red-100 text-red-700 border-red-200'
    default:     return 'bg-gray-100 text-gray-500 border-gray-200'
  }
}

export default function GoogleAdsAssets({ workspaceId }: { workspaceId: string }) {
  const [data, setData] = useState<AssetsData | null>(null)
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<'Headline' | 'Description' | 'All'>('Headline')

  useEffect(() => {
    fetch(`/api/google-ads/assets?workspace_id=${workspaceId}`)
      .then(r => r.json())
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [workspaceId])

  const filtered = data?.assets.filter(a =>
    tab === 'All' ? true : a.asset_type.toLowerCase().includes(tab.toLowerCase())
  ) ?? []

  return (
    <div className="rounded-xl border border-gray-200 overflow-hidden">
      <div className="bg-gray-50 px-4 py-3 border-b border-gray-200 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-gray-700 flex items-center gap-1.5">
            <Type className="h-3.5 w-3.5 text-pink-600" />
            Ad Asset Performance (RSA)
          </h2>
          <p className="text-xs text-gray-600">Which headlines Google rates as BEST vs LOW</p>
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
          No asset data yet — upload an Ad Assets / RSA report
        </div>
      ) : (
        <>
          <div className="flex border-b border-gray-100 px-4 pt-2">
            {(['Headline', 'Description', 'All'] as const).map(t => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`mr-3 pb-2 text-xs font-medium border-b-2 transition-colors ${
                  tab === t ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'
                }`}
              >
                {t}
              </button>
            ))}
          </div>

          <div className="divide-y divide-gray-50 max-h-72 overflow-y-auto">
            {filtered.slice(0, 40).map((asset, i) => (
              <div key={i} className="flex items-start gap-3 px-4 py-2.5">
                <span className={`mt-0.5 shrink-0 rounded border px-1.5 py-0.5 text-[9px] font-bold uppercase ${labelBadge(asset.performance_label)}`}>
                  {asset.performance_label}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-xs text-gray-800 leading-snug">{asset.asset_text}</p>
                  {asset.campaign_name && (
                    <p className="text-[10px] text-gray-400 mt-0.5 truncate">{asset.campaign_name}</p>
                  )}
                </div>
                <div className="shrink-0 text-right">
                  <p className="text-[10px] text-gray-400">{asset.impressions.toLocaleString()} impr</p>
                  <p className="text-[10px] text-gray-500">{asset.clicks} clicks</p>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
