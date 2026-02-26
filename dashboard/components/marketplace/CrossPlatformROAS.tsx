'use client'

import { useEffect, useState } from 'react'
import { TrendingUp, Loader2 } from 'lucide-react'

interface PlatformData {
  name: string
  roas: number
  spend: number
  color: string
  barColor: string
  textColor: string
}

function fmtINR(n: number) {
  if (n >= 1_00_00_000) return `₹${(n / 1_00_00_000).toFixed(1)}Cr`
  if (n >= 1_00_000)    return `₹${(n / 1_00_000).toFixed(1)}L`
  if (n >= 1_000)       return `₹${(n / 1_000).toFixed(1)}K`
  return `₹${n.toFixed(0)}`
}

export default function CrossPlatformROAS({ workspaceId }: { workspaceId: string }) {
  const [platforms, setPlatforms] = useState<PlatformData[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.allSettled([
      fetch(`/api/kpi/summary?workspace_id=${workspaceId}&days=365`).then(r => r.json()),
      fetch(`/api/marketplace/campaigns?workspace_id=${workspaceId}&days=365`).then(r => r.json()),
    ]).then(([kpi, amazon]) => {
      const result: PlatformData[] = []

      if (kpi.status === 'fulfilled' && kpi.value?.platform_breakdown) {
        const meta   = kpi.value.platform_breakdown['meta']
        const google = kpi.value.platform_breakdown['google']
        if (meta && meta.spend > 0) {
          result.push({
            name: 'Meta Ads',
            roas: meta.roas || 0,
            spend: meta.spend,
            color: 'bg-blue-100',
            barColor: 'bg-blue-500',
            textColor: 'text-blue-700',
          })
        }
        if (google && google.spend > 0) {
          result.push({
            name: 'Google Ads',
            roas: google.roas || 0,
            spend: google.spend,
            color: 'bg-green-100',
            barColor: 'bg-green-500',
            textColor: 'text-green-700',
          })
        }
      }

      if (amazon.status === 'fulfilled' && amazon.value?.summary?.total_spend > 0) {
        result.push({
          name: 'Amazon Ads',
          roas: amazon.value.summary.avg_roas || 0,
          spend: amazon.value.summary.total_spend,
          color: 'bg-orange-100',
          barColor: 'bg-orange-500',
          textColor: 'text-orange-700',
        })
      }

      setPlatforms(result.sort((a, b) => b.roas - a.roas))
      setLoading(false)
    })
  }, [workspaceId])

  const maxRoas = Math.max(...platforms.map(p => p.roas), 1)

  if (!loading && platforms.length === 0) return null

  return (
    <div className="rounded-xl border border-gray-100 bg-white p-5">
      <div className="flex items-center gap-2 mb-4">
        <TrendingUp className="h-4 w-4 text-gray-500" />
        <h2 className="text-sm font-semibold text-gray-900">Cross-Platform ROAS</h2>
        <span className="text-xs text-gray-400 ml-1">All-time · Higher is better</span>
        {loading && <Loader2 className="h-3.5 w-3.5 animate-spin text-gray-300 ml-auto" />}
      </div>

      {loading ? (
        <div className="space-y-3">
          {[1, 2, 3].map(i => (
            <div key={i} className="flex items-center gap-3">
              <div className="w-24 h-4 rounded bg-gray-100 animate-pulse" />
              <div className="flex-1 h-6 rounded-full bg-gray-100 animate-pulse" />
              <div className="w-12 h-4 rounded bg-gray-100 animate-pulse" />
            </div>
          ))}
        </div>
      ) : (
        <div className="space-y-3">
          {platforms.map(p => (
            <div key={p.name}>
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-medium text-gray-700">{p.name}</span>
                <div className="flex items-center gap-3">
                  <span className="text-[10px] text-gray-400">{fmtINR(p.spend)} spend</span>
                  <span className={`text-xs font-bold ${p.textColor}`}>
                    {p.roas > 0 ? `${p.roas.toFixed(2)}x` : '—'}
                  </span>
                </div>
              </div>
              <div className={`h-5 rounded-full overflow-hidden ${p.color}`}>
                <div
                  className={`h-full rounded-full ${p.barColor} transition-all duration-700`}
                  style={{ width: `${Math.max((p.roas / maxRoas) * 100, 2)}%` }}
                />
              </div>
            </div>
          ))}
          {platforms.length > 0 && (
            <p className="text-[10px] text-gray-400 pt-1 text-right">
              Target ROAS: 2.5x · {platforms[0]?.name} leads at {platforms[0]?.roas.toFixed(2)}x
            </p>
          )}
        </div>
      )}
    </div>
  )
}
